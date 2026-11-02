"""Workspace disk cleanup and size cap enforcement."""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Set

from pebble.workspace import get_workspace_root

if TYPE_CHECKING:
    from pebble.jobs import JobStore

logger = logging.getLogger(__name__)

DEFAULT_RETENTION_DAYS = 3.0
DEFAULT_MAX_GB = 5.0
DEFAULT_CLEANUP_INTERVAL_HOURS = 3.0


def get_path_size(path: Path) -> int:
    """Return total recursive size of a file or directory in bytes."""
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def delete_job_folder(job_id: str, workspace_root: Path | None = None) -> float:
    """Immediately delete a job's workspace folder (including Manim media).

    Returns:
        float: Megabytes freed.
    """
    root = (Path(workspace_root) if workspace_root else get_workspace_root()) / job_id
    if not root.exists():
        return 0.0

    size_bytes = get_path_size(root)
    shutil.rmtree(root, ignore_errors=True)
    freed_mb = size_bytes / (1024 * 1024)
    logger.info("Deleted workspace for job %s (freed %.2f MB)", job_id, freed_mb)
    return freed_mb


def cleanup_workspace(
    workspace_root: Path | None = None,
    store: JobStore | None = None,
    retention_days: float | None = None,
    max_gb: float | None = None,
    active_job_ids: Set[str] | None = None,
) -> float:
    """Clean up workspace:
    1. Delete expired job folders older than retention_days (default 3 days).
    2. Enforce total workspace cap (default 5.0 GB), deleting oldest folders first.
    3. Never delete folders of active/running jobs or workspace files.

    Returns:
        float: Total Megabytes freed.
    """
    root = Path(workspace_root) if workspace_root else get_workspace_root()
    if not root.exists():
        return 0.0

    # Resolve settings
    if retention_days is None:
        try:
            retention_days = float(os.environ.get("PEBBLE_FAILED_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        except (ValueError, TypeError):
            retention_days = DEFAULT_RETENTION_DAYS

    if max_gb is None:
        try:
            max_gb = float(os.environ.get("PEBBLE_WORKSPACE_MAX_GB", DEFAULT_MAX_GB))
        except (ValueError, TypeError):
            max_gb = DEFAULT_MAX_GB

    max_bytes = int(max_gb * 1024 * 1024 * 1024)

    # Protect active / running jobs
    protected: set[str] = set(active_job_ids or ())
    if store is not None:
        try:
            protected.update(store.get_active_job_ids())
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not query active job IDs from store: %s", exc)

    now = time.time()
    total_freed_bytes = 0

    # Scan directories only (never delete jobs.db, cost_log.jsonl, etc.)
    try:
        entries = [p for p in root.iterdir() if p.is_dir()]
    except OSError as exc:
        logger.warning("could not list workspace directory %s: %s", root, exc)
        return 0.0

    candidate_folders: list[tuple[Path, float, int]] = []

    # 1. Retention-based cleanup for expired folders
    for folder in entries:
        folder_name = folder.name
        if folder_name in protected:
            continue

        try:
            mtime = folder.stat().st_mtime
        except OSError:
            continue

        # Protect folders actively touched in the last 60 seconds
        if (now - mtime) < 60:
            continue

        age_days = (now - mtime) / 86400.0
        if age_days >= retention_days:
            size = get_path_size(folder)
            shutil.rmtree(folder, ignore_errors=True)
            total_freed_bytes += size
            logger.info(
                "Cleaned expired job folder %s (age %.1f days >= %.1f days, freed %.2f MB)",
                folder_name,
                age_days,
                retention_days,
                size / (1024 * 1024),
            )
        else:
            size = get_path_size(folder)
            candidate_folders.append((folder, mtime, size))

    # 2. Size-cap enforcement: delete oldest folders first when total exceeds max_gb
    total_workspace_bytes = sum(item[2] for item in candidate_folders)
    if total_workspace_bytes > max_bytes:
        logger.info(
            "Workspace size (%.2f MB) exceeds cap (%.2f MB); trimming oldest folders",
            total_workspace_bytes / (1024 * 1024),
            max_bytes / (1024 * 1024),
        )
        # Sort oldest first (smallest mtime)
        candidate_folders.sort(key=lambda x: x[1])
        for folder, _, size in candidate_folders:
            if total_workspace_bytes <= max_bytes:
                break
            shutil.rmtree(folder, ignore_errors=True)
            total_freed_bytes += size
            total_workspace_bytes -= size
            logger.info(
                "Enforced size cap: removed old job folder %s (freed %.2f MB)",
                folder.name,
                size / (1024 * 1024),
            )

    freed_mb = total_freed_bytes / (1024 * 1024)
    if freed_mb > 0:
        logger.info("Workspace cleanup completed: freed %.2f MB", freed_mb)
    return freed_mb


class WorkspaceCleaner:
    """Background service that runs periodic workspace cleanup every few hours."""

    def __init__(
        self,
        workspace_root: Path | None = None,
        store: JobStore | None = None,
        interval_hours: float = DEFAULT_CLEANUP_INTERVAL_HOURS,
        retention_days: float = DEFAULT_RETENTION_DAYS,
        max_gb: float = DEFAULT_MAX_GB,
    ) -> None:
        self.workspace_root = workspace_root or get_workspace_root()
        self.store = store
        self.interval_seconds = max(60.0, interval_hours * 3600.0)
        self.retention_days = retention_days
        self.max_gb = max_gb
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Run initial cleanup on startup and start the periodic background loop."""
        # Initial cleanup on startup
        try:
            cleanup_workspace(
                workspace_root=self.workspace_root,
                store=self.store,
                retention_days=self.retention_days,
                max_gb=self.max_gb,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup workspace cleanup failed: %s", exc)

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="workspace-cleaner", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _run_loop(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                cleanup_workspace(
                    workspace_root=self.workspace_root,
                    store=self.store,
                    retention_days=self.retention_days,
                    max_gb=self.max_gb,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Periodic workspace cleanup failed: %s", exc)

