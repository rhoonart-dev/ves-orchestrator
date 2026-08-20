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


def scene_rerender_argv(ai_py: str, engine: str, job_dir: str,
                        overrides_path: str | None = None) -> list:
    """scene_rerender 호출 argv — localize_run 은 **ai-video venv** 로 돈다(런타임 의존
    google-genai·edge-tts 가 그 venv 에 있고, 재렌더도 같은 엔진을 부른다).
    overrides_path(8/14 반려-수정 재렌더): 검수함에서 고친 텍스트 JSON — 엔진이 L1 번역에
    병합해 고친 본으로 L3+ 를 다시 돈다. 순수 — 테스트 대상."""
    argv = [ai_py, f"{engine}/scripts/localize_run.py", "--job-dir", job_dir]
    if overrides_path:
        argv += ["--overrides", str(overrides_path)]
    return argv


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


def convert_argv(py: str, video: str, plan: str, out: str, voice_id,
                 subs: str | None = None, tts_subs: str | None = None) -> list:
    """vlp src.convert_short 호출 argv. voice_id 필수 — 없으면 dub 전역 config(잔망루피
    클론 보이스) 로 떨어지는 대신 여기서 거부한다. 순수 — 테스트 대상.
    subs/tts_subs(8/13 v2): 자막·나레이션 원료 ASS — 있으면 전달, 없으면 그 요소 생략."""
    if not str(voice_id or "").strip():
        raise base.PermanentError(
            "나레이션 목소리(params.voice_id) 없음 — ops_config.localize_voices 에 "
            "이 채널의 ElevenLabs voice_id 를 넣으세요")
    argv = [py, "-m", "src.convert_short", f"--video={video}", f"--edit-plan={plan}",
            f"--out={out}", f"--voice={voice_id}"]
    if subs:
        argv.append(f"--subs={subs}")
    if tts_subs:
        argv.append(f"--tts-subs={tts_subs}")
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
        # 자막 원료(8/13 v2) — 없으면 그 요소만 생략(자막 없는 회차 허용, 잡은 계속)
        prefix = base.storage_key(run_id, "x").rsplit("/", 1)[0]
        subs_local = tts_subs_local = None
        for fname, var in (("subtitles.ass", "subs"), ("tts_subtitles.ass", "tts")):
            dest = work_dir / f"{prefix}_{fname}"
            try:
                store.download("ves-outputs", base.storage_key(run_id, fname), str(dest))
                if var == "subs":
                    subs_local = dest
                else:
                    tts_subs_local = dest
            except RuntimeError:
                print(f"[localize] {fname} 없음 — 해당 요소 생략(구 run 또는 자막 없는 회차)")
        out_local = pathlib.Path(eng) / "outputs" / run_id / "localized_ja.mp4"
        out_local.parent.mkdir(parents=True, exist_ok=True)
        # 인터프리터(8/13 실측): 변환은 GSV 가 필요 없다 — ElevenLabs·ffmpeg·번역뿐.
        # .venv-gsv 는 pip sync(엔진 requirements) 대상이 아니라 elevenlabs 가 영영 없다.
        # 메인 venv 는 updater 가 requirements.txt 로 동기화한다.
        dub_py = str(pathlib.Path(eng) / p.get("dub_python")) if p.get("dub_python") \
            else cfgmod.engine_py(cfg, "localization")
        if not pathlib.Path(dub_py).exists():
            raise base.PermanentError(f"변환 인터프리터 없음: {dub_py}")
        cr = subprocess.run(
            convert_argv(dub_py, str(src), str(plan_local), str(out_local), p.get("voice_id"),
                         subs=str(subs_local) if subs_local else None,
                         tts_subs=str(tts_subs_local) if tts_subs_local else None),
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
        # B안 1단계(8/14): 핀이 풀렸거나(노드 사망·수동 해제) 디스크 GC 로 사라졌으면
        # ves-runs 번들에서 복원해 **이 노드에서** 계속한다 — 종전엔 즉사(permanent)였다.
        store = Store(cfg.supabase_url, cfg.supabase_service_key)
        _restore_run_dir(cfg, conn, store, run_id, run_dir)

    eng = cfgmod.engine_dir(cfg, "localization")
    ai_py = cfgmod.engine_py(cfg, "ai_video")
    ov_path = None
    if p.get("overrides"):
        # 반려-수정 재렌더(8/14, 0038): 검수함에서 고친 텍스트를 job 디렉토리에 내려놓고
        # 엔진에 넘긴다. 같은 노드 재실행이라 L1 캐시(translation.json) 위에 병합된다.
        ov_path = pathlib.Path(run_dir) / "localize_overrides.json"
        ov_path.write_text(json.dumps(p["overrides"], ensure_ascii=False, indent=2),
                           encoding="utf-8")
    argv = scene_rerender_argv(ai_py, eng, str(run_dir),
                               str(ov_path) if ov_path else None)
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

    # 편집 재렌더 성공 청소(F-302, 0066) — KR 은 brain(evaluate)이 하지만 JP 는
    # brain 이 pipeline 조기 반환이라 여기가 체인의 끝이다. '성공하면 지우고 실패하면
    # 남긴다' — 남으면 같은 run 의 다음 카드에 낡은 편집이 이중 적용된다.
    # 통상 1라운드(보낸 초안 없음)는 0행 — 무해.
    with conn.cursor() as c:
        c.execute("""UPDATE public.editor_assets
                        SET draft=NULL, draft_at=NULL, draft_by=NULL, draft_sent_at=NULL
                      WHERE run_id=%s AND draft_sent_at IS NOT NULL""", (run_id,))

    _enqueue_qa(conn, job, {"run_id": run_id, "preview_key": out_key,
                            "bucket": "ves-localized", "mode": "scene_rerender",
                            "youtube_title": meta.get("youtube_title"),
                            "youtube_title_ko": meta.get("youtube_title_ko"),   # 한글 대역(8/14)
                            "description": meta.get("description"),
                            "description_ko": meta.get("description_ko"),
                            # 한글 대역(8/14 사용자 요청) — 카드에서 일본어 제목·자막을
                            # 한글과 나란히 본다. 엔진(l5_metadata)이 40건 상한을 이미 건다.
                            "ko_ja_pairs": meta.get("ko_ja_pairs"),
                            "note": "\n".join(meta.get("notes") or [])[:300]})
    return {"run_id": run_id, "localized_key": out_key, "mode": "scene_rerender",
            "youtube_title": meta.get("youtube_title"),
            "stdout_tail": (r.stdout or "")[-300:]}


def source_sha_from_runlog(run_log: dict):
    """run_log.input.video_path → 내용주소 sha256. 캐시 경로 규약(§9-2)이 정본 —
    /…/cache/sources/<sha256>. 규약 밖 경로(유튜브 URL 소스 등)는 None. 순수 — 테스트 대상."""
    path = str(((run_log or {}).get("input") or {}).get("video_path") or "")
    name = path.rsplit("/", 1)[-1]
    return name if len(name) == 64 and all(c in "0123456789abcdef" for c in name.lower()) \
        else None


def _restore_run_dir(cfg, conn, store, run_id: str, run_dir: str) -> None:
    """ves-runs 번들 + ves-outputs(shorts) + ves-sources(원본)로 job 디렉토리 복원.

    복원 대상(l4_render 실측 필요집합): run_log.json(플래그·소스경로)·checkpoint_*·
    subtitle_segments.json·edit_plan.json·crop_*.json·*.txt — 전부 번들에 있다.
    shorts.mp4 는 L0 백업(shorts_ko.mp4)과 컷 길이 검증의 기준이라 반드시 넣는다.
    번들이 없으면(구 run) 종전과 같이 permanent — 재시도 무의미."""
    import json as _json
    mkey = base.storage_key(run_id, "run_manifest.json")
    root = pathlib.Path(run_dir)
    root.mkdir(parents=True, exist_ok=True)
    mlocal = root / ".run_manifest.json"
    try:
        store.download("ves-runs", mkey, str(mlocal))
    except RuntimeError as e:
        raise base.PermanentError(
            f"job 디렉토리 없음 + 번들도 없음({run_id}) — 신버전 upload_artifacts 이후 "
            f"run 부터 복원 가능: {e}")
    manifest = _json.loads(mlocal.read_text(encoding="utf-8"))
    bprefix = base.storage_key(run_id, "bundle")
    for item in manifest.get("files", []):
        rel = item["rel"]
        if ".." in rel or rel.startswith("/"):
            continue                      # 경로 탈출 방어
        dest = root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        store.download("ves-runs", f"{bprefix}/{rel}", str(dest))
    # 원본 shorts(KR) — L0 이 shorts_ko.mp4 로 백업하고 L4 가 길이 검증 기준으로 쓴다
    try:
        store.download("ves-outputs", base.storage_key(run_id, "shorts.mp4"),
                       str(root / "shorts.mp4"))
    except RuntimeError as e:
        raise base.PermanentError(f"복원 실패 — ves-outputs 에 shorts.mp4 없음({run_id}): {e}")
    # 소스 마스터 — 내용주소 캐시 경로에 없으면 ves-sources 에서
    try:
        rl = _json.loads((root / "run_log.json").read_text(encoding="utf-8"))
    except Exception:
        rl = {}
    sha = source_sha_from_runlog(rl)
    if sha:
        cache = pathlib.Path(cfgmod.source_cache_path(cfg, sha))
        if not cache.exists():
            with conn.cursor() as c:
                c.execute("SELECT object_key FROM public.sources WHERE sha256=%s", (sha,))
                row = c.fetchone()
            if not row:
                raise base.PermanentError(f"복원 실패 — sources 에 sha 없음: {sha}")
            cache.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".part")
            store.download("ves-sources", row["object_key"], str(tmp))
            tmp.rename(cache)
    mlocal.unlink(missing_ok=True)
    print(f"[localize] job 디렉토리 복원 완료: {run_dir} (번들 {len(manifest.get('files', []))}건)")
