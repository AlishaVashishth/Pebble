"""API route for POST /playground endpoint."""

import logging
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.core.rate_limit import limiter
from backend.app.db.session import get_db
from backend.app.execution.runner import execute_code
from backend.app.models.user import User
from backend.app.schemas.playground import (
    ExecuteRequest,
    ExecuteResponse,
    PlaygroundRequest,
    PlaygroundResponse,
)
from backend.app.services.playground_service import PlaygroundService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Playground"])


@router.post("/playground", response_model=PlaygroundResponse)
@limiter.limit("20/minute")
def run_playground(
    request: Request,
    payload: PlaygroundRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PlaygroundResponse:
    """
    Submit code to explain or a problem to solve in the Playground.

    Rate limit: 20 requests/minute per authenticated user.
    - mode='explain': Accepts user code and returns a step-by-step explanation.
    - mode='solve': Accepts a problem description, searches the DB first,
                    then falls back to LLM generation.
    """
    logger.info(
        "Processing /playground request for user_id=%s, mode=%s, language=%s",
        current_user.id,
        payload.mode,
        payload.language,
    )
    service = PlaygroundService()
    return service.run(db=db, req=payload)


@router.post("/playground/execute", response_model=ExecuteResponse)
@limiter.limit("15/minute")
def execute_playground_code(
    request: Request,
    payload: ExecuteRequest,
    current_user: User = Depends(get_current_user),
) -> ExecuteResponse:
    """
    Execute user-submitted code in an isolated subprocess.

    Rate limit: 15 requests/minute per authenticated user.
    - Never executed inside the main FastAPI application process.
    - Runs in an isolated subprocess with hard timeout.
    - Standard input (custom_input) is passed to stdin.
    - Supports Python (with step-by-step trace), Java, and C++.
    """
    logger.info(
        "Processing /playground/execute for user_id=%s, language=%s, code_len=%d",
        current_user.id,
        payload.language,
        len(payload.code),
    )
    result = execute_code(
        language=payload.language,
        code=payload.code,
        stdin_text=payload.custom_input or "",
        timeout=payload.timeout_seconds,
    )
    return ExecuteResponse(**result.model_dump())

