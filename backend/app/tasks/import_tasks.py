import asyncio
import logging
from datetime import UTC, datetime

from app.importers import get_handler
from app.importers.base import NormalizationError
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_import_job(self, job_id: str):
    """
    Process a citation import job.

    Flow:
    1. Load job from DB
    2. Instantiate the appropriate handler (z3950, manual, etc.)
    3. Fetch raw records from source
    4. Normalize each record to CitationDraft
    5. Assess quality (confidence score + warnings)
    6. Write import_items to DB
    7. Broadcast progress via WebSocket
    8. Set job status to 'awaiting_review' on completion

    Row-level errors don't abort the job — a failed row becomes an
    import_item with confidence_score=0 and a warning.
    """
    try:
        asyncio.run(_process_import_job(job_id))
    except Exception as exc:
        logger.exception("Import job %s failed: %s", job_id, exc)
        raise self.retry(exc=exc) from exc


async def _process_import_job(job_id: str):
    from app.database import AsyncSessionLocal
    from app.models.models import BackgroundJob, ImportItem

    async with AsyncSessionLocal() as db:
        job = await db.get(BackgroundJob, job_id)
        if not job:
            logger.error("Job %s not found", job_id)
            return

        job.status = "processing"
        job.started_at = datetime.now(UTC)
        await db.commit()

        _broadcast(job.payload.get("list_id"), {
            "type": "import.progress",
            "job_id": job_id,
            "status": "processing",
        })

        handler = get_handler(job.job_type.replace("import_", ""))
        processed = 0
        failed = 0

        async for raw_record in handler.fetch(job.payload):
            try:
                draft = handler.normalize(raw_record)
                score, warnings = handler.assess_quality(draft)

                item = ImportItem(
                    import_job_id=job_id,
                    raw_data=raw_record.data,
                    source_identifier=raw_record.data.get("id") or raw_record.data.get("doi"),
                    normalized_data=draft.__dict__,
                    confidence_score=score,
                    warnings=warnings,
                    status="pending_review",
                    sort_order=processed,
                )
                db.add(item)
                processed += 1

            except NormalizationError as e:
                logger.warning("Normalization failed for record in job %s: %s", job_id, e)
                item = ImportItem(
                    import_job_id=job_id,
                    raw_data=raw_record.data,
                    normalized_data={},
                    confidence_score=0.0,
                    warnings=[f"normalization_error: {str(e)}"],
                    status="pending_review",
                    sort_order=processed,
                )
                db.add(item)
                failed += 1

            if processed % 5 == 0:
                await db.commit()
                _broadcast(job.payload.get("list_id"), {
                    "type": "import.progress",
                    "job_id": job_id,
                    "processed": processed,
                    "failed": failed,
                })

        job.status = "awaiting_review"
        job.completed_at = datetime.now(UTC)
        job.result = {"processed": processed, "failed": failed}
        await db.commit()

        _broadcast(job.payload.get("list_id"), {
            "type": "import.ready_for_review",
            "job_id": job_id,
            "processed": processed,
            "failed": failed,
        })

        logger.info("Import job %s complete: %d processed, %d failed", job_id, processed, failed)


def _broadcast(list_id: str | None, message: dict):
    """Broadcast a WebSocket message to all subscribers of a list."""
    # TODO: implement via Redis pub/sub → WebSocket manager
    logger.debug("WS broadcast list=%s: %s", list_id, message)
