"""Narration to speech via Azure Speech, one synthesizer per scene."""

from __future__ import annotations

import io
import logging
import re
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pebble.config import Settings, voice_for_language
from pebble.cost import CostTracker
from pebble.errors import ConfigError, TTSError
from pebble.models import GenerationResult
from pebble.mux import probe_duration
from pebble.templates.pebble_kit import split_sentences
from pebble.workspace import JobWorkspace

logger = logging.getLogger(__name__)

MAX_TRANSIENT_RETRIES = 2

# Gap between two sentences inside one scene WAV. It is the pause the narration
# would have had anyway, and it makes each sentence's start measurable.
PER_SENTENCE_GAP = 0.25

_EMPHASIS_RE = re.compile(r"(?<![\w])_([^_\n]+)_(?![\w])")
_SPACE_RE = re.compile(r"\s+")

_PERMANENT_MARKERS = (
    "401",
    "403",
    "authentication",
    "unauthorized",
    "forbidden",
    "invalid subscription",
    "quota",
)


@dataclass(frozen=True)
class SceneAudio:
    index: int
    class_name: str
    audio_path: Path
    duration: float
    text: str
    # Optional per-sentence timing: [{"text", "start", "end"}]. Additive, so
    # workspaces and old callers keep working unchanged.
    sentences: list[dict] = field(default_factory=list)


def sanitize_narration(text: str) -> str:
    """Strip markdown so it is not read aloud, and collapse whitespace."""
    cleaned = (text or "").replace("`", "")
    cleaned = cleaned.replace("**", "").replace("*", "")
    cleaned = cleaned.replace("#", "")
    cleaned = _EMPHASIS_RE.sub(r"\1", cleaned)
    cleaned = _SPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def _speech_config(settings: Settings, voice: str):
    """Build an Azure SpeechConfig. Imported lazily so tests need no SDK call."""
    import azure.cognitiveservices.speech as speechsdk

    if not settings.azure_speech_key:
        raise ConfigError("AZURE_SPEECH_KEY is not configured")
    if not settings.azure_speech_region:
        raise ConfigError("AZURE_SPEECH_REGION is not configured")

    config = speechsdk.SpeechConfig(
        subscription=settings.azure_speech_key, region=settings.azure_speech_region
    )
    config.speech_synthesis_voice_name = voice
    return config


def _synth_audio(text: str, voice: str, settings: Settings) -> bytes:
    """Synthesize `text` and return WAV bytes. Isolated for easy mocking."""
    import azure.cognitiveservices.speech as speechsdk

    speech_config = _speech_config(settings, voice)
    # audio_config=None returns the audio in memory instead of playing it.
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
    result = synthesizer.speak_text_async(text).get()

    if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
        return bytes(result.audio_data)

    if result.reason == speechsdk.ResultReason.Canceled:
        raise TTSError(f"Azure Speech canceled the synthesis: {_cancellation_text(result)}")

    raise TTSError(f"Azure Speech returned an unexpected result: {result.reason}")


def _cancellation_text(result) -> str:
    """Explain a canceled result without depending on one SDK's helper name."""
    details = None
    try:
        import azure.cognitiveservices.speech as speechsdk

        factory = getattr(speechsdk.SpeechSynthesisCancellationDetails, "from_result", None)
        if factory is not None:
            details = factory(result)
        else:
            details = speechsdk.SpeechSynthesisCancellationDetails(result)
    except Exception:  # noqa: BLE001 - diagnostics must never mask the failure
        details = getattr(result, "cancellation_details", None)

    reason = getattr(details, "reason", None)
    code = getattr(details, "error_code", None)
    message = getattr(details, "error_details", "") or "no details"
    return f"reason={reason} error_code={code}: {message}"


def _is_permanent(error: str) -> bool:
    lowered = (error or "").lower()
    return any(marker in lowered for marker in _PERMANENT_MARKERS)


def _synthesize_with_retries(text: str, voice: str, settings: Settings) -> bytes:
    last_error = ""
    for attempt in range(MAX_TRANSIENT_RETRIES + 1):
        try:
            return _synth_audio(text, voice, settings)
        except ConfigError:
            raise
        except TTSError as exc:
            last_error = str(exc)
            if _is_permanent(last_error) or "canceled the synthesis" in last_error:
                # A cancellation is the service's verdict, not a flaky call: retrying
                # it only burns time (and has crashed the native SDK).
                raise
            if attempt < MAX_TRANSIENT_RETRIES:
                logger.warning(
                    "speech synthesis failed (attempt %d/%d), retrying: %s",
                    attempt + 1,
                    MAX_TRANSIENT_RETRIES + 1,
                    last_error,
                )
        except Exception as exc:  # noqa: BLE001 - network/SDK errors are transient here
            last_error = f"{type(exc).__name__}: {exc}"
            if _is_permanent(last_error):
                raise TTSError(last_error) from exc
            if attempt < MAX_TRANSIENT_RETRIES:
                logger.warning(
                    "speech synthesis error (attempt %d/%d), retrying: %s",
                    attempt + 1,
                    MAX_TRANSIENT_RETRIES + 1,
                    last_error,
                )
    raise TTSError(f"speech synthesis failed after retries: {last_error}")


def _write_audio(out_path: Path, audio: bytes) -> float:
    if not audio:
        raise TTSError(f"Azure Speech returned no audio for {out_path.stem}")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    return probe_duration(out_path)


def estimate_sentence_timings(
    sentences: list[str], total: float, gap: float = PER_SENTENCE_GAP
) -> list[dict]:
    """Spread `total` seconds over sentences: characters plus a pause per end."""
    if not sentences:
        return []
    total = max(0.0, float(total))
    weights = [max(1, len(sentence)) + 12 for sentence in sentences]
    available = max(0.0, total - gap * (len(sentences) - 1))
    scale = available / sum(weights)
    spans: list[dict] = []
    clock = 0.0
    for position, (sentence, weight) in enumerate(zip(sentences, weights)):
        start = clock
        clock += weight * scale
        spans.append(
            {
                "text": sentence,
                "start": round(start, 3),
                "end": round(clock, 3),
            }
        )
        if position < len(sentences) - 1:
            clock += gap
    return spans


def _wav_parts(data: bytes) -> tuple[int, int, int, bytes]:
    """(channels, sample width, frame rate, raw frames) of a WAV blob."""
    with wave.open(io.BytesIO(data), "rb") as handle:
        return (
            handle.getnchannels(),
            handle.getsampwidth(),
            handle.getframerate(),
            handle.readframes(handle.getnframes()),
        )


def join_wavs(
    chunks: list[bytes], gap: float = PER_SENTENCE_GAP
) -> tuple[bytes, list[tuple[float, float]]]:
    """Join WAV blobs with `gap` seconds of silence; return bytes and spans."""
    parts = [_wav_parts(chunk) for chunk in chunks]
    channels, width, rate = parts[0][0], parts[0][1], parts[0][2]
    for other in parts[1:]:
        if other[:3] != (channels, width, rate):
            raise TTSError("per-sentence audio arrived in mixed formats")
    frame_bytes = max(1, width * channels)
    silence = b"\x00" * (int(gap * rate) * frame_bytes)
    frames = bytearray()
    spans: list[tuple[float, float]] = []
    clock = 0.0
    for position, part in enumerate(parts):
        if position:
            frames += silence
            clock += gap
        payload = part[3]
        start = clock
        clock += len(payload) / float(frame_bytes * rate)
        frames += payload
        spans.append((start, clock))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return buffer.getvalue(), spans


def _single_call(
    text: str, out_path: Path, voice: str, settings: Settings
) -> tuple[float, list[dict]]:
    """Old behaviour: one call per scene, sentence starts estimated by length."""
    audio = _synthesize_with_retries(text, voice, settings)
    duration = _write_audio(out_path, audio)
    return duration, estimate_sentence_timings(split_sentences(text), duration)


def synthesize_scene_sentences(
    narration: str, out_path: Path, voice: str, settings: Settings
) -> tuple[float, list[dict]]:
    """Write one scene's narration (sentence by sentence) and return its timing.

    Each sentence is synthesized with the same voice and settings and the pieces
    are joined with a short silence into the SAME WAV file as before, so muxing
    and stitching are untouched. Any failure (rate limit, SDK error, mixed audio
    formats) falls back to the single call and proportional estimates: a job is
    never lost because of caption timing.
    """
    text = sanitize_narration(narration)
    if not text:
        raise TTSError(f"narration for {out_path.stem} is empty after sanitizing")

    sentences = split_sentences(text)
    if len(sentences) < 2:
        return _single_call(text, out_path, voice, settings)

    try:
        chunks = [
            _synthesize_with_retries(sentence, voice, settings)
            for sentence in sentences
        ]
        combined, spans = join_wavs(chunks, PER_SENTENCE_GAP)
    except Exception as exc:  # noqa: BLE001 - timing must never fail the job
        logger.warning(
            "%s: per-sentence synthesis failed (%s); falling back to one call",
            out_path.stem,
            exc,
        )
        return _single_call(text, out_path, voice, settings)

    duration = _write_audio(out_path, combined)
    timings = [
        {"text": sentence, "start": round(start, 3), "end": round(end, 3)}
        for sentence, (start, end) in zip(sentences, spans)
    ]
    return duration, timings


def synthesize_scene(
    narration: str, out_path: Path, voice: str, settings: Settings
) -> float:
    """Write one scene's narration to `out_path` and return its duration."""
    text = sanitize_narration(narration)
    if not text:
        raise TTSError(f"narration for {out_path.stem} is empty after sanitizing")

    audio = _synthesize_with_retries(text, voice, settings)
    return _write_audio(out_path, audio)


def narrate_scenes(
    result: GenerationResult,
    workspace: JobWorkspace,
    settings: Settings,
    language: str,
    on_scene: Callable[[SceneAudio], None] | None = None,
    cost: CostTracker | None = None,
) -> list[SceneAudio]:
    """Synthesize every scene's narration in order."""
    voice = voice_for_language(language)
    total = len(result.scenes)
    logger.info("narrating %d scene(s) with voice %s", total, voice)

    audio: list[SceneAudio] = []
    for index, scene in enumerate(result.scenes, start=1):
        out_path = workspace.audio_dir / f"{index:02d}_{scene.class_name}.wav"
        started = time.monotonic()
        duration, sentences = synthesize_scene_sentences(
            scene.narration, out_path, voice, settings
        )
        text = sanitize_narration(scene.narration)
        item = SceneAudio(
            index=index,
            class_name=scene.class_name,
            audio_path=out_path,
            duration=duration,
            text=text,
            sentences=sentences,
        )
        audio.append(item)
        if cost is not None:
            cost.record_tts(scene.class_name, len(text), voice)
        logger.info(
            "[narrate %d/%d] %s  %d chars -> %.2fs audio  %.1fs",
            index,
            total,
            scene.class_name,
            len(text),
            duration,
            time.monotonic() - started,
        )
        if on_scene is not None:
            on_scene(item)
    return audio
