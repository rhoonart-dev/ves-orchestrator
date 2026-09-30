#!/usr/bin/env python3
"""laeebly_sync — 레이블리 작품 DB(licensed_video) → laeebly_works(읽기 사본) (0116).

워크스페이스 작품 관리를 웹 주소에서도 쓰기 위한 사본이다. 레이블리 접속 정보는 스케줄러 노드에만 두고,
브라우저는 Supabase 의 이 표만 읽는다. 정본은 레이블리 — 레이블리에 없는 행은 지운다(channels_sync 와 같은 규칙).
바뀐 행만 쓴다(guide 가 길어 매번 통째로 쓰면 낭비).
"""
from __future__ import annotations

import datetime as dt

COLS = ("id", "title", "video_type", "thumbnail", "guide", "identification_code", "required_hashtags_title",
        "required_hashtags_description", "required_hashtags_notice", "copyrights_holder_name", "geo_block_required",
        "geo_block_regions", "geo_block_mode", "company", "download_link")


# ───────── 순수 (테스트 대상) ─────────
def plan(source: list, mirror: dict) -> tuple:
    """(쓸 행들, 지울 id들). mirror: id → 행(COLS). 같은 내용이면 건너뛴다."""
    ids = set()
    writes = []
    for r in source:
        rid = str(r.get("id") or "")
        if not rid or not r.get("title"):
            continue
        ids.add(rid)
        row = {k: r.get(k) for k in COLS}
        row["id"] = rid
        old = mirror.get(rid)
        if old is None or any(old.get(k) != row[k] for k in COLS):
            writes.append(row)
    return writes, sorted(set(mirror) - ids)


# ───────── 실행부 ─────────
def run(conn, cfg):
    if not cfg.laeebly_url:
        print("[laeebly_sync] 레이블리 연결 없음 — 건너뜀")
        return 0
    from ves.db import connect
    lae = connect(cfg.laeebly_url)
    try:
        with lae.cursor() as c:
            c.execute(f"SELECT {', '.join(COLS)} FROM licensed_video")
            source = [dict(r) for r in c.fetchall()]
    finally:
        lae.close()
    with conn.cursor() as c:
        c.execute(f"SELECT {', '.join(COLS)} FROM public.laeebly_works")
        mirror = {r["id"]: dict(r) for r in c.fetchall()}
    writes, deletes = plan(source, mirror)
    now = dt.datetime.now(dt.timezone.utc)
    with conn.cursor() as c:
        for row in writes:
            c.execute(
                f"""INSERT INTO public.laeebly_works ({', '.join(COLS)}, synced_at)
                    VALUES ({', '.join(['%s'] * len(COLS))}, %s)
                    ON CONFLICT (id) DO UPDATE SET {', '.join(f'{k}=EXCLUDED.{k}' for k in COLS if k != 'id')},
                        synced_at=EXCLUDED.synced_at""",
                (*[row[k] for k in COLS], now))
        if deletes:
            c.execute("DELETE FROM public.laeebly_works WHERE id = ANY(%s)", (deletes,))
    print(f"[laeebly_sync] 작품 {len(source)} · 바뀜 {len(writes)} · 지움 {len(deletes)}")
    return len(writes)
