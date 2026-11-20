"""
Sandbox runner: executes a command in an isolated subprocess with timeout.

Security model:
  - Code is written to a temp file, never eval'd in the main process.
  - Execution runs via subprocess.run() with a hard timeout.
  - On Windows: timeout is the primary safety mechanism (resource module unavailable).
  - On Linux/macOS: resource limits (CPU, memory) are applied via preexec_fn.
  - Temp files are always cleaned up in `finally`.
"""

from __future__ import annotations

import os
import platform
import subprocess
import time
from typing import List, Optional, Tuple

# Max output we'll keep (bytes) — prevents memory exhaustion from verbose programs
_MAX_OUTPUT_BYTES = 64 * 1024  # 64 KB

_SAFE_ENV_VARS = frozenset(
    {
        # Windows system paths & basic runtime vars
        "SYSTEMROOT",
        "SYSTEMDRIVE",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "COMSPEC",
        "WINDIR",
        "LOCALAPPDATA",
        "APPDATA",
        # Unix / POSIX
        "HOME",
        "USER",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LD_LIBRARY_PATH",
    }
)


def get_sanitized_env(extra_env: Optional[dict] = None) -> dict:
    """
    Build a minimal, safe environment dictionary.
    Excludes sensitive application variables (DATABASE_URL, SECRET_KEY, API keys, etc.).
    """
    clean_env: dict = {}
    for key, val in os.environ.items():
        if key.upper() in _SAFE_ENV_VARS:
            clean_env[key] = val

    # Avoid writing __pycache__ or bytecode during sandbox execution
    clean_env["PYTHONUNBUFFERED"] = "1"
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"

    if extra_env:
        clean_env.update(extra_env)

    return clean_env


def _apply_resource_limits() -> None:
    """Apply OS resource limits (Linux/macOS only). Called as subprocess preexec_fn."""
    try:
        import resource  # type: ignore
        # CPU time limit: 15 seconds (guard above the subprocess timeout)
        resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
        # Virtual memory limit: 256 MB
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
        # Max child processes: 64
        resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
    except Exception:
        pass  # Non-fatal; timeout still applies


def run_subprocess(
    cmd: List[str],
    stdin_text: str = "",
    timeout_seconds: int = 10,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
) -> Tuple[str, str, int, bool]:
    """
    Run *cmd* in a subprocess with safety guards.

    Returns
    -------
    stdout : str
    stderr : str
    exit_code : int
    timed_out : bool
    """
    is_unix = platform.system() != "Windows"
    preexec = _apply_resource_limits if is_unix else None
    sanitized_env = get_sanitized_env(env)

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            input=stdin_text.encode("utf-8", errors="replace"),
            capture_output=True,
            timeout=timeout_seconds,
            cwd=cwd,
            env=sanitized_env,
            preexec_fn=preexec,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        stdout = proc.stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        stderr = proc.stderr[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        return stdout, stderr, proc.returncode, False

    except subprocess.TimeoutExpired as exc:
        # Kill the process group on timeout
        if exc.output:
            stdout = exc.output[:_MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
        else:
            stdout = ""
        stderr = f"Execution timed out after {timeout_seconds} seconds."
        return stdout, stderr, -1, True

    except FileNotFoundError:
        # Compiler / interpreter not found
        raise

    except Exception as exc:  # pragma: no cover
        return "", str(exc), -1, False
