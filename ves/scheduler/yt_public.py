#!/usr/bin/env python3
"""yt_public — YouTube Data API 공개 조회 (키 1개, 읽기 전용).

쓰는 곳 둘:
  · channels_sync — 채널 아이콘(avatar_url) 갱신 (0020)
  · perf_sync     — laeebly 수집 공백 채널의 영상 통계 직접 보완 (커리어데이 실측 8/11)
키는 brain .env 의 REACT_APP_YOUTUBE_API_KEY 를 재사용한다(구 대시보드와 같은 키).
쿼터: videos.list·channels.list 는 호출당 1유닛 · 50개씩 묶어 부른다 — 하루 수십 유닛.
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
    import os
    for n in KEY_NAMES:
        if os.environ.get(n):
            return os.environ[n]
    envp = pathlib.Path(cfgmod.engine_dir(cfg, "brain")) / ".env"
    try:
        for line in envp.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() in KEY_NAMES and v.strip():
                return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return None


def _get(path: str, params: dict, timeout: int = 20) -> dict:
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=timeout) as r:   # noqa: S310 — 고정 도메인
        return json.loads(r.read().decode("utf-8"))


def video_stats(key: str, ids) -> list:
    out = []
    for part in chunk_ids(ids):
        try:
            out += parse_video_stats(_get("videos", {
                "part": "statistics", "id": ",".join(part), "key": key}))
        except Exception as e:  # noqa: BLE001 — 한 묶음 실패가 전체를 막지 않는다
            print(f"[yt_public] videos.list 실패({len(part)}건): {e}")
    return out


def channel_avatars(key: str, ids) -> list:
    out = []
    for part in chunk_ids(ids):
        try:
            out += parse_channel_avatars(_get("channels", {
                "part": "snippet", "id": ",".join(part), "key": key}))
        except Exception as e:  # noqa: BLE001
            print(f"[yt_public] channels.list 실패({len(part)}건): {e}")
    return out
