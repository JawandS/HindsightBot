import logging
import os
import threading
import time
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from agents.investigator import investigate
from agents.scheduler import schedule_next_check
from db.models import Collection, Prediction, Investigation, Source, Job, VerdictStatus, JobStatus
from db.session import SessionLocal, get_db
from web.auth import require_admin

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "43200"))
STUCK_THRESHOLD_MINUTES = 30


# ── Background worker ─────────────────────────────────────────────────────────

def _reset_stuck_jobs(db: Session) -> None:
    cutoff = datetime.utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    stuck = (
        db.query(Job)
        .filter(Job.status == JobStatus.RUNNING, Job.started_at < cutoff)
        .all()
    )
    for job in stuck:
        job.status = JobStatus.PENDING
        job.started_at = None
    if stuck:
        db.commit()
        logger.info("Reset %d stuck jobs", len(stuck))


def _promote_due_predictions(db: Session) -> None:
    now = datetime.utcnow()
    already_queued = (
        db.query(Job.prediction_id)
        .filter(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .scalar_subquery()
    )
    due = (
        db.query(Prediction)
        .filter(
            Prediction.status == VerdictStatus.UNRESOLVED,
            Prediction.next_check_at <= now,
            ~Prediction.id.in_(already_queued),
        )
        .all()
    )
    for pred in due:
        db.add(Job(prediction_id=pred.id))
    if due:
        db.commit()
        logger.info("Promoted %d predictions to pending jobs", len(due))


def _claim_next_job(db: Session) -> Job | None:
    job = (
        db.query(Job)
        .filter(Job.status == JobStatus.PENDING)
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.started_at = datetime.utcnow()
    db.commit()
    return job


def _process_job(db: Session, job: Job) -> None:
    pred = (
        db.query(Prediction)
        .join(Collection)
        .filter(Prediction.id == job.prediction_id)
        .one()
    )
    try:
        result = investigate(prediction_text=pred.text, collection_name=pred.collection.name)

        inv = Investigation(
            prediction_id=pred.id,
            verdict=VerdictStatus(result.verdict),
            summary=result.summary,
        )
        db.add(inv)
        db.flush()

        for src in result.sources:
            db.add(Source(
                investigation_id=inv.id,
                url=src.get("url", ""),
                title=src.get("title", ""),
                relevance_summary=src.get("relevance_summary", ""),
            ))

        pred.status = VerdictStatus(result.verdict)
        pred.summary = result.summary
        pred.updated_at = datetime.utcnow()
        job.status = JobStatus.DONE
        job.completed_at = datetime.utcnow()
        db.commit()
        logger.info("Job %d: prediction %d → %s", job.id, pred.id, result.verdict)

        if result.verdict == "unresolved":
            schedule_result = schedule_next_check(pred.text, result.summary)
            pred.next_check_at = schedule_result.next_check_at
            db.commit()
            logger.info("Next check in %d %s", schedule_result.value, schedule_result.unit)

    except Exception as exc:
        db.rollback()
        job.status = JobStatus.FAILED
        job.completed_at = datetime.utcnow()
        job.error_message = str(exc)
        db.commit()
        logger.error("Job %d failed: %s", job.id, exc)


def _poll_cycle(db: Session) -> None:
    _reset_stuck_jobs(db)
    _promote_due_predictions(db)
    while True:
        job = _claim_next_job(db)
        if job is None:
            break
        _process_job(db, job)


def _worker_loop() -> None:
    logger.info("Background worker started — poll interval=%ds", POLL_INTERVAL)
    while True:
        db = SessionLocal()
        try:
            _poll_cycle(db)
        except Exception as exc:
            logger.error("Poll cycle error: %s", exc)
        finally:
            db.close()
        time.sleep(POLL_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_worker_loop, daemon=True, name="worker")
    t.start()
    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="HindsightBot", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ── Public routes ─────────────────────────────────────────────────────────────

_STATUS_ORDER = {"came_true": 0, "came_false": 1, "unresolved": 2}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    collections = db.query(Collection).order_by(Collection.created_at).all()
    for collection in collections:
        collection.predictions.sort(
            key=lambda p: (_STATUS_ORDER[p.status.value], -p.updated_at.timestamp())
        )
    return templates.TemplateResponse("public/index.html", {"request": request, "collections": collections})


@app.get("/predictions/{prediction_id}/detail", response_class=HTMLResponse)
def prediction_detail(prediction_id: int, request: Request, db: Session = Depends(get_db)):
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if pred is None:
        raise HTTPException(status_code=404, detail="Prediction not found")
    return templates.TemplateResponse("public/_prediction_detail.html", {"request": request, "prediction": pred})


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_index(request: Request, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    collections = db.query(Collection).order_by(Collection.created_at).all()
    predictions = db.query(Prediction).order_by(Prediction.collection_id, Prediction.id).all()
    return templates.TemplateResponse(
        "admin/index.html",
        {"request": request, "collections": collections, "predictions": predictions},
    )


@app.post("/admin/collections", response_class=RedirectResponse)
def admin_create_collection(
    name: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    db.add(Collection(name=name.strip(), description=description.strip() or None))
    db.commit()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/predictions/{prediction_id}/investigate", response_class=HTMLResponse)
def admin_investigate_now(
    prediction_id: int,
    request: Request,
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    pred = db.query(Prediction).filter(Prediction.id == prediction_id).first()
    if pred is None:
        raise HTTPException(status_code=404)
    existing = (
        db.query(Job)
        .filter(Job.prediction_id == prediction_id, Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .first()
    )
    if existing is None:
        db.add(Job(prediction_id=prediction_id))
        db.commit()
    return templates.TemplateResponse(
        "admin/_investigate_btn.html",
        {"request": request, "prediction_id": prediction_id},
    )


@app.post("/admin/investigate-all", response_class=HTMLResponse)
def admin_investigate_all(request: Request, db: Session = Depends(get_db), _: str = Depends(require_admin)):
    already_queued = (
        db.query(Job.prediction_id)
        .filter(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .scalar_subquery()
    )
    due = (
        db.query(Prediction)
        .filter(Prediction.status == VerdictStatus.UNRESOLVED, ~Prediction.id.in_(already_queued))
        .all()
    )
    for pred in due:
        db.add(Job(prediction_id=pred.id))
    db.commit()
    return templates.TemplateResponse("admin/_bulk_result.html", {"request": request, "count": len(due)})


@app.post("/admin/seed", response_class=HTMLResponse)
def admin_seed(
    request: Request,
    collection_id: int = Form(...),
    predictions_text: str = Form(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_admin),
):
    collection = db.query(Collection).filter(Collection.id == collection_id).first()
    if collection is None:
        raise HTTPException(status_code=404)

    existing_normalized = {
        _normalize(p.text)
        for p in db.query(Prediction).filter(Prediction.collection_id == collection_id).all()
    }

    added, skipped = 0, 0
    for line in predictions_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if _normalize(line) in existing_normalized:
            skipped += 1
        else:
            db.add(Prediction(collection_id=collection_id, text=line))
            existing_normalized.add(_normalize(line))
            added += 1

    db.commit()
    return templates.TemplateResponse(
        "admin/_seed_result.html",
        {"request": request, "added": added, "skipped": skipped},
    )


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())
