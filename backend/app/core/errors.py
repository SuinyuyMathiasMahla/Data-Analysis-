"""Uniform API errors.

Every error response has the shape
    {"error": {"code": "...", "message": "...", "details": ...}}
Unexpected exceptions are logged with their stack trace on the server and
returned to the client as a generic message - never with internals.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.ai.providers import AIUnavailableError
from app.statistics.utils import AnalysisError, InsufficientDataError, MethodNotImplementedError

logger = logging.getLogger("app.errors")


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: object | None = None) -> None:
        super().__init__(message)
        self.status_code, self.code, self.message, self.details = status_code, code, message, details


def not_found(what: str = "Resource") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found.")


def forbidden(message: str = "You do not have permission to do this.") -> ApiError:
    return ApiError(403, "forbidden", message)


def bad_request(message: str, code: str = "bad_request", details: object | None = None) -> ApiError:
    return ApiError(400, code, message, details)


def _body(code: str, message: str, details: object | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(MethodNotImplementedError)
    async def _not_implemented(_: Request, exc: MethodNotImplementedError):
        return JSONResponse(_body("method_not_implemented", str(exc)), status_code=501)

    @app.exception_handler(InsufficientDataError)
    async def _insufficient(_: Request, exc: InsufficientDataError):
        return JSONResponse(_body("insufficient_data", str(exc)), status_code=422)

    @app.exception_handler(AnalysisError)
    async def _analysis(_: Request, exc: AnalysisError):
        return JSONResponse(_body("analysis_error", str(exc)), status_code=422)

    @app.exception_handler(AIUnavailableError)
    async def _ai(_: Request, exc: AIUnavailableError):
        return JSONResponse(_body("ai_unavailable", str(exc)), status_code=503)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        problems = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()]
        first = problems[0] if problems else {"field": "", "message": "Invalid request."}
        message = f"{first['field']}: {first['message']}" if first["field"] else first["message"]
        return JSONResponse(_body("validation_error", message, problems), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException):
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed", 413: "payload_too_large",
                429: "rate_limited"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(OperationalError)
    async def _database(request: Request, exc: OperationalError):
        # Wrong DATABASE_URL credentials, MySQL not running, etc. The cause is logged; the client gets no internals.
        reference = uuid.uuid4().hex[:12]
        logger.error("Database error %s on %s %s: %s", reference, request.method, request.url.path, exc.orig)
        if exc.orig is not None and exc.orig.args and exc.orig.args[0] == 1054:
            # MySQL "Unknown column": the database is older than the code (a migration has not been applied).
            return JSONResponse(_body("schema_out_of_date",
                                      "The database is missing a column the server needs: " + str(exc.orig.args[1]).split("'")[1]
                                      + ". Run the migration for this version (see backend/alembic/versions) as a database administrator. "
                                      f"Reference: {reference}"), status_code=500)
        return JSONResponse(_body("database_unavailable", "The server could not connect to its database. "
                                  f"Check DATABASE_URL in backend/.env and that MySQL is running. Reference: {reference}"),
                            status_code=503)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception):
        return unexpected_response(request, exc)


def unexpected_response(request: Request, exc: Exception) -> JSONResponse:
    """Generic 500 body; the stack trace goes to the server log only."""
    reference = uuid.uuid4().hex[:12]
    logger.error("Unhandled error %s on %s %s", reference, request.method, request.url.path, exc_info=exc)
    return JSONResponse(_body("internal_error", f"Something went wrong on the server. Reference: {reference}"), status_code=500)