"""V3(M5) 채널 전환 배선 — aivideo 어댑터 v3 분기 회귀 가드.

계약(orders/v3-m5-channel-switch.md §A): 게이트 둘 다(ops aivideo_v3 ∧ 채널
design.pipeline_v3) 켜져야 v3. 꺼져 있으면 기존 경로 **바이트 동일**. v3 미지원
플래그는 argv 에 싣지 않는다. resume 은 checkpoint_<step> → v3 --from-step 어휘.
"""
from __future__ import annotations

import pytest

from ves.adapters import base
from ves.adapters.aivideo import (
    STEP_ORDER_V3,
    build_argv_pure,
    build_argv_v3_pure,
    pick_resume_step,
    pick_resume_step_v3,
    v3_enabled,
)


def test_v3_argv_minimal_and_no_v1_flags():
    argv = build_argv_v3_pure("/py", {"work_title": "포핸즈", "episode": 1,
                                      "no_research": True, "outdir": "outputs"},
                              "/cache/src.mp4")
    assert argv[:4] == ["/py", "-u", "-m", "app.v3"]
    assert "--video" in argv and "--work-title" in argv
    assert "--skip-research" in argv and "--episode" in argv
    # v1 전용 플래그가 새면 v3 argparse 즉사 — 절대 실리면 안 된다
    joined = " ".join(argv)
    for banned in ("--max-shorts", "--design-", "--topic", "--no-subtitles",
                   "create_shorts"):
        assert banned not in joined


def test_v3_argv_requires_local_source():
    with pytest.raises(base.PermanentError):
        build_argv_v3_pure("/py", {"work_title": "x", "source_url": "https://y"},
                           None)


def test_gate_requires_both_switches(monkeypatch):
    import ves.adapters.aivideo as a
    monkeypatch.setattr(a, "_channel_record",
                        lambda cfg, name: {"design": {"pipeline_v3": True}})
    assert v3_enabled({}, {"aivideo_v3_allowed": True,
                           "channel_name": "c"}) is True
    assert v3_enabled({}, {"aivideo_v3_allowed": False,
                           "channel_name": "c"}) is False        # ops off
    monkeypatch.setattr(a, "_channel_record", lambda cfg, name: {"design": {}})
    assert v3_enabled({}, {"aivideo_v3_allowed": True,
                           "channel_name": "c"}) is False        # 채널 off
    assert v3_enabled({}, {}) is False                           # 기본 완전 off


def test_gate_design_override_wins(monkeypatch):
    import ves.adapters.aivideo as a
    monkeypatch.setattr(a, "_channel_record", lambda cfg, name: {"design": {}})
    assert v3_enabled({}, {"aivideo_v3_allowed": True, "channel_name": "c",
                           "design_override": {"pipeline_v3": True}}) is True


def test_v1_path_byte_identical_when_gate_off():
    # 게이트 off 잡의 argv 는 분기 신설 전과 완전히 같아야 한다 — v1 순수 빌더 직접 대조
    p = {"work_title": "가왕쇼", "max_shorts": 1, "no_research": True,
         "outdir": "outputs"}
    assert build_argv_pure("/py", p, "/s.mp4")[:5] == [
        "/py", "-u", "-m", "app.cli", "create_shorts"]


def test_resume_step_v3_mapping_and_order():
    files = ["a/checkpoint_research.json", "a/checkpoint_probe.json",
             "a/checkpoint_grid_words.json", "a/checkpoint_chunk_split.json",
             "a/checkpoint_chunk_analyze.json", "a/checkpoint_story.json"]
    assert pick_resume_step_v3(files) == "story"                 # 마지막 완료 스텝
    assert pick_resume_step_v3(["a/checkpoint_grid_words.json"]) == "grid"
    assert pick_resume_step_v3(["a/checkpoint_research.json"]) is None
    assert pick_resume_step_v3([]) is None
    # v1 선택기는 v3 체크포인트명을 모른 채 그대로 — 서로 오염 없음
    assert pick_resume_step(["a/checkpoint_grid_words.json"]) is None


def test_step_order_v3_matches_engine_vocabulary():
    # 엔진 V3_STEPS(ai-video app/v3/pipeline.py)와 1:1 — 어휘가 갈리면 --from-step 즉사
    assert STEP_ORDER_V3 == ["research", "probe", "proxy", "grid", "seq_analyze",
                             "chunk_split", "chunk_analyze", "story", "resources",
                             "draft_render", "style", "render", "validate"]
