#!/usr/bin/env python3
"""brain CLI 어댑터 3종 — ingest / evaluate / publish.

판정 규칙(D1~D6·R1~R6)은 brain 코드가 소유한다 — 여기서는 argv 만 만든다(§3).
measure/audit 접합은 Phase 4(reconcile 이 잡을 만들 때 활성화 — scheduler/reconcile.py).
"""
from __future__ import annotations

import glob

from ves import config as cfgmod
from ves.adapters import base


def _py(cfg):
    return cfgmod.engine_py(cfg, "brain")


def _scripts(cfg):
    return f"{cfgmod.engine_dir(cfg, 'brain')}/scripts"


def _env(cfg):
    # 발행 토큰(YT_REFRESH_TOKEN_*)도 사람이 노드에 나중에 넣는다 — aivideo 와 같은
    # 규약으로 잡마다 env 파일을 다시 읽는다(config.job_env).
    return cfgmod.job_env(cfg)


class Ingest:
    """생성물 → fdidiqd provenance 적재 (ingest_aivideo_run.py)."""

    @staticmethod
    def cwd(cfg, job):
        return cfgmod.engine_dir(cfg, "brain")

    @staticmethod
    def env(cfg, job):
        return _env(cfg)

    @staticmethod
    def build_argv(cfg, job):
        p = job["params"]
        run_dir = p.get("run_dir")
        if not run_dir:
            raise base.PermanentError("params.run_dir 없음 — planner/의존 결과 확인")
        return [_py(cfg), f"{_scripts(cfg)}/ingest_aivideo_run.py",
                "--run-dir", run_dir, "--short-label", p.get("short_label", "shorts_1"),
                "--channel", p["channel_name"]]

    @staticmethod
    def parse_result(cfg, job, stdout):
        return {"stdout_tail": (stdout or "")[-400:]}

    @staticmethod
    def classify_error(rc, stderr, stdout):
        return base.classify_by_patterns(stderr, stdout)


def feature_argv(py: str, scripts: str) -> list:
    """피처 추출은 배치형 — DB 에서 미처리 클립을 스스로 고른다(--limit 안전빵). 순수."""
    return [py, f"{scripts}/run_feature_extraction.py", "--limit", "50"]


def judge_argv(py: str, scripts: str, clip_id: str, video: str | None) -> list:
    """judge 는 클립 단위(--clip-id). 로컬 영상이 있으면 --video 로 다운로드 생략. 순수."""
    argv = [py, f"{scripts}/run_judge.py", "--clip-id", clip_id]
    if video:
        argv += ["--video", video]
    return argv


class Evaluate:
    """피처(배치) + judge 안전게이트 — 네이티브 2단 실행. judge 는 성과 예측에 쓰지 않는다(D3).
    ⚠ 스모크3 실측: 종전의 evaluate_run.py 는 brain 에 존재한 적 없는 스크립트였다.
    실제 CLI 는 run_feature_extraction.py(배치) + run_judge.py(--clip-id) 2종이며,
    클립 ID 는 ingest 가 만든 clips/clip_metadata 에서 (ai_video_run_id, episode)로 찾는다."""

    FIND_CLIP_SQL = """SELECT c.id FROM public.clips c
                         JOIN public.clip_metadata m ON m.clip_id = c.id
                        WHERE m.ai_video_run_id = %s AND c.source = 'auto_edit'
                          AND c.episode IS NOT DISTINCT FROM %s LIMIT 1"""

    @staticmethod
    def run(cfg, conn, job, deps):
        import subprocess
        p = job["params"]
        run_id = p.get("run_id")
        if not run_id:
            raise base.PermanentError("params.run_id 없음 — 의존 결과/planner 확인")
        with conn.cursor() as c:
            c.execute(Evaluate.FIND_CLIP_SQL, (run_id, p.get("short_label", "shorts_1")))
            row = c.fetchone()
        if not row:
            raise base.PermanentError(f"ingest 된 클립 없음 (run={run_id}) — ingest 선행 확인")
        clip_id = str(row["id"] if isinstance(row, dict) else row[0])

        video = None
        if p.get("run_dir"):
            vids = [v for v in glob.glob(f"{p['run_dir']}/shorts*.mp4") if "_480" not in v]
            video = vids[0] if vids else None

        py, scripts = _py(cfg), _scripts(cfg)
        env, cwd = _env(cfg), cfgmod.engine_dir(cfg, "brain")
        for argv, timeout in ((feature_argv(py, scripts), 900),
                              (judge_argv(py, scripts, clip_id, video), 1200)):
            r = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                               text=True, timeout=timeout)
            if r.returncode != 0:
                msg = (r.stderr or r.stdout or "")[-800:]
                cls = base.classify_by_patterns(r.stderr or "", r.stdout or "")
                if cls == "quota":
                    raise base.QuotaError(msg)
                if cls in ("permanent", "human_required"):
                    raise base.PermanentError(msg)
                raise RuntimeError(msg)
        return {"clip_id": clip_id, "judged": True}

    @staticmethod
    def post_success(cfg, conn, job, result):
        """안전게이트 통과분을 사람 검수 대기열에 — 검수(D5-①)는 review_queue 로 통합(§8-1).

        JP 현지화 파이프라인은 제외(사용자 결정 8/14: "일본어로 된 영상만 올라오면 돼") —
        이 시점의 preview 는 현지화 전 한국어판이라 보여줄 것도 결정할 것도 없다.
        그 체인의 게이트는 localize 가 올리는 localization_qa(일본어판) 하나다.
        (발행은 0033 부터 그 카드로 — approve_and_publish 가 두 kind 를 다 받는다)"""
        p = job["params"]
        with conn.cursor() as c:
            c.execute("SELECT pipeline FROM public.work_orders WHERE id=%s",
                      (job["work_order_id"],))
            row = c.fetchone()
            if row and row["pipeline"] == "shorts_jp_localized":
                return
        with conn.cursor() as c:
            # 편집 재렌더 성공 청소(F-302, 0050) — '성공하면 지우고 실패하면 남긴다'.
            # waiting 중복 skip **보다 먼저**: skip 경로에서도 이 evaluate 의 편집 체인은
            # 성공했다(초안 반영 완료). 뒤에 두면 그 경로에서 보낸 초안이 영구 잔존해
            # 같은 run 의 카드에 낡은 편집이 이중 적용된다. 통상 파이프라인은 0행 — 무해.
            c.execute(
                """UPDATE public.editor_assets
                       SET draft=NULL, draft_at=NULL, draft_by=NULL, draft_sent_at=NULL
                     WHERE run_id=%s AND draft_sent_at IS NOT NULL""",
                (p.get("run_id"),))
            c.execute(
                """SELECT 1 FROM public.review_queue
                    WHERE kind='publish_gate' AND work_order_id=%s AND status='waiting'""",
                (job["work_order_id"],))
            if c.fetchone():
                return
            import json
            # 편집 지침 칩·재생성 배지(8/20) — 부가 정보라 조회 실패가 검수 등록을 막지 않는다.
            # ★말로만 그랬고 실제로는 막았다(8/20 사고): _regen_info 가 rejected_takes 에
            #   없는 컬럼(created_at)으로 정렬해 post_success 가 통째로 죽었다. executor 는
            #   훅 예외를 삼키고 잡은 succeeded 로 남아, 생성은 됐는데 검수함에 카드가 한 장도
            #   안 올라오는 상태가 두 시간 이어졌다(커리어데이·국대 2건). 화면에는 아무 신호도
            #   없었다 — 그래서 지금은 **부가 정보 수집 전체를 감싼다**. 칩이 빠질지언정
            #   카드는 반드시 만든다.
            extra = {}
            try:
                ed, ed_run = _run_log_editorial(cfg, p)
                if ed:
                    extra["editorial"] = ed
                if ed_run:
                    extra["editorial_run"] = ed_run   # '추가 생성된 영상' 배지의 기획 방향 원문
                rg = _regen_info(conn, job["work_order_id"])
                if rg:
                    extra["regen"] = rg
                ei = _editor_info(conn, p.get("run_id"))
                if ei:
                    extra["editor"] = ei      # '편집된 영상' 배지(8/21)
            except Exception as e:  # noqa: BLE001 — 칩·배지는 없어도 검수는 돌아야 한다
                print(f"[evaluate] 검수 카드 부가 정보 수집 실패(카드는 만든다): "
                      f"{type(e).__name__} {e}")
                extra = {}
                # 연결은 autocommit(db.connect) 이라 실패한 조회가 다음 INSERT 를
                # 막지 않는다 — 여기서 트랜잭션을 되돌릴 것도 없다.
            c.execute(
                """INSERT INTO public.review_queue
                       (kind, work_order_id, job_id, channel_slug, clip_id, payload)
                   VALUES ('publish_gate', %s, %s, %s, %s, %s::jsonb)""",
                (job["work_order_id"], job["id"], p.get("channel_slug"),
                 result.get("clip_id"),      # 0018: 발행 RPC 가 쓰는 정본 — NULL 이면 발행 불가
                 json.dumps({"run_id": p.get("run_id"),
                             # 업로더와 같은 키 규약(base.storage_key) — 한글 키 금지(스모크3)
                             "preview_key": base.storage_key(p.get("run_id"), "preview.mp4"),
                             "note": result.get("stdout_tail", "")[-300:],
                             **extra},
                            ensure_ascii=False)))


class Publish:
    """발행 (publish_youtube.py) — R9/지오블락/오채널 게이트는 이 스크립트가 최종 방어선.
    ⚠ 예약공개(publishAt)는 publish_youtube.py 에 아직 없다 — Phase 2 코드 작업(놓친 부분 ④)."""

    @staticmethod
    def cwd(cfg, job):
        return cfgmod.engine_dir(cfg, "brain")

    @staticmethod
    def env(cfg, job):
        return _env(cfg)

    @staticmethod
    def resource(cfg, job):
        return "yt_upload:_global"

    @staticmethod
    def build_argv(cfg, job):
        p = job["params"]
        if p.get("privacy") == "public":
            # R9: public 직행 금지 — RPC 가 걸렀어야 하나 여기서도 차단(이중 방어)
            raise base.PermanentError("R9: publish 잡은 private/unlisted/예약만")
        video = p.get("video_path") or _find_video(cfg, p.get("run_id"), p.get("outdir"))
        if not video:
            # Storage 폴백(8/11 실측 수정): 로컬에 없으면 업로더가 올린 사본을 내려받는다 —
            # 발행이 '생성한 그 노드'에 묶이지 않게 하는 장치(종전 TODO Phase 2).
            video = _fetch_from_storage(cfg, p.get("run_id"))
        if not video:
            raise base.PermanentError(
                f"영상 파일 못 찾음 (run={p.get('run_id')}) — 로컬·Storage 모두 없음")
        argv = [_py(cfg), f"{_scripts(cfg)}/publish_youtube.py",
                "--clip-id", p["clip_id"], "--video", video,
                "--channel", p["channel_name"], "--publish",
                "--privacy", p.get("privacy", "unlisted")]
        if p.get("episode") is not None:
            # 설명란 '<작품명> N화' 줄 — 없으면 스크립트가 '회차 미상' 경고(8/11 실측)
            argv += ["--episode", str(p["episode"])]
        # 현지화판 메타(2026-08-23) — JP 카드에서만 채워진다(approve_and_publish 가
        # localization_qa 카드 payload 에서 옮겨 담는다). 없으면 종전과 완전히 동일:
        # brain 이 clip_metadata 의 **한국어** top_title 과 한국어 작품명으로 조립한다.
        # 그것이 일본어 채널(ショトコン)에 한국어 제목·해시태그가 그대로 올라가던 원인이다
        # (실측 clip 606a7e5c: title '몸만 오면 된다더니 …', #혜미리예채파).
        if p.get("publish_title"):
            argv += ["--title", str(p["publish_title"])]
        if p.get("publish_description"):
            argv += ["--description", str(p["publish_description"])]
        tags = [str(t).strip() for t in (p.get("publish_tags") or []) if str(t).strip()]
        if tags:
            argv += ["--hashtags", *tags]
        if p.get("publish_at"):
            argv += ["--publish-at", p["publish_at"]]   # TODO(Phase 2): 스크립트에 추가 필요
        return argv

    @staticmethod
    def parse_result(cfg, job, stdout):
        return {"stdout_tail": (stdout or "")[-400:]}

    @staticmethod
    def classify_error(rc, stderr, stdout):
        blob = (stderr or "") + (stdout or "")
        if "uploadLimitExceeded" in blob or "quotaExceeded" in blob:
            return "quota"
        return base.classify_by_patterns(stderr, stdout)

    @staticmethod
    def is_already_done(cfg, job):
        return False  # publish_youtube 가 clip 상태로 자체 멱등 처리 — 이중 업로드는 스크립트가 방어


def _find_video(cfg, run_id, outdir):
    if not run_id:
        return None
    base_dir = f"{cfgmod.engine_dir(cfg, 'ai_video')}/{outdir or 'outputs'}/{run_id}"
    vids = [v for v in glob.glob(f"{base_dir}/shorts*.mp4") if "_480" not in v]
    return vids[0] if vids else None


def _run_log_editorial(cfg, p):
    """run_log.input → (editorial, editorial_run) — 검수 카드 지침 칩·'추가 생성' 배지의
    데이터원(8/20). editorial 은 병합 적용본(칩), editorial_run 은 이번 실행에만 얹은
    지시의 **원문**(배지에서 상시 지침과 구분해 보여준다 — 운영 결정 8/20).

    ai-video 가 둘 다 run_log 에 남긴다(그쪽 4a3bb3a·후속). 로컬(run_dir →
    표준 경로) 우선, 없으면 업로더가 올린 Storage 사본(run_log.json) — evaluate 가
    생성 노드와 다른 맥에서 돌 수 있어 폴백이 필요하다(_fetch_from_storage 와 같은 이유).
    실패는 (None, None) — 칩은 부가 정보라 검수 등록을 막지 않는다."""
    import json as _json
    import pathlib
    rid = p.get("run_id")
    if not rid:
        return None, None
    cands = []
    if p.get("run_dir"):
        cands.append(pathlib.Path(p["run_dir"]) / "run_log.json")
    cands.append(pathlib.Path(cfgmod.engine_dir(cfg, "ai_video"))
                 / (p.get("outdir") or "outputs") / rid / "run_log.json")
    raw = None
    for f in cands:
        try:
            raw = f.read_text(encoding="utf-8")
            break
        except OSError:
            continue
    if raw is None:
        try:
            from ves.storage.supabase_storage import Store
            dest = pathlib.Path(cfg.home) / "cache" / "runlog" / f"{rid}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            Store(cfg.supabase_url, cfg.supabase_service_key).download(
                "ves-outputs", base.storage_key(rid, "run_log.json"), str(dest))
            raw = dest.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001 — 부가 정보 실패는 로그만
            print(f"[evaluate] run_log 조회 실패({rid}): {e}")
            return None, None
    try:
        inp = _json.loads(raw).get("input") or {}
        return inp.get("editorial") or None, inp.get("editorial_run") or None
    except (ValueError, AttributeError):
        return None, None


def _regen_info(conn, work_order_id):
    """반려 재생성 배지(8/20) — rejected_takes 의 최신 사유·단계와 회수.
    반려 기록이 없으면 None(첫 생성 카드에는 배지가 안 뜬다)."""
    with conn.cursor() as c:
        c.execute("""SELECT stage, note FROM public.rejected_takes
                      WHERE work_order_id=%s ORDER BY rejected_at DESC""",
                  (work_order_id,))
        rows = c.fetchall()
    if not rows:
        return None
    return {"tries": len(rows), "stage": rows[0]["stage"], "note": rows[0]["note"]}


def _editor_info(conn, run_id):
    """편집된 영상 배지(8/21) — 0067 submit_editor_render 가 남긴 감사 기록에서
    이 run 의 마지막 편집 요약을 뽑는다. 편집실을 안 거친 카드에는 None(배지 없음).

    출처를 감사 로그로 잡은 이유: 0067 이 이미 keys·carried·subs·clips·tts·images·note 를
    거기 다 적고 있다 — 같은 값을 다른 자리에 또 쓰면 두 벌이 어긋난다.
    nth 는 같은 run 의 편집 횟수(2회 이상이면 배지 칩에 '2번째'로 붙는다).
    actor 는 auth.uid() 라 이메일은 auth.users 에서 되찾는다 — 못 찾으면 uid 를 그대로 둔다."""
    if not run_id:
        return None
    with conn.cursor() as c:
        c.execute("""SELECT a.at, a.actor, a.payload
                       FROM public.dashboard_actions a
                      WHERE a.action='editor_render'
                        AND a.payload->>'run_id' = %s
                      ORDER BY a.at DESC""", (run_id,))
        rows = c.fetchall()
    if not rows:
        return None
    top, pay = rows[0], rows[0]["payload"] or {}
    keys = pay.get("keys") or []
    by = top["actor"]
    with conn.cursor() as c:
        c.execute("SELECT email FROM auth.users WHERE id::text=%s", (str(by),))
        u = c.fetchone()
    if u and u.get("email"):
        by = u["email"]
    return {"nth": len(rows), "at": top["at"].isoformat(), "by": by,
            "title": "title" in keys, "design": "design" in keys,
            "subs": pay.get("subs") or 0, "clips": pay.get("clips") or 0,
            "tts": pay.get("tts") or 0, "images": pay.get("images") or 0,
            "texts": pay.get("texts") or 0,            # F-411(0071 감사 payload)
            "carried": pay.get("carried") or [],
            "resubmit": bool(pay.get("resubmit")), "note": pay.get("note")}


def _fetch_from_storage(cfg, run_id):
    """업로더가 올린 ves-outputs/<키>/shorts.mp4 를 노드 캐시로 내린다. 실패는 None."""
    if not run_id:
        return None
    import pathlib
    from ves.storage.supabase_storage import Store
    dest = pathlib.Path(cfg.home) / "cache" / "publish" / f"{run_id}.mp4"
    if dest.exists() and dest.stat().st_size > 0:
        return str(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        Store(cfg.supabase_url, cfg.supabase_service_key).download(
            "ves-outputs", base.storage_key(run_id, "shorts.mp4"), str(dest))
    except Exception as e:  # noqa: BLE001 — 폴백 실패는 상위에서 명확한 메시지로 처리
        print(f"[publish] Storage 폴백 실패({run_id}): {e}")
        return None
    return str(dest) if dest.exists() and dest.stat().st_size > 0 else None
