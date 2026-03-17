import os
import unicodedata
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from db.models import Collection, Prediction, Job, VerdictStatus, JobStatus
from db.session import get_db
from web.auth import require_admin

app = FastAPI(title="HindsightBot")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# ── Public routes ────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    collections = db.query(Collection).order_by(Collection.created_at).all()
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


# ── Admin routes ─────────────────────────────────────────────────────────────

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
        .subquery()
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
