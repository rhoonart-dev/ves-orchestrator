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


# ── 플랫폼 표기 통과(2026-09-04, 가왕쇼 7화 '티빙' 누락 후속) ──

def test_v3_design_flags_pick_supported_keys_only():
    from ves.adapters.aivideo import V3_DESIGN_KEYS, v3_design_flags
    # 한 입 주막 실물 design(2026-09-04 DB 실측)에 v1 전용 키를 섞은 입력
    design = {"video_y": 440, "aspect_ratio": "13:9", "title_font": "여기어때 잘난체 고딕 TTF",
              "face_tracking": False, "platform_text": "티빙", "platform_align": "right",
              "transcribe_backend": "elevenlabs", "style_compose": True,
              "subtitles": False, "video_speed": 1.2, "_note": "x"}
    flags = v3_design_flags(design, "HANIPJUMAK")
    # v1 전용 키(transcribe_backend·style_compose·subtitles·video_speed)는 에러가 아니라 제외
    assert flags == ["--design-video-y", "440", "--design-aspect-ratio", "13:9",
                     "--design-title-font", "여기어때 잘난체 고딕 TTF",
                     "--no-reframe",
                     "--design-platform-text", "티빙",
                     "--design-platform-align", "right"]
    assert v3_design_flags({"face_tracking": True}, "c") == []      # 켜짐 = 플래그 없음
    assert v3_design_flags(None, "c") == [] and v3_design_flags({}, "c") == []
    for banned in ("transcribe_backend", "style_compose", "subtitles", "video_speed",
                   "pipeline_v3", "title_rotate"):
        assert banned not in V3_DESIGN_KEYS


def test_v3_argv_carries_platform_text_and_stays_identical_without_design():
    p = {"work_title": "가왕쇼", "episode": 7, "no_research": True,
         "outdir": "outputs", "channel_name": "HANIPJUMAK"}
    base_argv = build_argv_v3_pure("/py", p, "/s.mp4")
    assert build_argv_v3_pure("/py", p, "/s.mp4", None) == base_argv       # 회귀 0
    argv = build_argv_v3_pure("/py", p, "/s.mp4",
                              {"platform_text": "티빙", "title_size": 80,
                               "transcribe_backend": "elevenlabs"})
    assert argv[:len(base_argv)] == base_argv
    assert argv[len(base_argv):] == ["--design-platform-text", "티빙",
                                     "--design-title-size", "80"]
    assert "--transcribe-backend" not in " ".join(argv)


def test_v3_platform_flags_also_on_resume(monkeypatch, tmp_path):
    import ves.adapters.aivideo as a
    monkeypatch.setattr(a, "_channel_record",
                        lambda cfg, name: {"design": {"pipeline_v3": True,
                                                      "platform_text": "티빙"}})
    monkeypatch.setattr(a.cfgmod, "engine_py", lambda cfg, k: "/py")
    monkeypatch.setattr(a.cfgmod, "engine_dir", lambda cfg, k: str(tmp_path))
    monkeypatch.setattr(a.cfgmod, "source_cache_path", lambda cfg, sha: str(tmp_path / "s.mp4"))
    (tmp_path / "s.mp4").write_bytes(b"")
    (tmp_path / "outputs" / "r1").mkdir(parents=True)
    job = {"params": {"work_title": "가왕쇼", "channel_name": "c", "source_sha256": "x",
                      "resume_run_id": "r1", "from_step": "render"}}
    argv = a._build_argv_v3({}, job)
    assert "--design-platform-text" in argv and "--from-step" in argv


def test_band_offset_keys_go_to_v3_only():
    from ves.adapters.aivideo import V3_ONLY_DESIGN_KEYS, channel_design_flags, v3_design_flags
    design = {"video_y": 500, "subtitle_band_offset": 30, "tts_band_offset": 24}
    assert v3_design_flags(design, "c") == ["--design-video-y", "500",
                                            "--design-subtitle-band-offset", "30",
                                            "--design-tts-band-offset", "24"]
    # v1 잡(job_design_flags 경로)에는 실리지 않는다 — v1 argparse 즉사 방지, 에러도 아님
    assert channel_design_flags(design, "c") == ["--design-video-y", "500"]
    assert V3_ONLY_DESIGN_KEYS == {"subtitle_band_offset", "tts_band_offset"}
