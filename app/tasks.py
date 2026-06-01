"""
app/tasks.py — Celery async tasks for future use.

Currently a placeholder. Activate when:
  - Model inference exceeds 2 seconds
  - Email notifications are needed
  - Scheduled report generation is required

Setup:
  1. pip install celery redis
  2. Set CELERY_BROKER_URL=redis://localhost:6379/1 in .env
  3. Run worker:  celery -A app.tasks.celery worker --loglevel=info
"""

import os
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Celery app (lazy — only created if broker URL is configured)
# ---------------------------------------------------------------------------
_celery = None


def get_celery():
    """Return the Celery app instance, creating it lazily."""
    global _celery
    if _celery is not None:
        return _celery

    broker_url = os.environ.get('CELERY_BROKER_URL')
    if not broker_url:
        logger.info("CELERY_BROKER_URL not set — async tasks disabled.")
        return None

    from celery import Celery
    _celery = Celery(
        'heart_anomalies',
        broker=broker_url,
        backend=os.environ.get('CELERY_RESULT_BACKEND', broker_url),
    )
    _celery.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='UTC',
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,            # don't acknowledge until task completes
        worker_prefetch_multiplier=1,   # one task at a time per worker
    )
    logger.info("Celery app initialised with broker: %s", broker_url)
    return _celery


# ---------------------------------------------------------------------------
# Example async task — uncomment and customise when ready
# ---------------------------------------------------------------------------

# celery = get_celery()
# if celery:
#     @celery.task(bind=True, max_retries=3, default_retry_delay=10)
#     def async_predict(self, image_path: str, prediction_id: int):
#         """
#         Run ECG inference asynchronously.
#
#         Usage from Flask:
#             from app.tasks import async_predict
#             task = async_predict.delay(image_path, prediction_id)
#             # Return task.id to client for polling
#         """
#         from app.ai import predict_image
#         try:
#             result, confidence = predict_image(image_path)
#             # Update DB
#             from app import db, create_app
#             app = create_app()
#             with app.app_context():
#                 from app.models import Prediction
#                 pred = Prediction.query.get(prediction_id)
#                 if pred:
#                     pred.result = result
#                     pred.confidence = confidence
#                     db.session.commit()
#             return {'result': result, 'confidence': confidence}
#         except Exception as exc:
#             logger.error("async_predict failed: %s", exc)
#             self.retry(exc=exc)
