#!/usr/bin/env python3
"""Pebble CLI: --doctor for environment checks, otherwise run a pipeline stage."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pebble import __version__
from pebble.config import load_settings, voice_for_language
from pebble.cost import COST_LOG_PATH, read_cost_log, summarize_cost_log
from pebble.environment import detect
from pebble.errors import PebbleError
from pebble.logging_setup import setup_logging
from pebble.models import VideoRequest
from pebble.styles import get_style
from pebble.workspace import JobWorkspace

MIN_PYTHON = (3, 10)
DEEP_RENDER_TIMEOUT = 300


def _fmt(ver: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in ver)


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------


def _check_python() -> tuple[bool, str]:
    ok = sys.version_info >= MIN_PYTHON
    return ok, f"Python {_fmt(tuple(sys.version_info[:3]))} (need >= {_fmt(MIN_PYTHON)})"


def _check_env_names(settings) -> tuple[bool, str]:
    missing = settings.missing_required_names
    if missing:
        return False, "missing env var names: " + ", ".join(missing)
    return True, "all required env var names present (values not shown)"


def _check_manim(env) -> tuple[bool, str]:
    if not env.manim_available:
        return False, f"manim import failed: {env.manim_version}"
    return True, f"manim {env.manim_version}"


def _check_ffmpeg(env) -> tuple[bool, str]:
    return env.ffmpeg_available, f"ffmpeg {'found' if env.ffmpeg_available else 'not on PATH'}"


def _check_ffprobe(env) -> tuple[bool, str]:
    return (
        env.ffprobe_available,
        f"ffprobe {'found' if env.ffprobe_available else 'not on PATH'}",
    )


def _check_latex(env) -> tuple[bool, str]:
    if env.latex_available:
        return True, "latex + dvisvgm found"
    return False, "latex/dvisvgm not installed (optional; MathTex will be forbidden)"


def _check_speech_sdk() -> tuple[bool, str]:
    try:
        import azure.cognitiveservices.speech as speech  # noqa: F401

        return True, "azure-cognitiveservices-speech importable"
    except Exception as exc:  # pragma: no cover
        return False, f"azure speech sdk import failed: {exc}"


def _check_font(env) -> tuple[bool, str]:
    if not env.code_font:
        return False, "no usable monospace font found"
    return True, f"code font = {env.code_font}"


def _check_llm_ping(settings) -> tuple[bool, str]:
    try:
        from pebble.llm import LLMClient

        client = LLMClient(settings)
        reply = client.call_llm("Reply with exactly: pong")
        return True, f"LLM ping ok ({len(reply)} chars from deployment)"
    except Exception as exc:  # noqa: BLE001
        return False, f"LLM ping failed: {type(exc).__name__}: {exc}"


def _check_speech_synthesis(settings) -> tuple[bool, str]:
    """Deep check: synthesize one short phrase to a temp wav."""
    from pebble.tts import synthesize_scene

    try:
        voice = voice_for_language("English")
    except Exception as exc:  # noqa: BLE001
        return False, f"voice lookup failed: {exc}"

    try:
        with tempfile.TemporaryDirectory(prefix="pebble_tts_") as tmp:
            out = Path(tmp) / "doctor.wav"
            duration = synthesize_scene(
                "Pebble speech check, one two three.", out, voice, settings
            )
            size = out.stat().st_size
            if size <= 0 or duration <= 0:
                return False, "speech synthesis produced no audio"
            return True, f"synthesized {duration:.2f}s ({_human_size(size)}) with {voice}"
    except PebbleError as exc:
        return False, f"speech synthesis failed: {type(exc).__name__}: {exc}"
    except Exception as exc:  # noqa: BLE001
        return False, f"speech synthesis failed: {type(exc).__name__}: {exc}"


DEEP_SCENE = '''from manim import *


class DoctorScene(Scene):
    def construct(self):
        self.play(Write(Text("Pebble doctor")), run_time=0.6)
        self.wait(0.3)
'''


def _check_manim_render(settings) -> tuple[bool, str]:
    """Deep check: render a trivial one-line scene at -ql."""
    with tempfile.TemporaryDirectory(prefix="pebble_render_") as tmp:
        root = Path(tmp)
        script = root / "doctor_scene.py"
        script.write_text(DEEP_SCENE, encoding="utf-8")
        media_dir = root / "media"
        cmd = [
            sys.executable,
            "-m",
            "manim",
            "render",
            "-ql",
            "--disable_caching",
            "--media_dir",
            str(media_dir),
            "-o",
            "DoctorScene",
            str(script),
            "DoctorScene",
        ]
        try:
            completed = subprocess.run(
                cmd, capture_output=True, text=True, timeout=DEEP_RENDER_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return False, f"manim render timed out after {DEEP_RENDER_TIMEOUT}s"
        except OSError as exc:
            return False, f"manim could not start: {exc}"

        if completed.returncode != 0:
            tail = (completed.stderr or completed.stdout).strip().splitlines()[-6:]
            return False, "manim render failed: " + " | ".join(tail)

        matches = list(media_dir.rglob("DoctorScene.mp4"))
        if not matches:
            return False, "manim reported success but produced no mp4"
        return True, f"rendered {_human_size(matches[0].stat().st_size)} scene at -ql"


def run_doctor(deep: bool = False, verbose: bool = False, quiet: bool = False) -> int:
    # detect() imports manim, which installs its own root logger config; set up
    # Pebble's logging afterwards so manim's chatter cannot override it.
    settings = load_settings()
    env = detect()
    setup_logging(verbose=verbose, quiet=quiet)

    checks: list[tuple[str, bool, str, bool]] = [
        ("python", *_check_python(), True),
        ("env names", *_check_env_names(settings), True),
        ("manim", *_check_manim(env), True),
        ("ffmpeg", *_check_ffmpeg(env), True),
        ("ffprobe", *_check_ffprobe(env), True),
        ("latex", *_check_latex(env), False),
        ("speech sdk", *_check_speech_sdk(), True),
        ("code font", *_check_font(env), True),
        ("llm ping", *_check_llm_ping(settings), True),
    ]
    if deep:
        checks.append(("speech", *_check_speech_synthesis(settings), True))
        checks.append(("render", *_check_manim_render(settings), True))

    print(f"Pebble {__version__} doctor{' (deep)' if deep else ''}")
    print(f"settings: {settings}")
    failed_required = False
    for name, ok, detail, required in checks:
        if ok:
            status = "PASS"
        elif required:
            status = "FAIL"
            failed_required = True
        else:
            status = "WARN"
        print(f"  [{status}] {name:<10} {detail}")

    if failed_required:
        print("doctor: FAILED")
        return 1
    print("doctor: OK")
    return 0


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------


def _load_payload(payload_path: Path) -> VideoRequest:
    if not payload_path.exists():
        raise SystemExit(f"Payload not found: {payload_path}")
    return VideoRequest.model_validate(json.loads(payload_path.read_text(encoding="utf-8")))


def _print_request(request: VideoRequest, payload_path: Path, job_id: str) -> None:
    style_name, _ = get_style(request.preferences_or_default.explanation_style)
    print(f"payload          : {payload_path}")
    print(f"job id           : {job_id}")
    print(f"request_kind     : {request.request_kind}")
    print(f"solution_state   : {request.solution_state}")
    print(f"style            : {style_name}")
    print(
        f"language         : {request.programming_language} / "
        f"{request.preferences_or_default.language}"
    )
    print(f"fingerprint      : {request.request_fingerprint()[:16]}…")


def run_generate(
    payload_path: Path, job_id: str | None, verbose: bool = False, quiet: bool = False
) -> int:
    request = _load_payload(payload_path)
    settings = load_settings()
    env = detect()
    workspace = JobWorkspace(job_id)
    setup_logging(workspace=workspace, verbose=verbose, quiet=quiet)
    _print_request(request, payload_path, workspace.job_id)

    from pebble.generation import generate

    try:
        result = generate(request, workspace, settings, env)
    except PebbleError as exc:
        print(f"\ngeneration FAILED: {exc}", file=sys.stderr)
        for problem in getattr(exc, "problems", []):
            print(f"  - {problem}", file=sys.stderr)
        print(f"workspace: {workspace.root}", file=sys.stderr)
        return 1

    meta = result.meta
    print("\ngeneration OK")
    print(f"  scenes          : {len(meta.scenes)}")
    print(f"  solution_source : {meta.solution_source}")
    print(
        f"  validation      : performed={meta.validation.performed} "
        f"is_correct={meta.validation.is_correct}"
    )
    for issue in meta.validation.issues:
        print(f"    issue: {issue}")
    print(f"  complexity      : time={meta.complexity.time} space={meta.complexity.space}")
    print(f"  animation.py    : {workspace.animation_path}")
    print(f"  generation.json : {workspace.generation_path}")
    print(f"  llm traces      : {workspace.llm_dir}")
    return 0


def run_full(
    payload_path: Path,
    job_id: str | None,
    verbose: bool = False,
    quiet: bool = False,
) -> int:
    request = _load_payload(payload_path)
    setup_logging(verbose=verbose, quiet=quiet)
    _print_request(request, payload_path, job_id or "(auto)")

    from pebble.pipeline import run_pipeline

    started = time.perf_counter()

    def on_status(stage: str) -> None:
        print(f"[stage] {stage}", flush=True)

    try:
        result = run_pipeline(
            request,
            job_id=job_id,
            on_status=on_status,
            verbose=verbose,
            quiet=quiet,
        )
    except PebbleError as exc:
        print(f"\npipeline FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        for problem in getattr(exc, "problems", []):
            print(f"  - {problem}", file=sys.stderr)
        tail = getattr(exc, "error_tail", "")
        if tail:
            print("--- error tail ---", file=sys.stderr)
            print(tail, file=sys.stderr)
        hint = Path("workspace") / job_id if job_id else Path("workspace")
        print(f"workspace: {hint}", file=sys.stderr)
        return 1

    size = result.final_video.stat().st_size
    print("\npipeline OK")
    print(f"  final video     : {result.final_video}")
    print(f"  duration        : {result.duration_seconds:.1f}s")
    print(f"  size            : {_human_size(size)}")
    print(f"  scenes          : {result.scene_count}")
    print(f"  solution_source : {result.solution_source}")
    print(
        f"  validation      : performed={result.validation.performed} "
        f"is_correct={result.validation.is_correct}"
    )
    for issue in result.validation.issues:
        print(f"    issue: {issue}")
    print(
        f"  complexity      : time={result.complexity.time} space={result.complexity.space}"
    )
    print(f"  repair attempts : {result.repair_attempts} "
          f"(applied {result.repairs_applied})")
    print("  timings         :")
    for stage, seconds in result.timings.items():
        print(f"    {stage:<10} {seconds:>7.2f}s")
    print()
    print(result.cost_table)
    print()
    print(f"  workspace       : {result.workspace}")
    print(f"  wall clock      : {time.perf_counter() - started:.1f}s")
    return 0


def run_costs() -> int:
    entries = read_cost_log(COST_LOG_PATH)
    if not entries:
        print(f"no cost history yet ({COST_LOG_PATH})")
        return 0

    summary = summarize_cost_log(entries)
    print(f"cost history: {COST_LOG_PATH}")
    print(
        f"  {'date':<20}{'job':<24}{'kind':<19}{'style':<18}"
        f"{'video s':>9}{'USD':>10}"
    )
    for entry in entries:
        print(
            f"  {str(entry.get('date', ''))[:19]:<20}"
            f"{str(entry.get('job_id', ''))[:23]:<24}"
            f"{str(entry.get('kind', ''))[:18]:<19}"
            f"{str(entry.get('style', ''))[:17]:<18}"
            f"{float(entry.get('video_seconds') or 0):>9.1f}"
            f"{'$' + format(float(entry.get('total_usd') or 0), '.4f'):>10}"
        )
    print(
        f"  runs {summary['runs']}  total ${summary['total_usd']:.4f}  "
        f"average ${summary['average_usd']:.4f}  "
        f"average per video minute ${summary['cost_per_minute_usd']:.5f}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_local.py",
        description="Pebble: JSON request -> narrated Manim explainer video",
    )
    parser.add_argument("payload", nargs="?", help="path to the JSON payload")
    parser.add_argument("--doctor", action="store_true", help="run environment checks")
    parser.add_argument(
        "--deep",
        action="store_true",
        help="with --doctor: also test live speech synthesis and a real manim render",
    )
    parser.add_argument("--job-id", default=None, help="reuse a specific workspace job id")
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG lines on the console",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only stage banners, warnings and the final summary",
    )
    parser.add_argument(
        "--costs", action="store_true", help="summarise workspace/cost_log.jsonl"
    )
    parser.add_argument(
        "--stage",
        default="full",
        choices=["generate", "full"],
        help="pipeline stage to run (default: full)",
    )
    parser.add_argument("--version", action="version", version=f"Pebble {__version__}")
    args = parser.parse_args(argv)

    if args.costs:
        return run_costs()

    if args.doctor:
        return run_doctor(deep=args.deep, verbose=args.verbose, quiet=args.quiet)

    if not args.payload:
        parser.error("payload path is required (or use --doctor)")

    payload_path = Path(args.payload)
    if args.stage == "generate":
        return run_generate(payload_path, args.job_id, verbose=args.verbose, quiet=args.quiet)
    return run_full(payload_path, args.job_id, verbose=args.verbose, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
