"""Video generation and job polling API routes."""

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from backend.app.core.dependencies import get_current_user
from backend.app.core.rate_limit import limiter
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.video import (
    CreateVideoJobRequest,
    VideoJobResponse,
    VideoJobStatusResponse,
    VideoResultResponse,
)
from backend.app.services.video_service import VideoService

router = APIRouter(prefix="/video-jobs", tags=["Video Jobs"])


def get_video_service() -> VideoService:
    """Dependency injector for VideoService."""
    return VideoService()


@router.post(
    "",
    response_model=VideoJobResponse,
    summary="Create or retrieve a video generation job",
)
@limiter.limit("30/minute")
def create_video_job(
    request: Request,
    payload: CreateVideoJobRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoJobResponse:
    """Create a video generation job or return existing cached/running job."""
    return service.create_video_job(
        db=db,
        user=current_user,
        req=payload,
        background_tasks=background_tasks,
    )


@router.get(
    "/{id}",
    response_model=VideoJobResponse,
    summary="Get video job status",
)
def get_video_job(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoJobResponse:
    """Poll the status and stage of a video job (owner only)."""
    return service.get_job(db=db, job_id=id, user=current_user)


@router.get(
    "/{id}/status",
    response_model=VideoJobStatusResponse,
    summary="Get video job polling status (queued | processing | completed | failed)",
)
def get_video_job_status(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoJobStatusResponse:
    """Poll video job status with standardized processing/completed status and videoUrl."""
    job = service.get_job(db=db, job_id=id, user=current_user)
    mapped_status = "processing" if job.status == "running" else job.status
    return VideoJobStatusResponse(
        id=job.id,
        status=mapped_status,
        stage=job.stage,
        videoUrl=job.video_url,
        video_url=job.video_url,
        error=job.error,
        queue_position=job.queue_position,
        elapsed_seconds=job.elapsed_seconds,
    )


status_router = APIRouter(prefix="/video", tags=["Video"])


@status_router.get(
    "/{id}/status",
    response_model=VideoJobStatusResponse,
    summary="Get video job status via /video/:jobId/status",
)
def get_video_status_alias(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoJobStatusResponse:
    """Alias for /video-jobs/{id}/status conforming to GET /video/:jobId/status."""
    return get_video_job_status(id=id, current_user=current_user, db=db, service=service)


@status_router.get(
    "/{id}",
    response_model=VideoJobResponse,
    summary="Get video job via /video/:jobId",
)
def get_video_job_alias(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoJobResponse:
    """Alias for /video-jobs/{id}."""
    return service.get_job(db=db, job_id=id, user=current_user)


@router.get(
    "/{id}/result",
    response_model=VideoResultResponse,
    summary="Get completed video artifact result",
)
def get_video_result(
    id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoResultResponse:
    """Fetch completed video URL and blob name (owner only, 409 if still processing, 400 if failed)."""
    return service.get_job_result(db=db, job_id=id, user=current_user)


@router.post(
    "/{id}/retry",
    response_model=VideoJobResponse,
    summary="Retry a failed video generation job",
)
def retry_video_job(
    id: str,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: VideoService = Depends(get_video_service),
) -> VideoJobResponse:
    """Retry a failed video job (owner only, only failed jobs)."""
    return service.retry_job(
        db=db,
        job_id=id,
        user=current_user,
        background_tasks=background_tasks,
    )
