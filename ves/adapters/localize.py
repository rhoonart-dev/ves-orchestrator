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


# ── 더빙(TTS) ────────────────────────────────────────────────────────────
# ⚠ process_video 는 더빙을 하지 않는다 — 그 스크립트 머리말에 "Level C 더빙은 이 스크립트가
#   호출하지 않는다(게이트 통과 후 src/dub.py 별도)"라고 적혀 있다. autopilot 은 _run_dub 로
#   따로 불렀지만 VES 경로엔 그 배선이 없어서, 등급 C 를 줘도 오디오가 한국어 그대로였다
#   (2026-08-12 사용자 지적). 여기서 같은 계약으로 잇는다.
DUB_LEVELS = ("C", "BC")


def needs_dub(level) -> bool:
    """이 등급이 더빙을 포함하는가. 순수 — 테스트 대상."""
    return str(level or "").upper() in DUB_LEVELS


def dub_argv(py: str, video: str, video_id: str, voice_id, config_path=None) -> list:
    """src.dub 호출 argv. autopilot._dub_cmd 와 같은 형식(`--opt=value` — video_id 가
    하이픈으로 시작해도 안전). 순수 — 테스트 대상.

    voice_id 를 반드시 실어 보낸다. 안 실으면 dub 이 config.dub.voice_id 로 떨어지는데
    그 값은 잔망루피 클론 보이스라, 다른 채널이 루피 목소리로 더빙된다."""
    if not str(voice_id or "").strip():
        raise base.PermanentError(
            "더빙 목소리(params.voice_id)가 없습니다 — ops_config.localize_voices 에 "
            "이 채널의 ElevenLabs voice_id 를 넣으세요. 비워두면 잔망루피 목소리로 나갑니다")
    argv = [py, "-m", "src.dub", f"--video-id={video_id}", f"--video={video}",
            "--level=C", f"--voice={voice_id}"]
    if config_path:
        argv.append(f"--config={config_path}")
    return argv


# ── 등급 J (2026-08-13 사용자 결정): JP 변환은 이 레포가 아니라 vlp 가 담당 ──
# ai-video 는 무변경. vlp convert_short 가 edit_plan 을 받아 제목·자막을 일본어로 재렌더하고
# 나레이션 구간만 일본어 TTS 로 교체한다. 원본 방송 오디오·노래는 그대로(자막으로만 전달).
JP_CONVERT_LEVEL = "J"


def is_jp_convert(level) -> bool:
    """convert_short 경로인가. 순수 — 테스트 대상."""
    return str(level or "").upper() == JP_CONVERT_LEVEL


def convert_argv(py: str, video: str, plan: str, out: str, voice_id) -> list:
    """vlp src.convert_short 호출 argv. voice_id 필수 — 없으면 dub 전역 config(잔망루피
    클론 보이스) 로 떨어지는 대신 여기서 거부한다. 순수 — 테스트 대상."""
    if not str(voice_id or "").strip():
        raise base.PermanentError(
            "나레이션 목소리(params.voice_id) 없음 — ops_config.localize_voices 에 "
            "이 채널의 ElevenLabs voice_id 를 넣으세요")
    return [py, "-m", "src.convert_short", f"--video={video}", f"--edit-plan={plan}",
            f"--out={out}", f"--voice={voice_id}"]


def pick_output(paths, video_id: str):
    """outputs/<video_id>/ 안에서 산출 mp4 선택(가장 최근 수정본). 순수."""
    vids = [p for p in (paths or []) if str(p).lower().endswith(".mp4")]
    return max(vids, key=lambda p: (os.path.getmtime(p) if os.path.exists(p) else 0),
               default=None)


def run(cfg, conn, job, deps):
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
    if is_jp_convert(p.get("level")):
        # 등급 J: edit_plan 이 원료다. 없으면 이전(미업로드) run — 재시도 무의미.
        plan_local = work_dir / f"{base.storage_key(run_id, 'p.json').split('/')[0]}_plan.json"
        try:
            store.download("ves-outputs", base.storage_key(run_id, "edit_plan.json"),
                           str(plan_local))
        except RuntimeError as e:
            raise base.PermanentError(
                f"edit_plan 없음({run_id}) — upload_artifacts 신버전 배포 후 새 run 부터 "
                f"가능합니다: {e}")
        out_local = pathlib.Path(eng) / "outputs" / run_id / "localized_ja.mp4"
        out_local.parent.mkdir(parents=True, exist_ok=True)
        dub_py = str(pathlib.Path(eng) / (p.get("dub_python") or ".venv-gsv/bin/python"))
        if not pathlib.Path(dub_py).exists():
            raise base.PermanentError(f"변환 인터프리터 없음: {dub_py}")
        cr = subprocess.run(
            convert_argv(dub_py, str(src), str(plan_local), str(out_local), p.get("voice_id")),
            cwd=eng, env={**os.environ, "is_half": "False", "TERM": "xterm"},
            capture_output=True, text=True, timeout=3600)
        if cr.returncode != 0:
            msg = (cr.stderr or cr.stdout or "")[-600:]
            cls = base.classify_by_patterns(cr.stderr or "", cr.stdout or "")
            if cls == "quota":
                raise base.QuotaError(f"JP 변환 한도: {msg}")
            if cls == "permanent":
                raise base.PermanentError(f"JP 변환 실패: {msg}")
            raise RuntimeError(f"JP 변환 실패: {msg}")
        note_tail = (cr.stdout or "")[-300:]
    else:
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
        note_tail = (r.stdout or "")[-300:]

    # 더빙(TTS 일본어) — 등급이 요구하면 process_video 뒤에 이어 돌린다.
    # 인터프리터는 autopilot 과 같은 것(.venv-gsv, 파이썬 3.11 전용 스택)을 쓴다.
    if needs_dub(p.get("level")):
        dub_py = str(pathlib.Path(eng) / (p.get("dub_python") or ".venv-gsv/bin/python"))
        if not pathlib.Path(dub_py).exists():
            raise base.PermanentError(f"더빙 인터프리터 없음: {dub_py}")
        dr = subprocess.run(dub_argv(dub_py, str(src), run_id, p.get("voice_id")),
                            cwd=eng, env={**os.environ, "is_half": "False", "TERM": "xterm"},
                            capture_output=True, text=True, timeout=3600)
        if dr.returncode != 0:
            msg = (dr.stderr or dr.stdout or "")[-600:]
            cls = base.classify_by_patterns(dr.stderr or "", dr.stdout or "")
            if cls == "quota":
                raise base.QuotaError(f"더빙 한도: {msg}")
            if cls == "permanent":
                raise base.PermanentError(f"더빙 실패: {msg}")
            raise RuntimeError(f"더빙 실패: {msg}")

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
                             "note": note_tail}, ensure_ascii=False)))
    return {"run_id": run_id, "localized_key": out_key, "stdout_tail": note_tail}
