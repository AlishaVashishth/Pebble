"""Tests for allowed API auto-generation, natural Viz methods, hard API validation,
early break on identical repair errors, and parallel scene rendering.
"""

from __future__ import annotations

import ast
from unittest.mock import MagicMock, patch

import pytest

from pebble.config import Settings
from pebble.kit_api import get_allowed_api_reference, get_allowed_structure_methods
from pebble.models import GenerationMeta, GenerationResult, SceneMeta, VideoRequest
from pebble.renderer import RenderAttempt, SceneRender, SceneRenderer, render_scenes
from pebble.validators import validate_generation_split


def test_allowed_structure_methods_contains_expected():
    methods = get_allowed_structure_methods()
    assert "StackViz" in methods
    assert "push" in methods["StackViz"]
    assert "pop" in methods["StackViz"]
    assert "append" in methods["StackViz"]

    assert "ArrayViz" in methods
    assert "append" in methods["ArrayViz"]
    assert "pop" in methods["ArrayViz"]
    assert "swap" in methods["ArrayViz"]
    assert "set_state" in methods["ArrayViz"]

    assert "QueueViz" in methods
    assert "enqueue" in methods["QueueViz"]
    assert "dequeue" in methods["QueueViz"]
    assert "push" in methods["QueueViz"]
    assert "pop" in methods["QueueViz"]
    assert "append" in methods["QueueViz"]
    assert "popleft" in methods["QueueViz"]


def test_allowed_api_reference_contains_rules_and_methods():
    ref = get_allowed_api_reference()
    assert "CRITICAL RULE" in ref
    assert "call ONLY these methods" in ref
    assert "StackViz" in ref
    assert ".push(" in ref
    assert "ArrayViz" in ref
    assert ".append(" in ref
    assert "QueueViz" in ref
    assert ".enqueue(" in ref


def test_invented_method_is_hard_error(env_info):
    code = (
        "from manim import *\n"
        "from pebble_kit import *\n\n"
        "class Scene1_Intro(Scene):\n"
        "    def construct(self):\n"
        "        arr = ArrayViz([1, 2, 3])\n"
        "        self.play(arr.foobar())\n"
        "        finish_scene(self)\n"
    )
    result = GenerationResult(
        manim_code=code,
        solution_code="def solve(): pass",
        meta=GenerationMeta(
            problem_summary="test",
            scenes=[
                SceneMeta(
                    class_name="Scene1_Intro",
                    title="Intro",
                    narration="test narration",
                )
            ],
        ),
    )
    request = VideoRequest.model_validate(
        {"question": {"id": 1, "slug": "test", "title": "Test"}}
    )
    problems = validate_generation_split(result, request, env_info)
    assert any("'foobar' is not a method of ArrayViz" in p for p in problems.hard)


def test_natural_methods_pass_validation(env_info):
    code = (
        "from manim import *\n"
        "from pebble_kit import *\n\n"
        "class Scene1_Intro(Scene):\n"
        "    def construct(self):\n"
        "        self.show_title('Stack & Array')\n"
        "        s = StackViz('stack', [1, 2])\n"
        "        self.play(s.push(3))\n"
        "        arr = ArrayViz([1, 2])\n"
        "        self.play(arr.append(3))\n"
        "        q = QueueViz('queue', [1, 2])\n"
        "        self.play(q.push(3))\n"
        "        finish_scene(self)\n"
    )
    result = GenerationResult(
        manim_code=code,
        solution_code="def solve(): pass",
        meta=GenerationMeta(
            problem_summary="test",
            scenes=[
                SceneMeta(
                    class_name="Scene1_Intro",
                    title="Intro",
                    narration="test narration",
                )
            ],
        ),
    )
    request = VideoRequest.model_validate(
        {"question": {"id": 1, "slug": "test", "title": "Test"}}
    )
    problems = validate_generation_split(result, request, env_info)
    method_problems = [p for p in problems.all if "is not a method of" in p]
    assert method_problems == []


def test_renderer_stops_repair_on_identical_errors(tmp_path, env_info):
    workspace = MagicMock()
    workspace.root = tmp_path
    workspace.animation_path = tmp_path / "animation.py"
    workspace.animation_path.write_text("class Scene1_Intro(Scene):\n    pass\n")
    workspace.scenes_dir = tmp_path / "scenes"
    workspace.scenes_dir.mkdir()

    settings = Settings(max_render_retries=3)
    renderer = SceneRenderer(workspace, settings, env_info, ["Scene1_Intro"])

    # Simulate _run_manim returning the SAME error each time
    call_count = 0
    def mock_run_manim(class_name, strict=None):
        nonlocal call_count
        call_count += 1
        # When called as fallback, succeed
        if renderer._use_fallback.called:
            out_file = tmp_path / "fallback.mp4"
            out_file.write_bytes(b"video")
            return RenderAttempt(out_file, "", [], False)
        return RenderAttempt(None, "AttributeError: 'StackViz' has no attribute 'fake'", [], False)

    renderer._run_manim = mock_run_manim
    renderer._use_fallback = MagicMock()
    renderer._try_repair = MagicMock(return_value="candidate code")
    renderer._backup = MagicMock()

    scene = SceneMeta(class_name="Scene1_Intro", title="Intro", narration="test")
    with patch("pebble.renderer.build_render_script"), patch(
        "pebble.renderer.probe_duration", return_value=5.0
    ):
        render_res = renderer.render_scene(scene, 1)

    # Should break out after attempt 1 sees attempt 0 error again (or attempt 2), avoiding all 3 retries
    assert renderer._try_repair.call_count <= 1
    assert renderer._use_fallback.called
    assert render_res.used_fallback


def test_render_scenes_parallel_preserves_order(tmp_path, env_info):
    workspace = MagicMock()
    workspace.root = tmp_path
    workspace.scenes_dir = tmp_path / "scenes"
    workspace.scenes_dir.mkdir()

    settings = Settings(render_workers=3)
    scene1 = SceneMeta(class_name="Scene1_Intro", title="1", narration="n1")
    scene2 = SceneMeta(class_name="Scene2_Algo", title="2", narration="n2")
    scene3 = SceneMeta(class_name="Scene3_Outro", title="3", narration="n3")

    result = GenerationResult(
        manim_code="code",
        solution_code="sol",
        meta=GenerationMeta(
            problem_summary="p",
            scenes=[scene1, scene2, scene3],
        ),
    )

    with patch("pebble.renderer.install_runtime"), patch(
        "pebble.renderer.build_render_script"
    ), patch.object(
        SceneRenderer, "render_scene"
    ) as mock_render_scene:
        def fake_render(scene, index):
            dummy_mp4 = tmp_path / f"{index}_{scene.class_name}.mp4"
            dummy_mp4.write_bytes(b"data")
            return SceneRender(
                index=index,
                class_name=scene.class_name,
                video_path=dummy_mp4,
                duration=3.0,
            )

        mock_render_scene.side_effect = fake_render
        rendered = render_scenes(result, workspace, settings, env_info)

    assert len(rendered) == 3
    assert [r.index for r in rendered] == [1, 2, 3]
    assert [r.class_name for r in rendered] == ["Scene1_Intro", "Scene2_Algo", "Scene3_Outro"]

