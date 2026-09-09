from app.routers.auth import router as auth_router
from app.routers.notebooks import router as notebooks_router
from app.routers.sources import router as sources_router, global_sources_router
from app.routers.chat import router as chat_router
from app.routers.llm_settings import router as llm_settings_router
from app.routers.study import router as study_router

__all__ = [
    "auth_router",
    "notebooks_router",
    "sources_router",
    "global_sources_router",
    "chat_router",
    "llm_settings_router",
    "study_router",
]
