from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import auth
from app.config import PROJECT_ROOT, settings
from app.services import vault as vault_svc
from app.routers import auth as auth_router
from app.routers import browse as browse_router
from app.routers import capture as capture_router
from app.routers import config as config_router
from app.routers import import_chats as import_router
from app.routers import search as search_router
from app.routers import settings as settings_router
from app.services import runtime_settings


def create_app() -> FastAPI:
    settings.ensure_vault_dirs()
    vault_svc.ensure_obsidian_graph_config()
    runtime_settings.apply_overrides()  # layer _meta/config.json on top of .env
    auth.bootstrap_from_env()

    app = FastAPI(title="Second Brain", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "vault": str(settings.vault_root),
            "active_provider": settings.active_provider,
            "auth_configured": auth.has_password(),
        }

    app.include_router(auth_router.router)
    app.include_router(capture_router.router)
    app.include_router(search_router.router)
    app.include_router(import_router.router)
    app.include_router(browse_router.router)
    app.include_router(config_router.router)
    app.include_router(settings_router.router)

    # Serve PWA static files at root. MUST be mounted last so /api/* routes take priority.
    frontend_dir = PROJECT_ROOT / "frontend"
    if frontend_dir.exists():
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app


app = create_app()
