import logging
import os
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from agents.investigator import investigate
from agents.scheduler import schedule_next_check
from db.models import Collection, Prediction, Investigation, Source, Job, VerdictStatus, JobStatus
from db.session import SessionLocal

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

STUCK_THRESHOLD_MINUTES = 30
POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "300"))


def reset_stuck_jobs(db: Session) -> int:
    """Reset jobs stuck in 'running' for too long back to 'pending'."""
    cutoff = datetime.utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)
    stuck = (
        db.query(Job)
        .filter(Job.status == JobStatus.RUNNING, Job.started_at < cutoff)
        .all()
    )
    for job in stuck:
        job.status = JobStatus.PENDING
        job.started_at = None
    db.commit()
    if stuck:
        logger.info("Reset %d stuck jobs", len(stuck))
    return len(stuck)


def promote_due_predictions(db: Session) -> int:
    """Create pending jobs for unresolved predictions whose next_check_at has elapsed."""
    now = datetime.utcnow()
    already_queued = (
        db.query(Job.prediction_id)
        .filter(Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .subquery()
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
    db.commit()
    if due:
        logger.info("Promoted %d predictions to pending jobs", len(due))
    return len(due)


def claim_next_job(db: Session) -> Job | None:
    """Atomically claim the next pending job. Returns None if queue is empty."""
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


def process_job(db: Session, job: Job) -> None:
    """Run investigation + scheduling for a job."""
    pred = (
        db.query(Prediction)
        .join(Collection)
        .filter(Prediction.id == job.prediction_id)
        .one()
    )

    try:
        result = investigate(
            prediction_text=pred.text,
            collection_name=pred.collection.name,
        )

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


def run_poll_cycle(db: Session) -> None:
    reset_stuck_jobs(db)
    promote_due_predictions(db)
    while True:
        job = claim_next_job(db)
        if job is None:
            break
        process_job(db, job)


def main():
    logger.info("Worker starting — poll interval=%ds", POLL_INTERVAL)
    while True:
        db = SessionLocal()
        try:
            run_poll_cycle(db)
        except Exception as exc:
            logger.error("Poll cycle error: %s", exc)
        finally:
            db.close()
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
