#!/usr/bin/env python3
"""yt_public — YouTube Data API 공개 조회 (키 1개, 읽기 전용).

쓰는 곳 둘:
  · channels_sync — 채널 아이콘(avatar_url) 갱신 (0020)
  · perf_sync     — laeebly 수집 공백 채널의 영상 통계 직접 보완 (커리어데이 실측 8/11)
키는 노드 시크릿(YOUTUBE_API_KEY) 또는 brain .env 의 REACT_APP_YOUTUBE_API_KEY 다.
쿼터: videos.list·channels.list 는 호출당 1유닛 · 50개씩 묶어 부른다 — 하루 수십 유닛.

★2026-08-19 실측. 키를 못 찾으면 두 호출부(성과 보완·아이콘 갱신)가 print 한 줄 남기고
조용히 건너뛴다. 로그는 노드 안에만 있어서 8일 동안 아무도 몰랐고, 그 사이 6개 채널 48편이
성과에서 통째로 비었다. 그래서 (1) 시크릿 파일을 지금 다시 읽고 (2) 성패를 ops_config 에
남겨 관제 화면이 말하게 한다.
"""
from __future__ import annotations

import json
import pathlib
import urllib.parse
import urllib.request

from ves import config as cfgmod

API = "https://www.googleapis.com/youtube/v3"
KEY_NAMES = ("REACT_APP_YOUTUBE_API_KEY", "YOUTUBE_API_KEY")


# ───────── 순수 (테스트 대상) ─────────
def pick_key(*sources):
    """여러 매핑에서 키를 앞에서부터 찾는다(따옴표 벗김). 순수."""
    for src in sources:
        for n in KEY_NAMES:
            v = (src or {}).get(n)
            if v and str(v).strip():
                return str(v).strip().strip('"').strip("'")
    return None


def backfill_reason(pending: int, filled: int, failed_calls: int) -> str:
    """상태 사유 판정. 순수 — 테스트 대상.

    ★2026-08-19 실측. 비공개·삭제된 영상은 videos.list 가 **에러 없이 항목만 빼고** 준다.
    그걸 호출 실패와 같이 묶으면 "API 오류" 붉은 경고가 영영 안 꺼진다(재미쇼츠 1편이 그랬다).
    호출이 깨진 것(키·쿼터·네트워크)과 받을 게 없는 것을 갈라야 경고 수위가 맞는다."""
    if failed_calls:
        return "api_error"
    if pending == 0 or filled >= pending:
        return "ok"
    return "partial" if filled else "unavailable"


def status_payload(reason: str, pending: int, filled: int, at: str) -> str:
    """ops_config 에 남길 상태 JSON. 순수.
    reason: ok | api_key_missing | api_error | partial | unavailable"""
    return json.dumps({"reason": reason, "pending": int(pending), "filled": int(filled),
                       "at": at}, ensure_ascii=False)



def chunk_ids(ids, n: int = 50) -> list:
    """API 는 id 를 50개까지 받는다. 순수."""
    ids = [i for i in (ids or []) if i]
    return [ids[i:i + n] for i in range(0, len(ids), n)]


def parse_video_stats(payload: dict) -> list:
    """videos.list 응답 → [(content_id, views, likes, comments)]. 순수."""
    out = []
    for it in (payload or {}).get("items") or []:
        st = it.get("statistics") or {}
        out.append((it.get("id"),
                    int(st.get("viewCount") or 0),
                    int(st.get("likeCount") or 0),
                    int(st.get("commentCount") or 0)))
    return [r for r in out if r[0]]


def pick_avatar(thumbnails: dict) -> str | None:
    """channels.list snippet.thumbnails → 가장 큰 아이콘 URL. 순수."""
    for k in ("high", "medium", "default"):
        u = ((thumbnails or {}).get(k) or {}).get("url")
        if u:
            return u
    return None


def parse_channel_avatars(payload: dict) -> list:
    """channels.list 응답 → [(channel_id, avatar_url)]. 순수."""
    out = []
    for it in (payload or {}).get("items") or []:
        url = pick_avatar(((it.get("snippet") or {}).get("thumbnails")))
        if it.get("id") and url:
            out.append((it["id"], url))
    return out


# ───────── 실행부 ─────────
def api_key(cfg) -> str | None:
    """환경변수 → 노드 시크릿 파일 → brain .env 순. 시크릿 파일을 **지금 다시 읽는** 것이
    핵심이다 — 기동 때 한 번 읽은 환경변수에만 기대면 사람이 키를 넣어도 재기동 전까지
    못 본다(job_env 와 같은 함정)."""
    import os
    brain = {}
    envp = pathlib.Path(cfgmod.engine_dir(cfg, "brain")) / ".env"
    try:
        for line in envp.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in KEY_NAMES:
                brain[k.strip()] = v
    except OSError:
        pass
    return pick_key(os.environ, cfgmod.file_env(), brain)


def note_status(conn, key: str, reason: str, pending: int, filled: int) -> None:
    """보완의 성패를 관제가 보는 자리에 남긴다. 기록 실패가 본 작업을 죽이지는 않는다."""
    import datetime as dt
    try:
        with conn.cursor() as c:
            c.execute("""INSERT INTO public.ops_config(key, value, note)
                         VALUES (%s, %s, %s)
                         ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value,
                             note=EXCLUDED.note, updated_at=now()""",
                      (key, status_payload(reason, pending, filled,
                                           dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
                       "YouTube 공개 API 보완 상태 — 대시보드가 읽는다(코드가 씀)"))
    except Exception as e:  # noqa: BLE001
        print(f"[yt_public] 상태 기록 실패(무시): {type(e).__name__} {e}")


def _get(path: str, params: dict, timeout: int = 20) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310 — 고정 도메인
        return json.loads(r.read().decode("utf-8"))


def video_stats(key: str, ids) -> tuple:
    """(통계 행, 실패한 호출 수). 실패 수를 같이 돌려주는 이유는 backfill_reason 참고."""
    out, failed = [], 0
    for part in chunk_ids(ids):
        try:
            out += parse_video_stats(_get("videos", {
                "part": "statistics", "id": ",".join(part), "key": key}))
        except Exception as e:  # noqa: BLE001 — 한 묶음 실패가 전체를 막지 않는다
            failed += 1
            print(f"[yt_public] videos.list 실패({len(part)}건): {e}")
    return out, failed


def channel_avatars(key: str, ids) -> tuple:
    out, failed = [], 0
    for part in chunk_ids(ids):
        try:
            out += parse_channel_avatars(_get("channels", {
                "part": "snippet", "id": ",".join(part), "key": key}))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"[yt_public] channels.list 실패({len(part)}건): {e}")
    return out, failed
