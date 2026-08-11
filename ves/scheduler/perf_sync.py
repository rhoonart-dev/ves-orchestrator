#!/usr/bin/env python3
"""perf_sync — laeebly youtube_*_snapshot → 관제 성과 미러 (0015, 매시간).

laeebly 는 권리·성과의 정본이고 계속 읽기 전용이다(§2). 관제(브라우저)는 laeebly 에
닿을 수 없으므로, 우리 채널(channels_mirror.channel_id)분만 fdidiqd 로 복사해
성과 탭이 RLS 아래에서 직접 SELECT 하게 한다. 창: 스냅샷 35일·영상 180일(신선도 우선).
"""
from __future__ import annotations

SNAP_DAYS = 35     # 스냅샷 보존·복사 창 — 28일 지표 + 여유
VIDEO_DAYS = 180   # 영상 목록 창(published_at 기준) — 성과 탭 목록 범위


def chunks(seq, n=200):
    """IN 절 안전 분할. 순수 — 테스트 대상."""
    seq = list(seq)
    return [seq[i:i + n] for i in range(0, len(seq), n)] if seq else []


def run(conn, cfg):
    if not cfg.laeebly_url:
        print("[perf_sync] laeebly_url 없음 — 건너뜀")
        return
    with conn.cursor() as c:
        c.execute("SELECT channel_id FROM public.channels_mirror WHERE channel_id IS NOT NULL")
        ch_ids = [r["channel_id"] for r in c.fetchall()]
    if not ch_ids:
        print("[perf_sync] channels_mirror 에 channel_id 없음 — 건너뜀")
        return

    from ves.db import connect
    lae = connect(cfg.laeebly_url)
    try:
        with lae.cursor() as c:
            c.execute(
                """SELECT content_id, channel_id, title, licensed_video_title,
                          published_at, dead_at
                     FROM youtube_video_map
                    WHERE channel_id = ANY(%s)
                      AND published_at > now() - make_interval(days => %s)""",
                (ch_ids, VIDEO_DAYS))
            vmap = c.fetchall()
        cids = [v["content_id"] for v in vmap]
        vsnap = []
        for part in chunks(cids):
            with lae.cursor() as c:
                c.execute(
                    """SELECT content_id, snapshot_date, view_count, like_count, comment_count
                         FROM youtube_video_snapshot
                        WHERE content_id = ANY(%s)
                          AND snapshot_date > current_date - %s""",
                    (part, SNAP_DAYS))
                vsnap.extend(c.fetchall())
        with lae.cursor() as c:
            c.execute(
                """SELECT channel_id, snapshot_date, subscriber_count, view_count, video_count
                     FROM youtube_channel_snapshot
                    WHERE channel_id = ANY(%s) AND snapshot_date > current_date - %s""",
                (ch_ids, SNAP_DAYS))
            csnap = c.fetchall()
    finally:
        lae.close()

    with conn.cursor() as c:
        for v in vmap:
            c.execute(
                """INSERT INTO public.perf_video_map
                       (content_id, channel_id, title, work_title, published_at, dead_at, synced_at)
                   VALUES (%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (content_id) DO UPDATE SET
                       channel_id=EXCLUDED.channel_id, title=EXCLUDED.title,
                       work_title=EXCLUDED.work_title, published_at=EXCLUDED.published_at,
                       dead_at=EXCLUDED.dead_at, synced_at=now()""",
                (v["content_id"], v["channel_id"], v["title"],
                 v["licensed_video_title"], v["published_at"], v["dead_at"]))
        for s in vsnap:
            c.execute(
                """INSERT INTO public.perf_video_snapshot
                       (content_id, snapshot_date, view_count, like_count, comment_count)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (content_id, snapshot_date) DO UPDATE SET
                       view_count=EXCLUDED.view_count, like_count=EXCLUDED.like_count,
                       comment_count=EXCLUDED.comment_count""",
                (s["content_id"], s["snapshot_date"], s["view_count"],
                 s["like_count"], s["comment_count"]))
        for s in csnap:
            c.execute(
                """INSERT INTO public.perf_channel_snapshot
                       (channel_id, snapshot_date, subscriber_count, view_count, video_count)
                   VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (channel_id, snapshot_date) DO UPDATE SET
                       subscriber_count=EXCLUDED.subscriber_count,
                       view_count=EXCLUDED.view_count, video_count=EXCLUDED.video_count""",
                (s["channel_id"], s["snapshot_date"], s["subscriber_count"],
                 s["view_count"], s["video_count"]))
        # 창 밖 정리(테이블 비대 방지)
        c.execute("DELETE FROM public.perf_video_snapshot WHERE snapshot_date < current_date - %s",
                  (SNAP_DAYS + 5,))
        c.execute("DELETE FROM public.perf_channel_snapshot WHERE snapshot_date < current_date - %s",
                  (SNAP_DAYS + 5,))
    print(f"[perf_sync] 영상 {len(vmap)} · 영상스냅 {len(vsnap)} · 채널스냅 {len(csnap)} 미러됨")
    backfill_missing(conn, cfg)


def backfill_missing(conn, cfg) -> int:
    """laeebly 수집 공백 보완(8/11 실측: 커리어데이 숏츠는 원천에 영상 통계가 0행).
    오늘치 스냅샷이 없는 우리 영상만 YouTube 공개 API 로 직접 받아 채운다 —
    laeebly 가 채워주면 같은 (content_id, 날짜) 키로 덮여 자연히 일원화된다."""
    from ves.scheduler import yt_public
    with conn.cursor() as c:
        c.execute("""SELECT m.content_id FROM public.perf_video_map m
                      WHERE m.dead_at IS NULL
                        AND NOT EXISTS (SELECT 1 FROM public.perf_video_snapshot s
                                         WHERE s.content_id = m.content_id
                                           AND s.snapshot_date = current_date)
                      LIMIT 300""")
        ids = [r["content_id"] for r in c.fetchall()]
    if not ids:
        return 0
    key = yt_public.api_key(cfg)
    if not key:
        print(f"[perf_sync] 오늘 스냅샷 없는 영상 {len(ids)}건 — YouTube API 키 없어 보완 생략")
        return 0
    rows = yt_public.video_stats(key, ids)
    with conn.cursor() as c:
        for cid, views, likes, comments in rows:
            c.execute(
                """INSERT INTO public.perf_video_snapshot
                       (content_id, snapshot_date, view_count, like_count, comment_count)
                   VALUES (%s, current_date, %s, %s, %s)
                   ON CONFLICT (content_id, snapshot_date) DO UPDATE SET
                       view_count=EXCLUDED.view_count, like_count=EXCLUDED.like_count,
                       comment_count=EXCLUDED.comment_count""",
                (cid, views, likes, comments))
    print(f"[perf_sync] 직접 보완 {len(rows)}/{len(ids)}건(YouTube API)")
    return len(rows)
