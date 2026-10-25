"""Render each scene with Manim, repairing the script when a scene fails.

The generated script is rendered through a wrapper file, ``animation_render.py``,
which is the script text with the helper import prepended on the *same first
line*. Line numbers therefore stay identical to ``animation.py``, which matters
for the repair loop: the stderr tail we feed back points at the real script.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from pebble.config import Settings
from pebble.cost import CostTracker, log_llm_call
from pebble.environment import EnvInfo
from pebble.errors import RenderError
from pebble.llm import LLMClient
from pebble.models import GenerationResult, SceneMeta
from pebble.mux import probe_duration
from pebble.prompt_builder import build_fixer_prompt
from pebble.validators import validate_manim_code
from pebble.workspace import JobWorkspace

logger = logging.getLogger(__name__)

MANIM_TIMEOUT = 900
ERROR_TAIL_LINES = 60

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
HELPERS_TEMPLATE = TEMPLATES_DIR / "pebble_helpers.py"
HELPER_IMPORT = "from pebble_helpers import finish_scene; "
REQUIRED_FIRST_LINE = "from manim import *"


@dataclass(frozen=True)
class SceneRender:
    index: int
    class_name: str
    video_path: Path
    duration: float
    repair_attempts: int = 0
    repairs_applied: int = 0


def tail_lines(text: str, count: int = ERROR_TAIL_LINES) -> str:
    lines = [line for line in (text or "").strip().splitlines() if line.strip()]
    return "\n".join(lines[-count:])


def strip_markdown_fences(text: str) -> str:
    """Remove ``` fences that a model added around a whole file."""
    cleaned = (text or "").strip()
    if not cleaned.startswith("```"):
        return cleaned
    first_newline = cleaned.find("\n")
    if first_newline == -1:
        return cleaned.strip("`").strip()
    body = cleaned[first_newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[: -3]
    return body.strip() + "\n"


def scene_targets(result: GenerationResult) -> list[SceneMeta]:
    """Scene metadata in the order the scenes must be rendered."""
    return list(result.meta.scenes)


def install_helpers(workspace: JobWorkspace) -> Path:
    """Copy the pipeline helper module next to the script (found via cwd)."""
    if not HELPERS_TEMPLATE.exists():
        raise RenderError(f"helper template is missing: {HELPERS_TEMPLATE}")
    shutil.copyfile(HELPERS_TEMPLATE, workspace.helpers_path)
    return workspace.helpers_path


def build_render_script(workspace: JobWorkspace) -> Path:
    """Write animation_render.py: helper import + script on the same first line."""
    script = workspace.animation_path.read_text(encoding="utf-8")
    first_line = script.splitlines()[0].strip() if script.strip() else ""
    if first_line != REQUIRED_FIRST_LINE:
        raise RenderError(
            "animation.py must start with 'from manim import *' "
            f"(found {first_line[:60]!r}); cannot attach the finish_scene helper"
        )
    workspace.animation_render_path.write_text(HELPER_IMPORT + script, encoding="utf-8")
    return workspace.animation_render_path


class SceneRenderer:
    """Owns the current animation.py and the per-scene repair loop."""

    def __init__(
        self,
        workspace: JobWorkspace,
        settings: Settings,
        env_info: EnvInfo,
        expected_names: list[str],
        client: LLMClient | None = None,
        cost: CostTracker | None = None,
    ) -> None:
        self.workspace = workspace
        self.settings = settings
        self.env_info = env_info
        self.expected_names = list(expected_names)
        self._client = client
        self.cost = cost

    @property
    def client(self) -> LLMClient:
        if self._client is None:
            self._client = LLMClient(self.settings)
        return self._client

    # -- manim ---------------------------------------------------------
    def _run_manim(self, class_name: str) -> tuple[Path | None, str]:
        media_dir = self.workspace.media_dir / class_name
        quality = f"-q{self.settings.render_quality}"
        cmd = [
            sys.executable,
            "-m",
            "manim",
            "render",
            quality,
            "--disable_caching",
            "--media_dir",
            str(media_dir),
            "-o",
            class_name,
            str(self.workspace.animation_render_path),
            class_name,
        ]

        started = time.monotonic()
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self.workspace.root),
                capture_output=True,
                text=True,
                timeout=MANIM_TIMEOUT,
            )
            stdout, stderr, code = completed.stdout, completed.stderr, completed.returncode
        except subprocess.TimeoutExpired:
            return None, f"manim timed out after {MANIM_TIMEOUT}s rendering {class_name}"
        except OSError as exc:
            return None, f"manim could not start: {exc}"

        elapsed = time.monotonic() - started
        self._write_render_log(class_name, cmd, stdout, stderr, code, elapsed)

        output = self._find_output(media_dir, class_name)
        if code == 0 and output is not None:
            logger.info("[render] %s ok  %.1fs", class_name, elapsed)
            return output, ""

        error = tail_lines(stderr) or tail_lines(stdout) or f"manim exited with code {code}"
        logger.warning("[render] %s failed (exit %s)  %.1fs", class_name, code, elapsed)
        return None, error

    def _write_render_log(
        self,
        class_name: str,
        cmd: list[str],
        stdout: str,
        stderr: str,
        code: int,
        elapsed: float,
    ) -> None:
        log_path = self.workspace.render_logs_dir / f"{class_name}.log"
        body = [
            f"$ {' '.join(cmd)}",
            f"exit code: {code}   elapsed: {elapsed:.1f}s",
            "",
            "--- stdout ---",
            stdout or "",
            "--- stderr ---",
            stderr or "",
        ]
        try:
            log_path.write_text("\n".join(body), encoding="utf-8")
        except OSError:  # pragma: no cover - logging must never break a render
            logger.debug("could not write render log %s", log_path)

    @staticmethod
    def _find_output(media_dir: Path, class_name: str) -> Path | None:
        if not media_dir.exists():
            return None
        matches = list(media_dir.rglob(f"{class_name}.mp4"))
        if not matches:
            return None
        final = [p for p in matches if "partial_movie_files" not in p.parts]
        candidates = final or matches
        return sorted(candidates, key=lambda path: len(path.parts))[0]

    # -- repair --------------------------------------------------------
    def _try_repair(self, class_name: str, error: str, expected: list[str]) -> str | None:
        """Ask the LLM for a fix. Returns the accepted code, or None if rejected."""
        script = self.workspace.animation_path.read_text(encoding="utf-8")
        prompt = build_fixer_prompt(script, class_name, error, self.env_info)
        response = self.client.call_llm(prompt)

        if self.cost is not None:
            self.cost.record_llm(
                "repair",
                self.settings.azure_deployment or "unknown",
                response.usage,
                response.seconds,
            )
            log_llm_call(logger, "repair", None, response, self.cost)

        candidate = strip_markdown_fences(response.text)

        problems = validate_manim_code(candidate, expected, self.env_info.latex_available)
        if problems:
            logger.warning(
                "repair for %s rejected (%d problem(s)): %s",
                class_name,
                len(problems),
                "; ".join(problems[:3]),
            )
            return None
        return candidate

    def _backup(self, attempt: int) -> Path:
        path = self.workspace.root / f"animation.attempt_{attempt}.py"
        shutil.copyfile(self.workspace.animation_path, path)
        return path

    # -- public --------------------------------------------------------
    def render_scene(self, scene: SceneMeta, index: int) -> SceneRender:
        expected = self.expected_names
        logger.info("[render %d/%d] %s", index, len(expected), scene.class_name)
        output, error = self._run_manim(scene.class_name)
        attempts = 0
        applied = 0

        while output is None and attempts < self.settings.max_render_retries:
            attempts += 1
            logger.info(
                "[render %d/%d] %s repair attempt %d/%d",
                index,
                len(expected),
                scene.class_name,
                attempts,
                self.settings.max_render_retries,
            )
            candidate = self._try_repair(scene.class_name, error, expected)
            if candidate is None:
                continue

            self._backup(attempts)
            self.workspace.animation_path.write_text(candidate, encoding="utf-8")
            build_render_script(self.workspace)
            applied += 1
            # Only the failing scene is re-rendered; finished scenes are kept.
            output, error = self._run_manim(scene.class_name)

        if output is None:
            raise RenderError(
                f"scene {scene.class_name} failed to render after "
                f"{attempts} repair attempt(s)",
                scene_class=scene.class_name,
                error_tail=error,
            )

        destination = self.workspace.scenes_dir / f"{index:02d}_{scene.class_name}.mp4"
        shutil.copyfile(output, destination)
        duration = probe_duration(destination)
        return SceneRender(
            index=index,
            class_name=scene.class_name,
            video_path=destination,
            duration=duration,
            repair_attempts=attempts,
            repairs_applied=applied,
        )


def render_scenes(
    result: GenerationResult,
    workspace: JobWorkspace,
    settings: Settings,
    env_info: EnvInfo,
    client: LLMClient | None = None,
    on_scene: Callable[[SceneRender], None] | None = None,
    cost: CostTracker | None = None,
) -> list[SceneRender]:
    """Render every scene in order; raises RenderError instead of skipping one."""
    scenes = scene_targets(result)
    install_helpers(workspace)
    build_render_script(workspace)

    renderer = SceneRenderer(
        workspace, settings, env_info, [meta.class_name for meta in scenes], client, cost
    )

    rendered: list[SceneRender] = []
    for index, scene in enumerate(scenes, start=1):
        scene_render = renderer.render_scene(scene, index)
        rendered.append(scene_render)
        if on_scene is not None:
            on_scene(scene_render)
    return rendered
