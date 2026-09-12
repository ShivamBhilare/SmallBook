"""
Celery Distributed Task Queue Configuration

Initializes the Celery application instance for SmallBook background task processing,
including document ingestion, chunk vectorization, and study tool generation (flashcards/quizzes).
Configures Redis as both message broker and result backend, sets task serialization policies,
and hooks into worker lifecycle signals to preload embedding models upon process fork.
"""

import os
from dotenv import load_dotenv
from celery import Celery

load_dotenv()

# Redis URL for broker queues and async task result backend persistence
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Primary Celery application instance bound to the background worker pool
celery_app = Celery(
    "smallbook_worker",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "app.services.ingestion.celery_tasks",
        "app.services.study.celery_tasks"
    ]
)
celery_app.set_default()

# Celery operational settings: strict JSON serialization, UTC timestamps, and connection retry resiliency
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    broker_connection_timeout=10.0,
    broker_transport_options={'max_retries': 3, 'timeout': 5.0},
    result_backend_transport_options={'retry_policy': {'timeout': 5.0, 'max_retries': 3}},
)

from celery.signals import worker_process_init

@worker_process_init.connect
def preload_models(**kwargs):
    """
    Worker Process Initialization Hook.

    Preloads the sentence-transformer embedding model directly into memory
    when a Celery worker process initializes. This eliminates first-inference
    cold start latency during document ingestion and vectorization.

    Args:
        **kwargs: Signal keyword arguments dispatched by Celery on process init.
    """
    try:
        from app.services.ingestion.qdrant_db import get_embedding_model
        get_embedding_model()
    except Exception as e:
        print(f"Warning: Preloading embedding model failed: {e}")