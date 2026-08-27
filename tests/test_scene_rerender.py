"""scene_rerender 모드(2026-08-13) — 순수 로직: 체인 구성·노드 핀·argv 계약."""
from ves.adapters import aivideo, localize
from ves.scheduler import planner


def _wo(pipeline="shorts_jp_localized"):
    return {"work_title": "혜미리예채파", "episode": 1, "channel_slug": "SHOTCONE",
            "channel_name": "ショトコン", "pipeline": pipeline}


def test_jp_chain_localize_is_scene_rerender_on_generate_cap():
    chain = planner.job_chain(_wo())
    kinds = [c[0] for c in chain]
    assert kinds[-1] == "localize"
    kind, params, caps, lease = chain[-1]
    # 생성 노드 재렌더: mm-06 전용 "localize" 캡이 아니라 generate 캡(+완료 시 node 핀)
    assert params["mode"] == "scene_rerender"
    assert caps == ["generate"]


def test_kr_chain_has_no_localize():
    assert "localize" not in [c[0] for c in planner.job_chain(_wo(pipeline="shorts_kr"))]


def test_localize_pinned_to_generate_node():
    # generate 완료 시 executor._pin_dependents 가 이 목록을 보고 node:* 캡을 박는다
    assert "localize" in aivideo.PIN_DEPENDENT_KINDS


def test_scene_rerender_argv_contract():
    argv = localize.scene_rerender_argv("/py", "/eng", "/jobs/run1")
    assert argv == ["/py", "/eng/scripts/localize_run.py", "--job-dir", "/jobs/run1"]


def test_level_b_argv_unchanged():
    # zanmang 등 완성-mp4 경로(level B)는 그대로 — mode 없는 잡은 기존 argv
    argv = localize.localize_argv("/py", "/v.mp4", "rid", {"level": "B"})
    assert argv[:3] == ["/py", "-m", "src.process_video"]


# ── 잔망루피 롱폼 내레이션 끔 (2026-08-27) ─────────────────────────────
def test_narration_switch_maps_to_no_narration_flag():
    """channel design `narration:false` → --no-narration. ⚠ 새 CLI 플래그라 엔진 전
    노드 배포 뒤에만 채널 design 에 싣는다(style_compose 와 같은 롤아웃)."""
    assert aivideo.CHANNEL_DESIGN_SWITCHES["narration"] == ("--no-narration", False)
    flags = aivideo.channel_design_flags({"narration": False, "style_compose": True}, "LOOPY")
    assert "--no-narration" in flags and "--style-compose" in flags
    # true(기본 동작)면 플래그가 안 붙는다 — 종전 채널 회귀 0
    assert "--no-narration" not in aivideo.channel_design_flags({"narration": True}, "SHOTCONE")
