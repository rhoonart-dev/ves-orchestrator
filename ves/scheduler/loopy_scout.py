#!/usr/bin/env python3
"""loopy_scout — 외부 채널 쇼츠·롱폼 아카이브 수집기 (L-P3, 2026-08-23).

발주서: docs/LOCALIZE_UNIFY.md §5-4·§5-5·§6-3.
사용자 지시(8/23): "잔망루피 쇼츠는 옛날 것부터 최신 것까지 주기적으로 자동 수집해서
가지고 있다가 사용할 수 있게."

vlp `src/scout.py` 를 **승격**한 것이다 — 무엇을·언제·어디서는 관제의 일이지 엔진의
일이 아니다(§0 원칙). 검증된 로직(UUSH 플레이리스트 트릭·ISO8601 파싱·쿼터 구분)은
그대로 옮기고, 달라진 것은 목적지(SQLite 원장 → PG `external_shorts`)와
**두 선반 분류**(길이로 short/longform)뿐이다.

## 왜 매일 전량을 다시 나열하는가

채널 전량(~1,100편)이 **46유닛** — 일일 무료 쿼터의 0.5% 다(playlistItems 50편당 1 +
videos.list 50편당 1 + channels 1). 증분만 받으면 **지표(조회수·좋아요)가 늙는다**.
아카이브는 목록이 아니라 "무엇이 일본에서 먹힐까"를 사람이 판단하는 자료라 지표가
살아 있어야 한다(§5-4).

## 안전

· 켜는 것은 사람이다 — `ops_config.loopy_scout.enabled` (기본 off).
· 수집은 **메타까지만**. 파일은 안 받는다(고른 편만 acquire 가 받는다).
· 실패해도 아카이브를 **비우지 않는다** — 빈 응답을 삭제로 오해하면 목록이 날아간다(§10-2).
· 발행 이력이 있는 행은 지표만 갱신하고 상태는 안 건드린다(0076 트리거가 한 번 더 막는다).
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

CONFIG_KEY = "loopy_scout"
API_BASE = "https://www.googleapis.com/youtube/v3"
SHORTS_MAX_SEC = 61.0          # 이보다 길면 롱폼 선반으로(§5-1 그림)
MIN_SEC = 3.0                  # 라이브 잔재·오류 항목 제외
API_BATCH = 50                 # playlistItems·videos.list 배치 상한

DEFAULTS = {"enabled": False, "channel_slug": "LOOPY", "handle": "@zanmangloopy",
            "max_scan": 0, "shorts_max_sec": SHORTS_MAX_SEC}

_DUR_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")
# 제목 정규화 — 해시태그는 **단어째** 걷어낸다(§5-7 1단계).
# ⚠ `#` 기호만 지우면 `루피 먹방 #shorts` 가 `루피먹방shorts` 가 되어 원본
#   `루피 먹방`(→`루피먹방`)과 안 맞는다. 해시태그는 내용이 아니라 메타데이터라
#   재업로드에서 붙었다 떨어졌다 하는 자리다 — 그걸로 중복을 놓치면 안 된다.
_HASHTAG = re.compile(r"#\S+")
_TITLE_STRIP = re.compile(r"[#\[\]()（）【】\s\-_·,.!?~…\"'`|/\\]+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")


class QuotaExceeded(RuntimeError):
    """일일 쿼터 소진 — 재시도 가능한 일시 장애(신호 부재와 구분한다)."""


# ───────── 순수 (테스트 대상) ─────────

def parse_iso8601_duration(s: str):
    """'PT1M3S' → 63.0, 'P0D' → 0.0. 라이브('P0D')·24h+ 도 파싱한다."""
    m = _DUR_RE.match(s or "")
    if not m or all(g is None for g in m.groups()):
        return None
    d, h, mi, sec = (int(g) if g else 0 for g in m.groups())
    return float(d * 86400 + h * 3600 + mi * 60 + sec)


def shorts_playlist_id(channel_id: str) -> str:
    """UC<suffix> → UUSH<suffix> (Shorts 전용 자동 플레이리스트 — 미문서화 트릭).

    2026-07 실측으로 잔망루피 채널 Shorts 탭과 동일 목록 확인. 404 면 UU(전체)로 폴백."""
    if not channel_id.startswith("UC"):
        raise ValueError(f"채널 ID 형식 아님(UC...): {channel_id}")
    return "UUSH" + channel_id[2:]


def classify_kind(duration, shorts_max_sec: float = SHORTS_MAX_SEC):
    """길이 → 선반. 수집기는 하나, 선반이 둘이다(§5-1).

    길이 미상은 None — 어느 선반에도 안 넣는다(fail-closed). 길이를 모르는 항목이
    쇼츠 아카이브에 섞이면 사람이 고른 뒤에야 규격 밖인 걸 안다."""
    if duration is None:
        return None
    if duration < MIN_SEC:
        return None
    return "short" if duration <= shorts_max_sec else "longform"


def normalize_title(title: str) -> str:
    """중복 판정용 제목 정규화 — 공백·기호·이모지·해시태그 제거 후 소문자. 순수.

    §5-7 1단계. 원 채널이 같은 내용을 새 id 로 다시 올리면 원장의 video_id 기준
    중복 판정이 통과해 **이미 올린 편을 또 올린다**."""
    t = _HASHTAG.sub(" ", title or "")
    t = _EMOJI.sub("", t)
    return _TITLE_STRIP.sub("", t).lower()


def find_duplicates(rows, tol_sec: float = 2.0) -> dict:
    """{video_id: 먼저 올라온 같은 내용의 video_id}. 순수 — 테스트 대상.

    판정: 정규화 제목 일치 **그리고** 길이 차 ≤ tol_sec(§5-7 1·2단계).
    ⚠ 자동으로 지우지 않는다 — 표시만 하고 사람이 뒤집을 수 있어야 한다(오탐이면
    소재 하나가 영영 사라진다). 썸네일 pHash(3단계)는 이미지 다운로드가 필요해 후속."""
    by_key: dict = {}
    out: dict = {}
    # 공개일 오름차순 — '먼저 올라온 것'이 원본이다. 공개일 미상은 뒤로.
    for r in sorted(rows, key=lambda x: (x.get("published_at") is None,
                                         x.get("published_at") or "")):
        vid, dur = r.get("video_id"), r.get("duration_sec")
        key = normalize_title(r.get("title") or "")
        if not vid or not key:
            continue
        hit = None
        for prev_vid, prev_dur in by_key.get(key, []):
            if dur is None or prev_dur is None:
                continue
            if abs(float(dur) - float(prev_dur)) <= tol_sec:
                hit = prev_vid
                break
        if hit:
            out[vid] = hit
        else:
            by_key.setdefault(key, []).append((vid, dur))
    return out


def merge_config(raw) -> dict:
    """ops_config 값 → 설정. 깨졌으면 기본값(수집이 안 돌 뿐 관제를 막지 않는다). 순수."""
    cfg = dict(DEFAULTS)
    try:
        if raw:
            got = json.loads(raw)
            if isinstance(got, dict):
                cfg.update({k: v for k, v in got.items() if k in DEFAULTS})
    except ValueError:
        pass
    return cfg


# ───────── YouTube Data API ─────────

def _api_get(endpoint: str, params: dict, api_key: str) -> dict:
    q = dict(params, key=api_key)
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:                                  # noqa: BLE001
            pass
        if e.code == 403 and "quotaExceeded" in body:
            raise QuotaExceeded(f"YouTube API 쿼터 소진 ({endpoint})") from e
        raise


def resolve_channel_id(handle: str, api_key: str) -> str:
    data = _api_get("channels", {"part": "id", "forHandle": handle}, api_key)
    items = data.get("items", [])
    if not items:
        raise ValueError(f"채널을 찾을 수 없음: {handle}")
    return items[0]["id"]


def list_playlist_video_ids(playlist_id: str, api_key: str, max_scan: int = 0) -> list:
    ids: list = []
    token = None
    while True:
        params = {"part": "contentDetails", "playlistId": playlist_id,
                  "maxResults": API_BATCH}
        if token:
            params["pageToken"] = token
        data = _api_get("playlistItems", params, api_key)
        ids += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
        token = data.get("nextPageToken")
        if not token or (max_scan and len(ids) >= max_scan):
            break
    return ids[:max_scan] if max_scan else ids


def videos_stats(video_ids: list, api_key: str) -> list:
    rows = []
    for i in range(0, len(video_ids), API_BATCH):
        data = _api_get("videos", {"part": "snippet,contentDetails,statistics",
                                   "id": ",".join(video_ids[i:i + API_BATCH])}, api_key)
        for it in data.get("items", []):
            st = it.get("statistics", {})
            sn = it.get("snippet", {})
            thumbs = sn.get("thumbnails") or {}
            best = thumbs.get("maxres") or thumbs.get("high") or thumbs.get("default") or {}
            rows.append({
                "video_id": it["id"],
                "title": sn.get("title", ""),
                "published_at": sn.get("publishedAt"),
                "thumbnail_url": best.get("url"),
                "duration_sec": parse_iso8601_duration(
                    it.get("contentDetails", {}).get("duration", "")),
                "view_count": int(st["viewCount"]) if "viewCount" in st else None,
                "like_count": int(st["likeCount"]) if "likeCount" in st else None,
                "comment_count": int(st["commentCount"]) if "commentCount" in st else None,
                "url": f"https://www.youtube.com/shorts/{it['id']}",
            })
    return rows


# ───────── 실행부 ─────────

def _cfg(conn) -> dict:
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key=%s", (CONFIG_KEY,))
        row = c.fetchone()
    return merge_config((row or {}).get("value"))


def _api_key(cfg) -> str | None:
    import os
    from ves import config as cfgmod
    try:
        merged = cfgmod.file_env()          # /etc/ves/node.env + $VES_HOME/secrets/ves.env
    except Exception:                                      # noqa: BLE001
        merged = {}
    return os.environ.get("YOUTUBE_API_KEY") or merged.get("YOUTUBE_API_KEY")


def upsert_rows(conn, channel_slug: str, handle: str, rows: list,
                shorts_max_sec: float) -> tuple[int, int]:
    """아카이브 upsert. (신규, 갱신) 건수.

    ⚠ **지표만 갱신하고 상태는 안 건드린다.** state·score·발행 이력은 선별기·발행이
    쓰는 자리다 — 수집기가 덮으면 이미 고른 편이 되돌아간다."""
    dups = find_duplicates(rows)
    new = upd = 0
    with conn.cursor() as c:
        for r in rows:
            kind = classify_kind(r.get("duration_sec"), shorts_max_sec)
            if kind is None:
                continue                       # 길이 미상·너무 짧음 — 선반에 안 넣는다
            c.execute("""
                INSERT INTO public.external_shorts
                    (video_id, channel_slug, source_handle, title, url, thumbnail_url,
                     duration_sec, view_count, like_count, comment_count,
                     published_at, kind, dup_of)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (video_id) DO UPDATE SET
                    title         = EXCLUDED.title,
                    url           = EXCLUDED.url,
                    thumbnail_url = EXCLUDED.thumbnail_url,
                    duration_sec  = EXCLUDED.duration_sec,
                    view_count    = EXCLUDED.view_count,
                    like_count    = EXCLUDED.like_count,
                    comment_count = EXCLUDED.comment_count,
                    published_at  = COALESCE(EXCLUDED.published_at,
                                             public.external_shorts.published_at),
                    kind          = EXCLUDED.kind,
                    dup_of        = COALESCE(public.external_shorts.dup_of, EXCLUDED.dup_of)
                RETURNING (xmax = 0) AS inserted
            """, (r["video_id"], channel_slug, handle, r.get("title"), r.get("url"),
                  r.get("thumbnail_url"), r.get("duration_sec"), r.get("view_count"),
                  r.get("like_count"), r.get("comment_count"), r.get("published_at"),
                  kind, dups.get(r["video_id"])))
            got = c.fetchone()
            if got and got.get("inserted"):
                new += 1
            else:
                upd += 1
    return new, upd


def run(conn, cfg):
    conf = _cfg(conn)
    if not conf.get("enabled"):
        return          # 스위치 off — 사람이 켠다(ops_config.loopy_scout)
    api_key = _api_key(cfg)
    if not api_key:
        print("[loopy_scout] YOUTUBE_API_KEY 없음 — 수집 건너뜀(ves.env 확인)")
        return

    handle = conf["handle"]
    slug = conf["channel_slug"]
    max_scan = int(conf.get("max_scan") or 0)
    try:
        cid = resolve_channel_id(handle, api_key)
        try:
            vids = list_playlist_video_ids(shorts_playlist_id(cid), api_key, max_scan)
            print(f"[loopy_scout] UUSH 쇼츠 플레이리스트 {len(vids)}편")
        except Exception as e:                             # noqa: BLE001 — UUSH 미지원 폴백
            print(f"[loopy_scout] UUSH 실패({e}) → 전체 업로드(UU)에서 길이로 분류")
            vids = list_playlist_video_ids("UU" + cid[2:], api_key, max_scan)
        rows = videos_stats(vids, api_key)
    except QuotaExceeded as e:
        # 일시 장애 — **아카이브를 비우지 않는다**(빈 응답을 삭제로 오해하면 목록이 날아간다)
        print(f"[loopy_scout] {e} — 이번 주기 보류(기존 아카이브 유지)")
        return
    except Exception as e:                                 # noqa: BLE001
        print(f"[loopy_scout] 수집 실패(기존 아카이브 유지): {type(e).__name__} {e}")
        return

    new, upd = upsert_rows(conn, slug, handle, rows,
                           float(conf.get("shorts_max_sec") or SHORTS_MAX_SEC))
    shorts = sum(1 for r in rows
                 if classify_kind(r.get("duration_sec")) == "short")
    print(f"[loopy_scout] {slug} 아카이브 — 수집 {len(rows)}편"
          f"(쇼츠 {shorts} · 롱폼 {len(rows) - shorts}) · 신규 {new} · 갱신 {upd}")
