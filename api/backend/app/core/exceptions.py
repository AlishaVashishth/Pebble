"""Safe exception handling and custom application errors."""

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def format_validation_error(exc: RequestValidationError) -> str:
    """Format the first validation error into a clear human-readable string."""
    errors = exc.errors()
    if not errors:
        return "Invalid request parameters."
    first = errors[0]
    loc = first.get("loc", [])
    field = str(loc[-1]) if loc else "field"
    err_type = str(first.get("type", ""))
    msg = str(first.get("msg", ""))

    if field == "password" and ("too_short" in err_type or "at least 8" in msg.lower()):
        return "Password must be at least 8 characters."
    if field == "email":
        return "Please enter a valid email address."
    if err_type == "missing":
        return f"{field.replace('_', ' ').capitalize()} is required."

    clean_msg = msg
    if clean_msg.startswith("Value error, "):
        clean_msg = clean_msg[len("Value error, "):]
    return f"{clean_msg[0].upper()}{clean_msg[1:]}" if clean_msg else "Invalid request parameters."


def setup_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers preventing stack trace leakage."""

    @app.middleware("http")
    async def safe_error_middleware(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "Something went wrong. Please try again.",
                    "detail": "Something went wrong. Please try again.",
                },
            )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
        human_msg = format_validation_error(exc)
        return JSONResponse(
            status_code=422,
            content={
                "error": "validation_error",
                "message": human_msg,
                "detail": human_msg,
                "details": [
                    {"loc": err.get("loc"), "msg": err.get("msg"), "type": err.get("type")}
                    for err in exc.errors()
                ],
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        if isinstance(exc.detail, dict):
            return JSONResponse(status_code=exc.status_code, content=exc.detail)
        msg = exc.detail if isinstance(exc.detail, str) else "An error occurred"
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "http_error",
                "message": msg,
                "detail": msg,
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception on %s: %s", request.url.path, type(exc).__name__, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": "Something went wrong. Please try again.",
                "detail": "Something went wrong. Please try again.",
            },
        )
