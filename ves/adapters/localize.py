#!/usr/bin/env python3
"""localize 어댑터(네이티브) — video-localization-project (JP 파이프라인, 2026-08-10 배선).

분산 원칙: generate 는 아무 노드에서나 돌지만 localize 는 localize 캡 노드(mm-06)만 —
그래서 파일은 스토리지를 경유한다: ves-outputs 에서 shorts 를 내려받아
process_video(Level B) 를 돌리고, 산출본을 ves-localized 에 올린 뒤
검수함(review_queue kind='localization_qa')에 등록한다. 승인·발행은 사람 몫(기존과 동일).
⚠ 가동 스위치: planner 의 JP 채널 생성은 ops_config.jp_pipeline='on' 일 때만 —
기존 현지화 autopilot 과의 이중 생산을 막는 컷오버 장치(기본 off).
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import subprocess

from ves import config as cfgmod
from ves.adapters import base
from ves.storage.supabase_storage import Store


def scene_rerender_argv(ai_py: str, engine: str, job_dir: str) -> list:
    """scene_rerender 호출 argv — localize_run 은 **ai-video venv** 로 돈다(런타임 의존
    google-genai·edge-tts 가 그 venv 에 있고, 재렌더도 같은 엔진을 부른다). 순수 — 테스트 대상."""
    return [ai_py, f"{engine}/scripts/localize_run.py", "--job-dir", job_dir]


def localize_argv(py: str, video: str, video_id: str, params: dict) -> list:
    """process_video 호출 argv. 순수 — 테스트 대상."""
    p = params or {}
    argv = [py, "-m", "src.process_video", "--video", video, "--video-id", video_id,
            "--level", str(p.get("level") or "B")]
    if p.get("content_type"):
        argv += ["--content-type", str(p["content_type"])]
    if p.get("backend"):
        argv += ["--backend", str(p["backend"])]
    return argv


def pick_output(paths, video_id: str):
    """outputs/<video_id>/ 안에서 산출 mp4 선택(가장 최근 수정본). 순수."""
    vids = [p for p in (paths or []) if str(p).lower().endswith(".mp4")]
    return max(vids, key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0),
               default=None)


def run(cfg, conn, job, deps):
    if (job.get("params") or {}).get("mode") == "scene_rerender":
        return _run_scene_rerender(cfg, conn, job, deps)
    p = job["params"]
    run_id = p.get("run_id")
    if not run_id:
        raise base.PermanentError("params.run_id 없음 — generate 의존 확인")

    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    work_dir = pathlib.Path(cfg.home) / "cache" / "localize"
    work_dir.mkdir(parents=True, exist_ok=True)
    src_key = base.storage_key(run_id, "shorts.mp4")
    src = work_dir / f"{base.storage_key(run_id, 'in.mp4').split('/')[0]}_in.mp4"
    try:
        store.download("ves-outputs", src_key, str(src))
    except RuntimeError as e:
        raise base.PermanentError(f"원본 다운로드 실패({src_key}): {e}")

    eng = cfgmod.engine_dir(cfg, "localization")
    argv = localize_argv(cfgmod.engine_py(cfg, "localization"), str(src), run_id, p)
    r = subprocess.run(argv, cwd=eng, env=dict(os.environ),
                       capture_output=True, text=True, timeout=3600 * 2)
    if r.returncode != 0:
        blob = (r.stderr or "").lower()
        msg = (r.stderr or r.stdout or "")[-600:]
        if "cuda" in blob or "mps" in blob or "weight" in blob:
            raise base.PermanentError(f"현지화 노드 미구성(가중치/GPU): {msg}")
        cls = base.classify_by_patterns(r.stderr or "", r.stdout or "")
        if cls == "permanent":
            raise base.PermanentError(msg)
        raise RuntimeError(msg)

    out_dir = pathlib.Path(eng) / "outputs" / run_id
    out = pick_output(glob.glob(str(out_dir / "**" / "*.mp4"), recursive=True), run_id)
    if not out:
        raise base.PermanentError(f"현지화 산출 mp4 없음: {out_dir}")
    out_key = base.storage_key(run_id, "localized.mp4")
    store.upload("ves-localized", out_key, str(out))
    src.unlink(missing_ok=True)

    with conn.cursor() as c:
        c.execute("""SELECT 1 FROM public.review_queue
                      WHERE kind='localization_qa' AND work_order_id=%s AND status='waiting'""",
                  (job["work_order_id"],))
        if not c.fetchone():
            c.execute(
                """INSERT INTO public.review_queue
                       (kind, work_order_id, job_id, channel_slug, payload)
                   VALUES ('localization_qa', %s, %s, %s, %s::jsonb)""",
                (job["work_order_id"], job["id"], p.get("channel_slug"),
                 json.dumps({"run_id": run_id, "preview_key": out_key,
                             "bucket": "ves-localized",
                             "note": (r.stdout or "")[-300:]}, ensure_ascii=False)))
    return {"run_id": run_id, "localized_key": out_key,
            "stdout_tail": (r.stdout or "")[-300:]}


def _enqueue_qa(conn, job, payload: dict):
    """localization_qa 검수함 등록(대기중 중복 방지) — 두 모드 공용."""
    with conn.cursor() as c:
        c.execute("""SELECT 1 FROM public.review_queue
                      WHERE kind='localization_qa' AND work_order_id=%s AND status='waiting'""",
                  (job["work_order_id"],))
        if not c.fetchone():
            c.execute(
                """INSERT INTO public.review_queue
                       (kind, work_order_id, job_id, channel_slug, payload)
                   VALUES ('localization_qa', %s, %s, %s, %s::jsonb)""",
                (job["work_order_id"], job["id"], job["params"].get("channel_slug"),
                 json.dumps(payload, ensure_ascii=False)))


def _run_scene_rerender(cfg, conn, job, deps):
    """scene_rerender 모드(2026-08-13) — ai-video 생성 job 디렉토리를 **생성 노드에서**
    재렌더 현지화한다(planner 가 캡 generate + aivideo PIN 으로 이 노드에 고정).
    level B(완성 mp4 후처리)와 달리 파일 왕복이 없다: job 디렉토리·원본 소스가 로컬이다.
    엔진 계약: video-localization-project scripts/localize_run.py --job-dir …
    (성공 마커 = <job_dir>/localize_ja/metadata.json, 산출 = <job_dir>/shorts.mp4 교체본)."""
    p = job["params"]
    gen = (deps or {}).get("generate") or {}
    run_id = gen.get("run_id") or p.get("run_id")
    run_dir = gen.get("run_dir") or p.get("run_dir")
    if not (run_id and run_dir):
        raise base.PermanentError("generate 결과(run_id/run_dir) 없음 — 의존 확인")
    if not os.path.isdir(run_dir):
        # 핀이 풀렸거나(노드 사망 후 수동 해제) 디스크 GC 로 사라진 경우 — 재시도 무의미
        raise base.PermanentError(f"job 디렉토리 없음(노드 어긋남?): {run_dir}")

    eng = cfgmod.engine_dir(cfg, "localization")
    ai_py = cfgmod.engine_py(cfg, "ai_video")
    argv = scene_rerender_argv(ai_py, eng, str(run_dir))
    r = subprocess.run(argv, cwd=eng, env=dict(os.environ),
                       capture_output=True, text=True, timeout=3600 * 2)
    meta_path = pathlib.Path(run_dir) / "localize_ja" / "metadata.json"
    if r.returncode != 0 or not meta_path.exists():
        msg = (r.stderr or r.stdout or "")[-600:]
        cls = base.classify_by_patterns(r.stderr or "", r.stdout or "")
        if cls == "permanent":
            raise base.PermanentError(msg)
        raise RuntimeError(msg)

    out = pathlib.Path(run_dir) / "shorts.mp4"
    if not out.exists():
        raise base.PermanentError(f"현지화 산출 shorts.mp4 없음: {run_dir}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    out_key = base.storage_key(run_id, "localized.mp4")
    store.upload("ves-localized", out_key, str(out))

    _enqueue_qa(conn, job, {"run_id": run_id, "preview_key": out_key,
                            "bucket": "ves-localized", "mode": "scene_rerender",
                            "youtube_title": meta.get("youtube_title"),
                            "description": meta.get("description"),
                            "note": "\n".join(meta.get("notes") or [])[:300]})
    return {"run_id": run_id, "localized_key": out_key, "mode": "scene_rerender",
            "youtube_title": meta.get("youtube_title"),
            "stdout_tail": (r.stdout or "")[-300:]}
