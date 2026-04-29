# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportMissingImports=false
"""Minimal Celery app configuration with structured JSON logging and DLQ hardening.

Key operational features:
- task_acks_late: Acknowledges messages AFTER execution, enabling redelivery on worker crash
- task_reject_on_worker_lost: Rejects tasks if worker connection is lost (prevents message loss)
- worker_cancel_long_running_tasks_on_connection_loss: Cancels hung tasks on disconnect
- DLQ monitoring: Tasks exceeding retry limits go to Dead Letter Queue (celery:unacked_index)

See DLQ_MONITORING.md for operational procedures, alerting setup, and task recovery.
"""

import logging
import os

from celery import Celery
from celery.signals import after_setup_logger
from creator_service.logging_config import setup_json_logging

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "worker-orchestrator",
    broker=redis_url,
    backend=redis_url,
    include=[
        "tasks.generate_script",
        "tasks.generate_visual_plan",
        "tasks.generate_scene_image",
        "tasks.generate_audio",
        "tasks.generate_subtitles",
        "tasks.render_video",
        "tasks.generate_paragraph_audio",
        "tasks.generate_paragraph_subtitles",
    ],
)
celery_app.conf.task_default_queue = "creator"
# DLQ Configuration: Controls message acknowledgment and failure handling
# - task_acks_late=True ensures at-least-once delivery by acknowledging AFTER execution
# - task_reject_on_worker_lost=True prevents message loss if worker dies
# This ensures failed tasks are not lost and can be replayed from the DLQ.
celery_app.conf.update(
    # Prefetch only 1 task per worker to prevent queue saturation
    worker_prefetch_multiplier=1,
    # Acknowledge messages AFTER successful execution (enables redelivery on crash)
    task_acks_late=True,
    # Reject tasks if worker connection is lost (returns to queue, not to DLQ)
    task_reject_on_worker_lost=True,
    # Cancel long-running tasks if worker disconnects
    worker_cancel_long_running_tasks_on_connection_loss=True,
)
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_cancel_long_running_tasks_on_connection_loss=True,
)


@after_setup_logger.connect
def setup_celery_logger(logger: logging.Logger, **kwargs: object) -> None:
    """Configure Celery logger with JSON formatting."""
    setup_json_logging(service_name="worker", level="INFO")


# ============================================================================
# DLQ MONITORING AND ALERTING INTEGRATION
# ============================================================================
# The Dead Letter Queue (DLQ) holds tasks that have exhausted all retries.
# Monitor the DLQ using these approaches:
#
# 1. REDIS CLI:
#    redis-cli -u redis://redis:6379/0
#    LLEN celery:unacked_index        # DLQ size
#    LRANGE celery:unacked_index 0 9 # View first 10 task IDs
#
# 2. FLOWER (Web UI):
#    http://localhost:5555
#    Tasks tab -> Filter by FAILURE state
#
# 3. PROMETHEUS:
#    Expose /metrics/dlq endpoint to track celery_dlq_size gauge
#    Alert on: celery_dlq_size > 20 for 5m (warning) or > 50 (critical)
#
# 4. PAGERDUTY / DATADOG:
#    - Configure webhook: POST /alert/dlq on DLQ size increase
#    - Monitor: celery.queue.size, celery.task.failure.rate
#
# RECOVERY:
#    Use DLQ_MONITORING.md replay_task.py script to resend failed tasks.
# ============================================================================
