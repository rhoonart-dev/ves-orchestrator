#!/usr/bin/env python3
"""perf_sync — laeebly youtube_*_snapshot → 관제 성과 미러 (0015, 매시간).

laeebly 는 권리·성과의 정본이고 계속 읽기 전용이다(§2). 관제(브라우저)는 laeebly 에
닿을 수 없으므로, 우리 채널(channels_mirror.channel_id)분만 fdidiqd 로 복사해
성과 탭이 RLS 아래에서 직접 SELECT 하게 한다.

0097 부터 **깔때기**(`youtube_studio` → `perf_studio_daily`)도 같이 미러한다 — 노출·CTR·
완주율이다. 조회수만으로는 "조회 0" 이 배포 실패인지 콘텐츠 실패인지 갈리지 않는다
(docs/TREND_REPORT.md §1). 알갱이가 다르니 테이블을 따로 둔다 — 영상 스냅샷은 **누적**,
깔때기는 **그날치 증분**이다.

창은 둘로 나뉜다 — **복사 창**(매시간 다시 읽는 최근 며칠)과 **보존 창**(미러에 남기는 기간).
지난 스냅샷은 원천에서도 더 바뀌지 않으므로 매시간 다시 읽을 이유가 없다. 대신 오래
보관해야 성과 탭에서 긴 기간을 고를 수 있다. 미러에 과거 구멍이 있으면(첫 회전이거나
보존 창을 늘린 직후) 원천이 가진 데까지 한 번에 메운다.
"""
from __future__ import annotations

from datetime import timedelta

COPY_DAYS = 7      # 매시간 다시 읽는 창 — 최근분만 갱신된다
KEEP_DAYS = 120    # 미러 보존 창 — 성과 탭 기간 선택의 상한
VIDEO_DAYS = 180   # 영상 목록 창(published_at 기준) — 성과 탭 목록 범위

# 깔때기 원천(0097).
#
# ## 날짜 축은 upload_at 이다 — created_at 이 아니다
#
# `upload_at` 은 **그 통계가 어느 날짜의 것인지**이고 `created_at` 은 **언제 수집했는지**다.
# 하루에 여러 날짜분을 몰아 넣는 날이 있어 둘이 갈린다 — 8/15 실측: 06:19 수집분은
# 8/10 자(노출 107), 16:35 수집분은 8/11 자(노출 135)다. 같은 날 재보고가 아니라
# **서로 다른 날의 증분**이라 둘 다 넣어야 맞다. `(content_id, upload_at)` 은 유일하다
# (B급 순삭 8월 파티션 1,779행 = 1,779키 실측) — 그래서 중복 제거가 필요 없다.
#
# ## upload_at 으로 걸러야 파티션이 잘린다
#
# `youtube_studio` 는 RANGE (upload_at) 월별 파티션이다. `created_at` 으로 거르면
# 프루닝이 안 돼 전 파티션(2025-01~)을 훑는다 — 실측에서 질의가 응답하지 못했다.
#
# · video_length 는 varchar 다. 관측값은 '25.0' 같은 초 단위 실수 문자열이지만
#   형식이 어긋난 값이 오면 캐스팅이 통째로 죽으므로 정규식으로 거른다(맞지 않으면 NULL).
# · publish_time 은 naive 다. laeebly 는 KST 로 쓴다(created_at 이 +09) — 그렇게 읽는다.
STUDIO_SQL = """
    SELECT content_id,
           (upload_at AT TIME ZONE 'Asia/Seoul')::date AS stat_date,
           channel_id,
           licensed_video_title AS work_title,
           video_title,
           publish_time AT TIME ZONE 'Asia/Seoul' AS publish_time,
           CASE WHEN video_length ~ '^[0-9]+(\\.[0-9]+)?$'
                THEN video_length::numeric END AS video_length,
           impressions,
           impression_click_rate AS ctr,
           views, valid_views,
           average_view_percentage AS view_pct,
           kept_watching_rate AS kept_rate,
           watch_time_hours AS watch_hours,
           subscribers, likes, shares, comments_added AS comments
      FROM youtube_studio
     WHERE channel_id = ANY(%s)
       AND upload_at >= (%s::date AT TIME ZONE 'Asia/Seoul')
"""

STUDIO_COLS = ("content_id", "stat_date", "channel_id", "work_title", "video_title",
               "publish_time", "video_length", "impressions", "ctr", "views",
               "valid_views", "view_pct", "kept_rate", "watch_hours",
               "subscribers", "likes", "shares", "comments")


def chunks(seq, n=200):
    """IN 절 안전 분할. 순수 — 테스트 대상."""
    seq = list(seq)
    return [seq[i:i + n] for i in range(0, len(seq), n)] if seq else []


# 깔때기 미러의 원천 하한 질의. copy_since 의 src_min 재료 — upload_at 범위를
# **명시해서** 묻는다. 무제한 min() 은 RANGE(upload_at) 전 파티션(2025-01~)을 훑는다.
STUDIO_SRC_MIN_SQL = """
    SELECT min((upload_at AT TIME ZONE 'Asia/Seoul'))::date AS mn
      FROM youtube_studio
     WHERE channel_id = ANY(%s)
       AND upload_at >= ((current_date - %s)::date AT TIME ZONE 'Asia/Seoul')
"""


def copy_since(mirror_min, src_min, today, keep_days=KEEP_DAYS, copy_days=COPY_DAYS):
    """이번 회전에 어느 날짜부터 복사할지. 순수 — 테스트 대상.

    평시엔 최근 copy_days 만 다시 읽는다. 미러가 비었거나 원천이 미러보다 과거를 더
    갖고 있으면(보존 창 안에서) 그 지점까지 넓혀 한 번에 메운다 — 메우고 나면 다음
    회전부터 다시 평시 창으로 돌아온다(원천에 없는 과거를 매시간 다시 긁지 않는다)."""
    recent = today - timedelta(days=copy_days)
    if src_min is None:
        return recent
    want = max(today - timedelta(days=keep_days), src_min)
    return want if (mirror_min is None or mirror_min > want) else recent


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

    with conn.cursor() as c:
        c.execute("SELECT current_date AS d, min(snapshot_date) AS mn "
                  "FROM public.perf_video_snapshot")
        r = c.fetchone()
        today, mirror_min = r["d"], r["mn"]

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
            # 원천이 어디까지 거슬러 갖고 있는지 — 미러의 과거 구멍을 메울지 판단한다
            c.execute("""SELECT min(snapshot_date) AS mn FROM youtube_video_snapshot
                          WHERE snapshot_date > current_date - %s""", (KEEP_DAYS,))
            src_min = c.fetchone()["mn"]
        since = copy_since(mirror_min, src_min, today)
        cids = [v["content_id"] for v in vmap]
        vsnap = []
        for part in chunks(cids):
            with lae.cursor() as c:
                c.execute(
                    """SELECT content_id, snapshot_date, view_count, like_count, comment_count
                         FROM youtube_video_snapshot
                        WHERE content_id = ANY(%s) AND snapshot_date >= %s""",
                    (part, since))
                vsnap.extend(c.fetchall())
        with lae.cursor() as c:
            c.execute(
                """SELECT channel_id, snapshot_date, subscriber_count, view_count, video_count
                     FROM youtube_channel_snapshot
                    WHERE channel_id = ANY(%s) AND snapshot_date >= %s""",
                (ch_ids, since))
            csnap = c.fetchall()

        # 깔때기(노출·CTR·완주율) — 0097. 영상 스냅샷과 **같은 창 규율**(copy_since)을 쓴다:
        # 미러 앞쪽에 구멍이 있으면 원천이 가진 데까지 한 번에 메우고, 평시엔 최근 창만.
        # ⚠ max(stat_date) 로 '비었나'만 보던 종전 로직의 사고(8/26 실측): 검증 데이터
        # 7행(8/19~22)이 먼저 들어가 있자 첫 회전이 평시 창으로 진입해 120일 대신 나흘만
        # 적재했고, 앞쪽 구멍(~8/18)은 영영 메워지지 않았다. 구멍은 min 으로만 보인다.
        with conn.cursor() as c:
            c.execute("SELECT min(stat_date) AS mn FROM public.perf_studio_daily")
            studio_mirror_min = c.fetchone()["mn"]
        with lae.cursor() as c:
            c.execute(STUDIO_SRC_MIN_SQL, (ch_ids, KEEP_DAYS))
            studio_src_min = c.fetchone()["mn"]
        studio_from = copy_since(studio_mirror_min, studio_src_min, today)
        studio = []
        for part in chunks(ch_ids):
            with lae.cursor() as c:
                c.execute(STUDIO_SQL, (part, studio_from))
                studio.extend(c.fetchall())
    finally:
        lae.close()

    with conn.cursor() as c:
        c.executemany(
            """INSERT INTO public.perf_video_map
                   (content_id, channel_id, title, work_title, published_at, dead_at, synced_at)
               VALUES (%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT (content_id) DO UPDATE SET
                   channel_id=EXCLUDED.channel_id, title=EXCLUDED.title,
                   work_title=EXCLUDED.work_title, published_at=EXCLUDED.published_at,
                   dead_at=EXCLUDED.dead_at, synced_at=now()""",
            [(v["content_id"], v["channel_id"], v["title"],
              v["licensed_video_title"], v["published_at"], v["dead_at"]) for v in vmap])
        c.executemany(
            """INSERT INTO public.perf_video_snapshot
                   (content_id, snapshot_date, view_count, like_count, comment_count)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (content_id, snapshot_date) DO UPDATE SET
                   view_count=EXCLUDED.view_count, like_count=EXCLUDED.like_count,
                   comment_count=EXCLUDED.comment_count""",
            [(s["content_id"], s["snapshot_date"], s["view_count"],
              s["like_count"], s["comment_count"]) for s in vsnap])
        c.executemany(
            """INSERT INTO public.perf_channel_snapshot
                   (channel_id, snapshot_date, subscriber_count, view_count, video_count)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (channel_id, snapshot_date) DO UPDATE SET
                   subscriber_count=EXCLUDED.subscriber_count,
                   view_count=EXCLUDED.view_count, video_count=EXCLUDED.video_count""",
            [(s["channel_id"], s["snapshot_date"], s["subscriber_count"],
              s["view_count"], s["video_count"]) for s in csnap])
        c.executemany(
            """INSERT INTO public.perf_studio_daily
                   (content_id, stat_date, channel_id, work_title, video_title,
                    publish_time, video_length, impressions, ctr, views, valid_views,
                    view_pct, kept_rate, watch_hours, subscribers, likes, shares,
                    comments, synced_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT (content_id, stat_date) DO UPDATE SET
                   channel_id=EXCLUDED.channel_id, work_title=EXCLUDED.work_title,
                   video_title=EXCLUDED.video_title, publish_time=EXCLUDED.publish_time,
                   video_length=EXCLUDED.video_length, impressions=EXCLUDED.impressions,
                   ctr=EXCLUDED.ctr, views=EXCLUDED.views, valid_views=EXCLUDED.valid_views,
                   view_pct=EXCLUDED.view_pct, kept_rate=EXCLUDED.kept_rate,
                   watch_hours=EXCLUDED.watch_hours, subscribers=EXCLUDED.subscribers,
                   likes=EXCLUDED.likes, shares=EXCLUDED.shares, comments=EXCLUDED.comments,
                   synced_at=now()""",
            [tuple(r[k] for k in STUDIO_COLS) for r in studio])
        # 보존 창 밖 정리(테이블 비대 방지)
        c.execute("DELETE FROM public.perf_video_snapshot WHERE snapshot_date < current_date - %s",
                  (KEEP_DAYS,))
        c.execute("DELETE FROM public.perf_channel_snapshot WHERE snapshot_date < current_date - %s",
                  (KEEP_DAYS,))
        c.execute("DELETE FROM public.perf_studio_daily WHERE stat_date < current_date - %s",
                  (KEEP_DAYS,))
    print(f"[perf_sync] {since} 이후 복사 — 영상 {len(vmap)} · 영상스냅 {len(vsnap)} "
          f"· 채널스냅 {len(csnap)} · 깔때기 {len(studio)}({studio_from} 이후) 미러됨")
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
        yt_public.note_status(conn, "perf_backfill_status", "ok", 0, 0)
        return 0
    key = yt_public.api_key(cfg)
    if not key:
        print(f"[perf_sync] 오늘 스냅샷 없는 영상 {len(ids)}건 — YouTube API 키 없어 보완 생략")
        yt_public.note_status(conn, "perf_backfill_status", "api_key_missing", len(ids), 0)
        return 0
    rows, failed = yt_public.video_stats(key, ids)
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
    yt_public.note_status(conn, "perf_backfill_status",
                          yt_public.backfill_reason(len(ids), len(rows), failed),
                          len(ids), len(rows))
    return len(rows)
