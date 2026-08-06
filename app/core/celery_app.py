import os
from celery import Celery

# Redis configuration for the Celery Broker and Backend
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "smallbook_worker",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# Optional: Configure Celery settings (e.g., timezone, task serialization)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@celery_app.task(name="process_pdf_task")
def process_pdf_task(source_id: str, user_id: str):
    """
    DUMMY TASK PREVIEW:
    In the next phase, this function will execute inside your isolated worker.
    It will download the PDF, run pymupdf4llm, chunk with tiktoken, 
    and store embeddings in FAISS/Qdrant.
    """
    pass