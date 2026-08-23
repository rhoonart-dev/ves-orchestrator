"""L-P2 — 현지화 엔진 컷오버 스위치.

두 엔진이 같은 산출 규약을 지키므로 갈리는 것은 argv·cwd 뿐이다. 그래서 이 파일이
고정하는 것은 ① 스위치 해석 ② 두 argv 의 모양 — 둘 다 순수.

🛑 가장 중요한 단언: **모르는 값은 vlp(기본)로 떨어진다.** 컷오버 설정 오타가
검증 안 된 엔진을 켜면 안 된다.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ves.adapters.localize import (  # noqa: E402
    ENGINE_AIVIDEO, ENGINE_VLP, aivideo_localize_argv, pick_engine, scene_rerender_argv,
)


# ── 스위치 해석 ─────────────────────────────────────────────────────────
def test_default_is_vlp_when_unset():
    assert pick_engine(None) == ENGINE_VLP
    assert pick_engine("") == ENGINE_VLP
    assert pick_engine("   ") == ENGINE_VLP


def test_scalar_switch():
    assert pick_engine("ai-video") == ENGINE_AIVIDEO
    assert pick_engine("  ai-video  ") == ENGINE_AIVIDEO
    assert pick_engine("vlp") == ENGINE_VLP


def test_unknown_value_falls_back_to_default():
    """오타가 검증 안 된 엔진을 켜면 안 된다."""
    assert pick_engine("aivideo") == ENGINE_VLP        # 하이픈 빠짐
    assert pick_engine("AI-VIDEO") == ENGINE_VLP       # 대소문자
    assert pick_engine("on") == ENGINE_VLP


def test_per_channel_map():
    raw = '{"_default":"vlp","SHOTCONE":"ai-video"}'
    assert pick_engine(raw, "SHOTCONE") == ENGINE_AIVIDEO
    assert pick_engine(raw, "LOOPY") == ENGINE_VLP
    assert pick_engine(raw, None) == ENGINE_VLP


def test_map_without_default_falls_back():
    assert pick_engine('{"SHOTCONE":"ai-video"}', "OTHER") == ENGINE_VLP


def test_map_can_flip_everything():
    assert pick_engine('{"_default":"ai-video"}', "ANY") == ENGINE_AIVIDEO


def test_broken_json_falls_back_to_default():
    assert pick_engine('{"_default":', "SHOTCONE") == ENGINE_VLP


def test_map_with_unknown_engine_value_falls_back():
    assert pick_engine('{"SHOTCONE":"nonsense"}', "SHOTCONE") == ENGINE_VLP


# ── argv 두 벌 ──────────────────────────────────────────────────────────
def test_vlp_argv_unchanged():
    """구 경로는 한 글자도 안 바뀌어야 한다 — 되돌리기가 진짜 되돌리기여야 한다."""
    assert scene_rerender_argv("/ai/.venv/bin/python", "/eng/vlp", "/out/JOB") == \
        ["/ai/.venv/bin/python", "/eng/vlp/scripts/localize_run.py", "--job-dir", "/out/JOB"]


def test_vlp_argv_with_overrides():
    argv = scene_rerender_argv("/py", "/eng", "/job", "/job/localize_overrides.json")
    assert argv[-2:] == ["--overrides", "/job/localize_overrides.json"]


def test_aivideo_argv_uses_subcommand():
    assert aivideo_localize_argv("/ai/.venv/bin/python", "/out/JOB") == \
        ["/ai/.venv/bin/python", "-m", "app.cli", "localize",
         "--job-dir", "/out/JOB", "--locale", "ja"]


def test_aivideo_argv_locale_and_overrides():
    argv = aivideo_localize_argv("/py", "/job", "ja", "/job/localize_overrides.json")
    assert argv[argv.index("--locale") + 1] == "ja"
    assert argv[-2:] == ["--overrides", "/job/localize_overrides.json"]


def test_aivideo_argv_defaults_locale_when_blank():
    argv = aivideo_localize_argv("/py", "/job", "")
    assert argv[argv.index("--locale") + 1] == "ja"


def test_both_argvs_run_the_same_interpreter():
    """둘 다 ai-video venv 로 돈다 — 런타임 의존(google-genai·edge-tts)이 거기 있다."""
    py = "/opt/ves/engines/ai-video/.venv/bin/python"
    assert scene_rerender_argv(py, "/eng", "/job")[0] == py
    assert aivideo_localize_argv(py, "/job")[0] == py
