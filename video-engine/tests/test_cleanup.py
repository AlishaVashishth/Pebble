"""Tests for workspace cleanup, retention expiration, and size cap enforcement."""

import os
import shutil
import time
from pathlib import Path

import pytest

from pebble.cleanup import cleanup_workspace, delete_job_folder, get_path_size
from pebble.jobs import JobStore, STATUS_COMPLETED, STATUS_FAILED, STATUS_PROCESSING, STATUS_QUEUED
from pebble.workspace import JobWorkspace, get_workspace_root


@pytest.fixture
def temp_workspace(tmp_path: Path):
    """Temporary isolated workspace root for cleanup testing."""
    ws = tmp_path / "test_workspace"
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def _create_mock_job_folder(
    workspace_root: Path,
    job_id: str,
    size_kb: int = 100,
    age_days: float = 0.0,
) -> Path:
    """Helper to create a job folder with subdirectories and mock files."""
    folder = workspace_root / job_id
    folder.mkdir(parents=True, exist_ok=True)
    media_dir = folder / "media" / "Scene1"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Write payload file to reach desired size
    data = b"x" * (size_kb * 1024)
    (media_dir / "Scene1.mp4").write_bytes(data)
    (folder / "animation.py").write_text("class Scene1: pass", encoding="utf-8")

    # Set modification time based on age_days
    past_time = time.time() - (age_days * 86400.0) - 100.0
    os.utime(folder, (past_time, past_time))
    for p in folder.rglob("*"):
        os.utime(p, (past_time, past_time))
    return folder


def test_delete_job_folder_success(temp_workspace: Path):
    """delete_job_folder immediately removes the folder and reports freed MB."""
    job_dir = _create_mock_job_folder(temp_workspace, "job_test_01", size_kb=2048)
    assert job_dir.exists()

    freed_mb = delete_job_folder("job_test_01", workspace_root=temp_workspace)
    assert not job_dir.exists()
    assert freed_mb >= 2.0


def test_retention_days_cleanup(temp_workspace: Path):
    """Old failed job folders older than retention_days are removed, newer ones kept."""
    # 5 days old (should be removed when retention_days=3)
    old_job = _create_mock_job_folder(temp_workspace, "job_old", size_kb=1024, age_days=5.0)
    # 1 day old (should be kept)
    new_job = _create_mock_job_folder(temp_workspace, "job_new", size_kb=1024, age_days=1.0)

    freed_mb = cleanup_workspace(
        workspace_root=temp_workspace,
        retention_days=3.0,
        max_gb=10.0,
    )

    assert not old_job.exists()
    assert new_job.exists()
    assert freed_mb >= 1.0


def test_size_cap_enforcement_deletes_oldest_first(temp_workspace: Path):
    """When workspace exceeds max_gb, oldest folders are deleted first until under cap."""
    # Create 3 jobs, total ~6 MB
    job1 = _create_mock_job_folder(temp_workspace, "job_1_oldest", size_kb=2048, age_days=2.0)
    job2 = _create_mock_job_folder(temp_workspace, "job_2_middle", size_kb=2048, age_days=1.5)
    job3 = _create_mock_job_folder(temp_workspace, "job_3_newest", size_kb=2048, age_days=0.5)

    # Set cap to 0.003 GB (~3.0 MB) so at least 1 or 2 folders must be deleted
    freed_mb = cleanup_workspace(
        workspace_root=temp_workspace,
        retention_days=10.0,  # High retention so only size cap triggers deletion
        max_gb=0.003,
    )

    # Oldest must be deleted first
    assert not job1.exists()
    assert job3.exists()
    assert freed_mb >= 2.0


def test_active_and_running_jobs_are_never_deleted(temp_workspace: Path):
    """A job that is still running is NEVER deleted even if old or over size cap."""
    running_job = _create_mock_job_folder(
        temp_workspace, "job_active_running", size_kb=3072, age_days=10.0
    )

    # Mock JobStore with this job active
    store_db = temp_workspace / "jobs.db"
    store = JobStore(path=store_db)
    store.init()
    job = store.create("fingerprint123", {"title": "Active Job"})
    job_id = job["job_id"]
    store.set_status(job_id, STATUS_PROCESSING)

    # Create folder matching the active job ID
    running_job = _create_mock_job_folder(
        temp_workspace, job_id, size_kb=3072, age_days=10.0
    )

    freed_mb = cleanup_workspace(
        workspace_root=temp_workspace,
        store=store,
        retention_days=1.0,
        max_gb=0.001,  # Strict cap
    )

    # Running job MUST be preserved
    assert running_job.exists()


def test_pebble_workspace_dir_configurable(tmp_path: Path, monkeypatch):
    """PEBBLE_WORKSPACE_DIR env var configures the workspace root path."""
    custom_dir = tmp_path / "custom_pebble_workspace"
    monkeypatch.setenv("PEBBLE_WORKSPACE_DIR", str(custom_dir))

    resolved = get_workspace_root()
    assert resolved == custom_dir.resolve()

    ws = JobWorkspace("job_custom_loc")
    assert ws.root == custom_dir.resolve() / "job_custom_loc"
    assert ws.media_dir == custom_dir.resolve() / "job_custom_loc" / "media"
    assert ws.media_dir.exists()
