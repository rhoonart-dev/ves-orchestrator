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
