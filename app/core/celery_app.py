import os
from dotenv import load_dotenv
from celery import Celery

load_dotenv()

# Redis configuration for the Celery Broker and Backend
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

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

# Optional: Configure Celery settings (e.g., timezone, task serialization)
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
    try:
        from app.services.ingestion.qdrant_db import get_embedding_model
        get_embedding_model()
    except Exception as e:
        print(f"Warning: Preloading embedding model failed: {e}")