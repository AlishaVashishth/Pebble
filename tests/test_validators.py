"""Validators: structural, safety and consistency checks."""

from __future__ import annotations

import json

from pebble.models import VideoRequest
from pebble.parsing import parse_response
from pebble.validators import validate_generation
from tests.conftest import VALID_MANIM, VALID_META, make_response


def _problems(response: str, request: VideoRequest, env_info) -> list[str]:
    return validate_generation(parse_response(response), request, env_info)


def _meta(**changes):
    meta = json.loads(json.dumps(VALID_META))
    meta.update(changes)
    return meta


def test_valid_two_scene_response_is_accepted(env_info, verified_request):
    assert _problems(make_response(), verified_request, env_info) == []


def test_wrong_numbering_is_rejected(env_info, verified_request):
    bad = VALID_MANIM.replace("class Scene2_Trace", "class Scene3_Trace").replace(
        "Scene2_Trace", "Scene9_Trace"
    )
    response = make_response(manim_code=bad)
    problems = _problems(response, verified_request, env_info)
    assert any("numbering" in p for p in problems)


def test_scene_count_mismatch_is_rejected(env_info, verified_request):
    meta = _meta(scenes=VALID_META["scenes"][:1])
    problems = _problems(make_response(meta=meta), verified_request, env_info)
    assert any("scene count mismatch" in p for p in problems)


def test_class_name_mismatch_is_rejected(env_info, verified_request):
    meta = _meta(
        scenes=[
            {"scene_id": 1, "class_name": "Scene1_Wrong", "title": "a", "narration": "n"},
            {"scene_id": 2, "class_name": "Scene2_Trace", "title": "b", "narration": "n"},
        ]
    )
    problems = _problems(make_response(meta=meta), verified_request, env_info)
    assert any("does not match" in p for p in problems)


def test_empty_narration_is_rejected(env_info, verified_request):
    meta = _meta(
        scenes=[
            {"scene_id": 1, "class_name": "Scene1_Intro", "title": "a", "narration": "   "},
            {"scene_id": 2, "class_name": "Scene2_Trace", "title": "b", "narration": "n"},
        ]
    )
    problems = _problems(make_response(meta=meta), verified_request, env_info)
    assert any("narration is empty" in p for p in problems)


def test_forbidden_import_is_rejected(env_info, verified_request):
    bad = VALID_MANIM + "\nimport os\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("import of 'os' is not allowed" in p for p in problems)


def test_subprocess_import_is_rejected(env_info, verified_request):
    bad = VALID_MANIM + "\nimport subprocess as sp\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("not allowed" in p for p in problems)


def test_dangerous_calls_are_rejected(env_info, verified_request):
    for snippet in ("eval('1+1')", "exec('x=1')", "open('f.txt')", "input()", "getattr(x, 'y')"):
        bad = VALID_MANIM + f"\ndef _bad():\n    {snippet}\n"
        problems = _problems(make_response(manim_code=bad), verified_request, env_info)
        assert problems, f"expected a problem for {snippet}"


def test_dunder_attribute_access_is_rejected(env_info, verified_request):
    bad = VALID_MANIM + "\ndef _bad(obj):\n    return obj.__class__\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("dunder" in p for p in problems)


def test_code_class_is_rejected(env_info, verified_request):
    bad = VALID_MANIM + "\ndef _bad():\n    return Code('main.py')\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("Code class" in p for p in problems)


def test_math_tex_rejected_without_latex(env_info, verified_request):
    bad = VALID_MANIM + "\ndef _bad():\n    return MathTex(r'x^2')\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("requires LaTeX" in p for p in problems)


def test_math_tex_allowed_when_latex_available(latex_env_info, verified_request):
    bad = VALID_MANIM + "\ndef _bad():\n    return MathTex(r'x^2')\n"
    problems = _problems(make_response(manim_code=bad), verified_request, latex_env_info)
    assert problems == []


def test_missing_manim_star_import_is_rejected(env_info, verified_request):
    bad = VALID_MANIM.replace("from manim import *", "import manim")
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("from manim import *" in p for p in problems)


def test_syntax_error_is_reported(env_info, verified_request):
    problems = _problems(
        make_response(manim_code="from manim import *\ndef broken(:\n"), verified_request, env_info
    )
    assert any("not valid Python" in p for p in problems)


def test_missing_meta_fields_are_reported(env_info, verified_request):
    meta = _meta()
    del meta["problem_summary"]
    problems = _problems(make_response(meta=meta), verified_request, env_info)
    assert any("problem_summary" in p for p in problems)


def test_solution_source_must_be_known(env_info, verified_request):
    problems = _problems(
        make_response(meta=_meta(solution_source="guessed")), verified_request, env_info
    )
    assert any("solution_source" in p for p in problems)


def test_verified_state_requires_provided_source(env_info, verified_request):
    problems = _problems(
        make_response(meta=_meta(solution_source="generated")), verified_request, env_info
    )
    assert any("verified" in p for p in problems)


def test_missing_state_requires_generated_source(env_info):
    from tests.conftest import load_sample

    request = load_sample("dijkstra_algorithm.json")
    meta = _meta(solution_source="provided")
    problems = _problems(make_response(meta=meta), request, env_info)
    assert any("missing" in p for p in problems)


def test_unverified_state_requires_performed_validation(env_info):
    from tests.conftest import load_sample

    request = load_sample("buggy_two_sum.json")
    meta = _meta(solution_source="provided", validation={"performed": False})
    problems = _problems(make_response(meta=meta), request, env_info)
    assert any("validation.performed" in p for p in problems)


def test_unverified_state_accepts_corrected_source(env_info):
    from tests.conftest import load_sample

    request = load_sample("buggy_two_sum.json")
    meta = _meta(
        solution_source="corrected",
        validation={"performed": True, "is_correct": False, "issues": ["off-by-one"]},
    )
    assert _problems(make_response(meta=meta), request, env_info) == []


def test_empty_solution_code_is_rejected(env_info, verified_request):
    problems = _problems(
        make_response(solution_code="   \n"), verified_request, env_info
    )
    assert any("solution_code is empty" in p for p in problems)


# ---------------------------------------------------------------------------
# finish_scene: the pipeline owns every scene ending
# ---------------------------------------------------------------------------


def test_missing_final_finish_scene_is_rejected(env_info, verified_request):
    bad = VALID_MANIM.replace("        finish_scene(self)\n", "", 1)
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("must be exactly finish_scene(self)" in p for p in problems)


def test_redefining_finish_scene_is_rejected(env_info, verified_request):
    bad = VALID_MANIM + "\n\ndef finish_scene(scene):\n    scene.wait(1)\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("do not define it" in p for p in problems)


def test_importing_finish_scene_is_rejected(env_info, verified_request):
    bad = VALID_MANIM + "\nfrom pebble_helpers import finish_scene\n"
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("do not import it" in p for p in problems)


def test_while_loop_around_wait_is_rejected(env_info, verified_request):
    bad = VALID_MANIM.replace(
        "        self.wait(1.2)\n        finish_scene(self)",
        "        remaining = 1.0\n"
        "        while remaining > 0:\n"
        "            self.wait(0.5)\n"
        "            remaining -= 0.5\n"
        "        finish_scene(self)",
    )
    assert bad != VALID_MANIM
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("while loop around self.wait" in p for p in problems)


def test_repair_output_without_finish_scene_is_rejected(env_info):
    from pebble.validators import validate_manim_code

    broken = VALID_MANIM.replace("        finish_scene(self)\n", "", 1)
    problems = validate_manim_code(
        broken, ["Scene1_Intro", "Scene2_Trace"], env_info.latex_available
    )
    assert any("finish_scene(self)" in p for p in problems)

    assert (
        validate_manim_code(
            VALID_MANIM, ["Scene1_Intro", "Scene2_Trace"], env_info.latex_available
        )
        == []
    )


def test_missing_background_is_rejected(env_info, verified_request):
    bad = VALID_MANIM.replace('config.background_color = "#0F172A"\n', "")
    problems = _problems(make_response(manim_code=bad), verified_request, env_info)
    assert any("config.background_color" in p for p in problems)
