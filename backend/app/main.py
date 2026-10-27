"""FastAPI application factory.

Run in development:
    cd backend && uvicorn app.main:app --reload --port 8000
Interactive API docs: http://localhost:8000/api/docs
"""
from __future__ import annotations

import logging

import truststore

# Use the operating system's certificate store for outbound HTTPS (AI providers, SMTP),
# so corporate or antivirus HTTPS scanning certificates are trusted.
truststore.inject_into_ssl()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, ai, analysis, auth, datasets, evidence, projects, reports
from app.core.config import get_settings
from app.core.errors import install_error_handlers, unexpected_response


def create_app() -> FastAPI:
    settings = get_settings()
    logging.basicConfig(level=logging.INFO if not settings.is_production else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = FastAPI(title=settings.APP_NAME, version="1.0.0", docs_url=f"{settings.API_PREFIX}/docs",
                  openapi_url=f"{settings.API_PREFIX}/openapi.json", redoc_url=None)
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        try:
            response = await call_next(request)
        except Exception as exc:  # noqa: BLE001 - turned into a JSON 500 here so it still passes through CORS below
            response = unexpected_response(request, exc)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith(settings.API_PREFIX) and "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    # Added last so it is the outermost layer: error responses also carry the CORS headers,
    # otherwise the browser hides a 500 behind a misleading "blocked by CORS policy" message.
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
                       expose_headers=["Content-Disposition"])

    install_error_handlers(app)
    for module in (auth, projects, datasets, analysis, ai, evidence, reports, admin):
        app.include_router(module.router, prefix=settings.API_PREFIX)

    @app.get(f"{settings.API_PREFIX}/health", tags=["system"])
    def health():
        return {"status": "ok", "app": settings.APP_NAME, "environment": settings.APP_ENV}

    return app


app = create_app()