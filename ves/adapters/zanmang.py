#!/usr/bin/env python3
"""zanmang_autopilot 어댑터 — 잔망루피 현지화 autopilot 실행 (subprocess 형, 2026-08-10).

구 파이프라인을 재작성하지 않고 편입한다: 그 레포의 .venv 로 `src.autopilot <task>` 를
그대로 실행 — 원장(outputs/autopilot.db)·YouTube 토큰·가중치 전부 기존 위치를 쓴다.
관제에는 성공/실패·단계별 건수가 남고, 승인(approve)은 종전대로 사람이 그 레포 CLI 로.

⚠ 이 CLI 는 진행 로그를 전부 logging(=stderr) 으로 낸다 — WANT_STDERR 로 stderr 를
받아 요약한다(8/11 실측: 성공했는데 stdout 이 비어 '무슨 일이 있었는지' 알 수 없었다).
"""
from __future__ import annotations

import json
import pathlib
import re

from ves.adapters import base

WANT_STDERR = True                       # executor 계약: parse_result(cfg, job, out, err)
DEFAULT_REPO = "/opt/ves/engines/video-localization-project"
TASKS = ("daily", "status", "scan", "score", "report", "pending")
LEDGER_REL = "outputs/autopilot.db"      # config autopilot.ledger_path 기본값
CHANNEL = "LOOPY"                        # 관제 채널 슬러그(channels_mirror)

# 라우트별 최종 산출물 — src/autopilot.py final_video_for 와 같은 규약.
# A(무변환)는 파일이 없다: 원본 유튜브 영상을 그대로 쓰므로 검수는 원본 URL 로 본다.
FINAL_BY_ROUTE = {"B":  ["final_draft.mp4"],
                  "BJ": ["final_draft.mp4"],   # 병기 자막도 같은 파일(8/14 실측 — 빠지면
                  #   검수 카드가 산출물을 못 찾는다. vlp final_video_for 와 같은 지도)
                  "C":  ["final_dubbed_subbed.mp4", "final_dubbed.mp4"],
                  "BC": ["final_dubbed_subbed.mp4", "final_dubbed.mp4"]}

# 로그 한 줄 → 관제에 남길 지표 (원문 문구는 src/autopilot.py 의 log.info 계약)
_METRICS = [
    ("scanned",   re.compile(r"scan 완료: 수집 (\d+)편")),
    ("new",       re.compile(r"scan 완료: 수집 \d+편, 신규 (\d+)편")),
    ("scored",    re.compile(r"scor\w*[: ]+(\d+)\s*편")),
    ("processed", re.compile(r"process\w*[: ]+(\d+)\s*편")),
    ("approved",  re.compile(r"승인[^0-9]{0,10}(\d+)\s*편")),
    ("uploaded",  re.compile(r"업로드[^0-9]{0,10}(\d+)\s*편")),
]


def daily_argv(repo: str, task: str = "daily") -> list:
    """autopilot 실행 argv. 순수 — 테스트 대상. 허용 task 만(임의 실행 차단)."""
    if task not in TASKS:
        raise base.PermanentError(f"허용되지 않은 task: {task} (허용: {', '.join(TASKS)})")
    return [f"{repo}/.venv/bin/python", "-m", "src.autopilot", task]


def action_argv(repo: str, task: str, video_id: str, state: str | None = None,
                privacy: str | None = None, publish_at: str | None = None) -> list:
    """video_id 를 받는 CLI(approve·upload·mark) argv. 순수 — 테스트 대상.

    daily_argv 와 나눈 이유: 이 셋은 인자를 받고, 사람 결정을 원장에 확정하는 쓰기 명령이라
    허용 목록을 따로 좁게 둔다(임의 실행 차단).

    upload 공개 방식(관제 3택, 8/14): schedule|private|unlisted 만 — public 은 여기서도
    막는다(R9). publish_at 은 schedule 에서만 의미가 있고 ISO 형태만 통과시킨다."""
    if task not in ("approve", "upload", "mark"):
        raise base.PermanentError(f"허용되지 않은 결정 task: {task}")
    if not (video_id or "").strip():
        raise base.PermanentError("video_id 없음")
    argv = [f"{repo}/.venv/bin/python", "-m", "src.autopilot", task, str(video_id)]
    if task == "mark":
        if state not in ("selected", "skipped"):
            raise base.PermanentError(f"mark state 는 selected|skipped (받은 값: {state})")
        argv += ["--state", state]
    if task == "upload":
        if privacy is not None:
            if privacy not in ("schedule", "private", "unlisted"):
                raise base.PermanentError(
                    f"upload privacy 는 schedule|private|unlisted (받은 값: {privacy})")
            argv += ["--privacy", privacy]
        if publish_at:
            import re as _re
            if not _re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", str(publish_at)):
                raise base.PermanentError(f"publish_at 형식 오류(ISO8601 필요): {publish_at}")
            argv += ["--publish-at", str(publish_at)]
    return argv


def final_video(route, base_dir) -> str | None:
    """라우트별 최종 산출 영상 경로. 없으면 None(=A 무변환이거나 산출 실패). 순수."""
    d = pathlib.Path(base_dir)
    for name in FINAL_BY_ROUTE.get(str(route or "").upper(), []):
        if (d / name).exists():
            return str(d / name)
    return None


def pending_rows(ledger_path) -> list:
    """원장에서 승인 대기 목록을 읽는다. CLI stdout 파싱 대신 sqlite 직독 —
    로그 문구가 바뀌어도 안 깨지고, 필드(제목·점수·라우트)를 그대로 가져올 수 있다.
    원장이 없으면 빈 목록(아직 한 번도 안 돌았거나 경로가 다름)."""
    p = pathlib.Path(ledger_path)
    if not p.exists():
        print(f"[zanmang] 원장 없음: {p}")
        return []
    import sqlite3
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)   # 읽기 전용 — autopilot 과 경합 금지
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT video_id, title, url, level_guess, score, notes "
            "  FROM videos WHERE state='pending_approval' ORDER BY view_count DESC")]
    finally:
        conn.close()


def ledger_row_params(r: dict) -> tuple:
    """sqlite videos 행 → loopy_ledger upsert 파라미터. scores 는 JSON 문자열 그대로
    jsonb 로(깨진 값은 NULL). 순수 — 테스트 대상."""
    import json as _json
    scores = r.get("scores")
    if scores is not None:
        try:
            _json.loads(scores)
        except (TypeError, ValueError):
            scores = None
    return (r.get("video_id"), r.get("title"), r.get("url"), r.get("duration"),
            r.get("view_count"), r.get("like_count"), r.get("comment_count"),
            r.get("published_at"), r.get("state"), r.get("level_guess"),
            r.get("score"), scores, r.get("notes"), r.get("discovered_at"),
            r.get("updated_at"), r.get("publish_at"), r.get("youtube_id"))


_MIRROR_SQL = """INSERT INTO public.loopy_ledger
    (video_id, title, url, duration, view_count, like_count, comment_count,
     published_at, state, level_guess, score, scores, notes, discovered_at,
     updated_at, publish_at, youtube_id, synced_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s, now())
ON CONFLICT (video_id) DO UPDATE SET
    title=excluded.title, url=excluded.url, duration=excluded.duration,
    view_count=excluded.view_count, like_count=excluded.like_count,
    comment_count=excluded.comment_count, published_at=excluded.published_at,
    state=excluded.state, level_guess=excluded.level_guess, score=excluded.score,
    scores=excluded.scores, notes=excluded.notes, discovered_at=excluded.discovered_at,
    updated_at=excluded.updated_at, publish_at=excluded.publish_at,
    youtube_id=excluded.youtube_id, synced_at=now()"""


def _mirror_ledger(conn, repo: pathlib.Path) -> int:
    """sqlite 원장 전체 → public.loopy_ledger (B안 2단계 ①, 0034).

    미러는 사본이다 — 정본은 여전히 sqlite 고, 여기 실패해도 검수·업로드는 계속돼야
    한다(호출부에서 삼킨다). 행수 수천 규모라 통째로 upsert 해도 daily 한 번당 1초대."""
    import sqlite3
    db = repo / LEDGER_REL
    if not db.exists():
        return 0
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in src.execute("SELECT * FROM videos")]
    finally:
        src.close()
    if not rows:
        return 0
    with conn.cursor() as c:
        c.executemany(_MIRROR_SQL, [ledger_row_params(r) for r in rows])
    return len(rows)


LOOPY_TEXT_FILES = ("metadata_draft.json", "translations.json", "ko_ja_pairs.json",
                    "ja.srt", "ja_dub.srt")


def loopy_store_key(vid: str, name: str) -> str:
    """루피 산출물 스토리지 키 — 아무 맥에서나 approve/upload 를 잇는 복원 원료(2단계 ③).
    video_id 는 유튜브 id(ASCII)라 한글 키 문제(스모크3)가 없다. 순수 — 테스트 대상."""
    return f"loopy/{vid}/{name}"


def review_meta(out_dir) -> dict:
    """검수 카드용 한글 대역(8/14) — outputs/<vid> 의 산출 파일에서 모은다.
    제목·설명: metadata_draft.json(_ko 대역 포함), 자막 쌍: ko_ja_pairs.json(C 더빙)
    또는 translations.json(B/BJ, source→target). 파일이 없거나 깨져도 카드 등록은
    계속돼야 한다 — 조용히 비운다. 순수(파일 읽기만) — 테스트 대상."""
    import json as _json
    d = pathlib.Path(out_dir)
    out: dict = {}
    try:
        md = _json.loads((d / "metadata_draft.json").read_text(encoding="utf-8"))
        cands = md.get("title_candidates") or []
        cands_ko = md.get("title_candidates_ko") or []
        if cands:
            out["youtube_title"] = cands[0]
        if cands_ko:
            out["youtube_title_ko"] = cands_ko[0]
        if md.get("description"):
            out["description"] = md["description"]
        if md.get("description_ko"):
            out["description_ko"] = md["description_ko"]
    except (OSError, ValueError):
        pass
    subs = []
    try:
        pj = _json.loads((d / "ko_ja_pairs.json").read_text(encoding="utf-8"))
        subs = [x for x in (pj.get("subs") or []) if x.get("ko") or x.get("ja")][:40]
    except (OSError, ValueError):
        pass
    if not subs:
        try:
            tj = _json.loads((d / "translations.json").read_text(encoding="utf-8"))
            subs = [{"ko": e.get("source"), "ja": e.get("target")}
                    for e in (tj.get("entries") or []) if e.get("source")][:40]
        except (OSError, ValueError):
            pass
    if subs:
        out["ko_ja_pairs"] = {"subs": subs}
    return out


def post_success(cfg, conn, job, result):
    """daily 가 끝나면 승인 대기분을 VES 검수함에 올린다 (사용자 요청 8/12).

    종전엔 승인이 그 레포 CLI 로만 가능했다(`approve <id>`) — 사람이 mm-06 에 붙어야 했다.
    이제 다른 채널과 똑같이 관제 검수함에서 보고 누른다. 승인/반려는 decide_loopy RPC 가
    zanmang_decision 잡을 만들어 원장에 확정한다(0026).

    · 검수 영상은 ves-localized 로 올려 카드에서 바로 재생되게 한다.
    · A(무변환) 라우트는 산출물이 없다 — payload.url(원본)로 대신 본다.
    · 이미 대기 중인 건은 건너뛴다(매일 daily 가 도는데 카드가 쌓이면 안 된다).
    """
    if (job.get("params") or {}).get("task", "daily") != "daily":
        return
    repo = pathlib.Path(cwd(cfg, job))
    try:
        n = _mirror_ledger(conn, repo)
        if n:
            print(f"[zanmang] 원장 미러 {n}행 → loopy_ledger")
    except Exception as e:  # noqa: BLE001 — 미러 실패가 검수 등록을 막지 않는다
        print(f"[zanmang] 원장 미러 실패(비치명): {e}")
    rows = pending_rows(repo / LEDGER_REL)
    if not rows:
        return
    with conn.cursor() as c:
        c.execute("""SELECT payload->>'zanmang_video_id' AS vid FROM public.review_queue
                      WHERE kind='localization_qa' AND channel_slug=%s AND status='waiting'""",
                  (CHANNEL,))
        already = {r["vid"] for r in c.fetchall() if r["vid"]}

    store = made = None
    for r in rows:
        vid = r["video_id"]
        if vid in already:
            continue
        route = (r.get("level_guess") or "A").upper()
        src = final_video(route, repo / "outputs" / vid)
        key = None
        if src:
            try:
                if store is None:
                    from ves.storage.supabase_storage import Store
                    store = Store(cfg.supabase_url, cfg.supabase_service_key)
                key = base.storage_key(vid, "loopy_ja.mp4")
                store.upload("ves-localized", key, src)
            except Exception as e:  # noqa: BLE001 — 프리뷰 실패로 검수 등록을 막지 않는다
                print(f"[zanmang] 프리뷰 업로드 실패({vid}), 카드는 등록: {e}")
                key = None
        payload = {"zanmang_video_id": vid, "title": r.get("title"), "url": r.get("url"),
                   "route": route, "score": r.get("score"), "notes": r.get("notes"),
                   "repo": str(repo)}
        payload.update(review_meta(repo / "outputs" / vid))
        # 산출물 텍스트 지속화(2단계 ③): approve/upload 가 다른 맥으로 가도 패키지를
        # 재구성할 수 있게 — 실패는 비치명(카드 등록이 우선).
        for name in LOOPY_TEXT_FILES:
            f = repo / "outputs" / vid / name
            if f.exists():
                try:
                    if store is None:
                        from ves.storage.supabase_storage import Store
                        store = Store(cfg.supabase_url, cfg.supabase_service_key)
                    store.upload("ves-runs", loopy_store_key(vid, name), str(f))
                except Exception as e:  # noqa: BLE001
                    print(f"[zanmang] 산출물 지속화 실패(비치명) {vid}/{name}: {e}")
        if key:
            payload.update({"preview_key": key, "bucket": "ves-localized"})
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.review_queue
                       (kind, work_order_id, job_id, channel_slug, payload)
                   VALUES ('localization_qa', NULL, %s, %s, %s::jsonb)""",
                (job["id"], CHANNEL, json.dumps(payload, ensure_ascii=False)))
        made = (made or 0) + 1
    if made:
        print(f"[zanmang] 검수함 등록 {made}건 (승인 대기 {len(rows)}건 중 신규)")


def summarize(stderr: str) -> dict:
    """진행 로그(stderr) → 지표 dict + 마지막 줄들. 순수 — 테스트 대상."""
    text = stderr or ""
    out = {}
    for key, rx in _METRICS:
        m = rx.search(text)
        if m:
            out[key] = int(m.group(1))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out["log_tail"] = "\n".join(lines[-12:])[-900:]
    out["idle"] = not any(v for k, v in out.items() if k != "log_tail" and isinstance(v, int))
    return out


def cwd(cfg, job):
    return (job["params"] or {}).get("repo") or DEFAULT_REPO


def build_argv(cfg, job):
    repo = cwd(cfg, job)
    if not pathlib.Path(f"{repo}/.venv/bin/python").exists():
        raise base.PermanentError(
            f"잔망루피 레포 .venv 없음: {repo} — ops_config zanmang_repo 확인")
    return daily_argv(repo, (job["params"] or {}).get("task") or "daily")


def parse_result(cfg, job, stdout, stderr=""):
    res = summarize(stderr)
    if stdout:
        res["stdout_tail"] = stdout[-400:]
    return res


def classify_error(rc, stderr, stdout):
    blob = (stderr or "") + (stdout or "")
    if "quota" in blob.lower() or "uploadLimitExceeded" in blob:
        return "quota"
    return base.classify_by_patterns(stderr, stdout)
