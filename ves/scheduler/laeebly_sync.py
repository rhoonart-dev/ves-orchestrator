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
        "geo_block_regions", "geo_block_mode", "company", "download_link", "inspection_policy")
# 권리사 검수(0117) — VES 채널 것만
INSP_COLS = ("id", "channel_id", "youtube_channel_id", "channel_name", "video_title", "company", "episode", "episode_part",
             "round", "status", "revision_notes", "remarks", "created_at", "updated_at", "reviewed_at", "respond_by",
             "revision_outcome", "auto_approved_at", "supersedes_inspection_id", "revision_items", "youtube_url",
             "file_link", "original_file_url", "published_youtube_url")
APP_COLS = ("id", "channel_id", "video_id", "status", "rejected_bool", "rh_verdict", "youtube_channel_id",
            "channel_title", "work_title")


# ───────── 순수 (테스트 대상) ─────────
def plan(source: list, mirror: dict, cols=COLS) -> tuple:
    """(쓸 행들, 지울 id들). mirror: id → 행(cols). 같은 내용이면 건너뛴다."""
    ids = set()
    writes = []
    for r in source:
        rid = str(r.get("id") or "")
        if not rid or ("title" in cols and not r.get("title")):
            continue
        ids.add(rid)
        row = {k: r.get(k) for k in cols}
        row["id"] = rid
        old = mirror.get(rid)
        if old is None or any(old.get(k) != row[k] for k in cols):
            writes.append(row)
    return writes, sorted(set(mirror) - ids)


def newly_approved(apps: list, old_status: dict) -> list:
    """이번 동기화에서 새로 '사용 승인'이 된 신청 → [(유튜브 채널 id, 작품명)]. 순수.
    전에 없던 신청이 이미 승인 상태로 들어와도 새 승인으로 본다. 반려(rejected_bool)는 뺀다."""
    out = []
    for a in apps:
        if a.get("status") is True and not a.get("rejected_bool") and a.get("work_title") and a.get("youtube_channel_id"):
            if old_status.get(str(a.get("id"))) is not True:
                out.append((a["youtube_channel_id"], a["work_title"]))
    return sorted(set(out))


def add_works(works: list | None, work: str) -> list | None:
    """채널 생성 대상 작품 목록에 작품 하나를 더한다(이미 있으면 None — 바꿀 것 없음). 순수."""
    cur = list(works or [])
    return None if work in cur else cur + [work]


# ───────── 실행부 ─────────
def _mirror(conn, table, cols, source) -> tuple:
    """source → public.<table> 에 바뀐 것만 쓰고 없어진 것은 지운다. (바뀜, 지움)"""
    from psycopg.types.json import Jsonb
    with conn.cursor() as c:
        c.execute(f"SELECT {', '.join(cols)} FROM public.{table}")
        mirror = {r["id"]: dict(r) for r in c.fetchall()}
    writes, deletes = plan(source, mirror, cols)
    now = dt.datetime.now(dt.timezone.utc)
    with conn.cursor() as c:
        for row in writes:
            vals = [Jsonb(row[k]) if isinstance(row[k], (dict, list)) and k != "geo_block_regions" else row[k] for k in cols]
            c.execute(
                f"""INSERT INTO public.{table} ({', '.join(cols)}, synced_at)
                    VALUES ({', '.join(['%s'] * len(cols))}, %s)
                    ON CONFLICT (id) DO UPDATE SET {', '.join(f'{k}=EXCLUDED.{k}' for k in cols if k != 'id')},
                        synced_at=EXCLUDED.synced_at""", (*vals, now))
        if deletes:
            c.execute(f"DELETE FROM public.{table} WHERE id = ANY(%s)", (deletes,))
        # 아무것도 안 바뀌어도 '언제 맞췄는지'는 남긴다(화면의 기준 시각)
        c.execute(f"UPDATE public.{table} SET synced_at = %s WHERE id = (SELECT id FROM public.{table} LIMIT 1)", (now,))
    return len(writes), len(deletes)


def _laeebly(cfg, sql, args=()):
    from ves.db import connect
    lae = connect(cfg.laeebly_url)
    try:
        with lae.cursor() as c:
            c.execute(sql, args)
            return [dict(r) for r in c.fetchall()]
    finally:
        lae.close()


def run(conn, cfg):
    """작품 정보(10분마다)."""
    if not cfg.laeebly_url:
        print("[laeebly_sync] 레이블리 연결 없음 — 건너뜀")
        return 0
    source = _laeebly(cfg, f"SELECT {', '.join(COLS)} FROM licensed_video")
    w, d = _mirror(conn, "laeebly_works", COLS, source)
    print(f"[laeebly_sync] 작품 {len(source)} · 바뀜 {w} · 지움 {d}")
    return w


def run_inspections(conn, cfg):
    """권리사 검수 · 작품 사용 신청(2분마다) — VES 채널(channels_mirror) 것만."""
    if not cfg.laeebly_url:
        return 0
    with conn.cursor() as c:
        c.execute("SELECT channel_id FROM public.channels_mirror WHERE channel_id IS NOT NULL")
        ids = [r["channel_id"] for r in c.fetchall()]
    insp = _laeebly(cfg, f"""SELECT {', '.join('i.' + k for k in INSP_COLS if k != 'youtube_channel_id')},
                                    c.channel_id AS youtube_channel_id
                               FROM public.video_inspection i JOIN public.channel c ON c.id = i.channel_id
                              WHERE c.channel_id = ANY(%s) AND c.deleted_at IS NULL""", (ids,))
    apps = _laeebly(cfg, """SELECT a.id, a.channel_id, a.video_id, a.status, a.rejected_bool, a.rh_verdict,
                                   c.channel_id AS youtube_channel_id, c.channel_title, l.title AS work_title
                              FROM public.channel_to_video a JOIN public.channel c ON c.id = a.channel_id
                              LEFT JOIN public.licensed_video l ON l.id = a.video_id
                             WHERE c.channel_id = ANY(%s) AND c.deleted_at IS NULL""", (ids,))
    with conn.cursor() as c:
        c.execute("SELECT id, status FROM public.laeebly_applications")
        old_status = {r["id"]: r["status"] for r in c.fetchall()}
    wi, di = _mirror(conn, "laeebly_inspections", INSP_COLS, insp)
    wa, da = _mirror(conn, "laeebly_applications", APP_COLS, apps)
    for ych, work in newly_approved(apps, old_status):
        auto_add_channel_work(conn, ych, work)
    if wi or di or wa or da:
        print(f"[laeebly_sync] 검수 {len(insp)}(바뀜 {wi}·지움 {di}) · 사용 신청 {len(apps)}(바뀜 {wa}·지움 {da})")
    return wi + wa


def auto_add_channel_work(conn, youtube_channel_id: str, work: str) -> bool:
    """레이블리에서 사용 승인이 나면 그 채널의 생성 대상 작품에 자동으로 더한다(2026-10-02 사용자 요청).
    채널이 이미 정해 둔 목록(channel_works_overrides)이 있으면 그 목록에 하나만 더하고, 없으면 기본 목록(channels_mirror.works)에 더해 저장한다.
    빼 둔 작품을 되살리지는 않는다 — 새로 승인된 그 작품만. 승인이 바뀌는 순간 한 번만 불리므로, 사람이 나중에 뺀 작품은 그대로 빠져 있다."""
    with conn.cursor() as c:
        c.execute("""SELECT m.token_slug, m.name, coalesce(o.works, m.works) AS works
                       FROM public.channels_mirror m LEFT JOIN public.channel_works_overrides o ON o.token_slug = m.token_slug
                      WHERE m.channel_id = %s""", (youtube_channel_id,))
        row = c.fetchone()
        if not row:
            return False
        nxt = add_works(row["works"], work)
        if nxt is None:
            return False
        c.execute("""INSERT INTO public.channel_works_overrides(token_slug, works, updated_by, updated_at)
                     VALUES (%s, %s, 'laeebly_sync(사용 승인)', now())
                     ON CONFLICT (token_slug) DO UPDATE SET works = EXCLUDED.works, updated_by = EXCLUDED.updated_by, updated_at = now()""",
                  (row["token_slug"], nxt))
    print(f"[laeebly_sync] 사용 승인 → {row['name']} 생성 대상 작품에 '{work}' 추가")
    return True
