#!/usr/bin/env python3
"""trend_scout — 외부 트렌드 일일 수집기 (T-P1, 2026-08-26).

발주서: docs/TREND_REPORT.md §3-C2.

두 소스를 같은 테이블(`trend_snapshot`)에 넣는다 — 리포트가 한 자리에서 읽게.

  · youtube_chart  — `videos.list chart=mostPopular` (KR/JP/US). **지역당 1유닛**.
  · google_trends  — 일일 인기 검색어 RSS. 키 불필요·쿼터 0.

## 왜 유튜브 차트만으로는 부족한가

유튜브는 2025-07 에 인기 급상승(Trending) 페이지를 폐지했고, API 의 mostPopular 도
그때부터 통합 "Trending Now" 가 아니라 **Music/Movies/Gaming 카테고리 차트**를
돌려준다. 즉 "지금 유튜브에서 뜨는 것"의 절반만 보인다. 나머지 절반(사건·인물·밈)은
검색 트렌드가 먼저 잡으므로 둘을 같이 본다.

## 안전

· 켜는 것은 사람이다 — `ops_config.trend_scout.enabled` (기본 off).
· **실패해도 과거 스냅샷을 지우지 않는다.** 빈 응답을 '트렌드 없음'으로 오해해 덮으면
  어제와 비교할 기준이 사라진다(0078 §10-2 와 같은 규율).
· 한 지역·한 소스가 죽어도 나머지는 넣는다 — 부분 수집이 무수집보다 낫다.
· 쿼터 소진은 일시 장애다. 이번 주기만 보류하고 다음 날 다시 온다.
"""
from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from ves.scheduler.loopy_scout import QuotaExceeded, _api_get, _api_key

CONFIG_KEY = "trend_scout"
TRENDS_RSS = "https://trends.google.com/trending/rss"
CHART_MAX = 50                 # videos.list 1회 상한 — 그래도 1유닛이다

DEFAULTS = {"enabled": False, "regions": ["KR", "JP", "US"], "max_per_region": CHART_MAX,
            "market": True, "market_max_works": 5}


# ───────── 순수 (테스트 대상) ─────────

def merge_config(raw) -> dict:
    """ops_config 값 → 설정. 깨졌으면 기본값(수집이 안 돌 뿐 관제를 막지 않는다). 순수."""
    conf = dict(DEFAULTS)
    try:
        if raw:
            got = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(got, dict):
                conf.update({k: v for k, v in got.items() if k in DEFAULTS})
    except ValueError:
        pass
    if not isinstance(conf.get("regions"), list) or not conf["regions"]:
        conf["regions"] = list(DEFAULTS["regions"])
    return conf


def parse_chart(payload: dict, region: str, today: dt.date) -> list[dict]:
    """videos.list 응답 → trend_snapshot 행. 순수.

    순위는 응답 순서다(API 가 이미 차트 순으로 준다). 통계가 없는 항목(비공개 전환 등)은
    조회수를 None 으로 둘 뿐 버리지 않는다 — 순위에 있었다는 사실 자체가 기록이다."""
    rows = []
    for i, item in enumerate(payload.get("items") or [], start=1):
        sn = item.get("snippet") or {}
        st = item.get("statistics") or {}
        rows.append({
            "collected_date": today, "region": region, "source": "youtube_chart",
            "rank": i,
            "title": sn.get("title"),
            "video_id": item.get("id"),
            "channel_title": sn.get("channelTitle"),
            "category_id": sn.get("categoryId"),
            "view_count": _int_or_none(st.get("viewCount")),
            "published_at": sn.get("publishedAt"),
            "raw": json.dumps({"tags": (sn.get("tags") or [])[:10],
                               "likes": st.get("likeCount")}, ensure_ascii=False),
        })
    return rows


def parse_trends_rss(xml_text: str, region: str, today: dt.date,
                     limit: int = CHART_MAX) -> list[dict]:
    """Google Trends 일일 RSS → trend_snapshot 행. 순수.

    스키마가 바뀌어도 죽지 않는다 — 못 읽으면 빈 목록이고, 호출자가 '이 소스만 건너뜀'
    으로 처리한다. 검색 트렌드에는 video_id·category 가 없다(그 자리는 NULL)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    rows = []
    for i, item in enumerate(root.iter("item"), start=1):
        if i > limit:
            break
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        traffic = next((el.text for el in item
                        if el.tag.endswith("approx_traffic")), None)
        rows.append({
            "collected_date": today, "region": region, "source": "google_trends",
            "rank": i, "title": title, "video_id": None, "channel_title": None,
            "category_id": None,
            "view_count": _approx_traffic(traffic),
            "published_at": None,
            "raw": json.dumps({"approx_traffic": traffic}, ensure_ascii=False),
        })
    return rows


def _int_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _approx_traffic(s):
    """'20,000+' → 20000. 검색량은 구글이 자릿수로만 준다 — 정확값이 아니라 규모다. 순수."""
    if not s:
        return None
    digits = "".join(ch for ch in str(s) if ch.isdigit())
    return int(digits) if digits else None


def category_mix(rows: list[dict]) -> dict:
    """카테고리별 편수 — 리포트 §1 의 '무엇이 뜨는가'. 순수."""
    mix: dict[str, int] = {}
    for r in rows:
        cid = r.get("category_id")
        if cid:
            mix[cid] = mix.get(cid, 0) + 1
    return mix


# ───────── 부수효과 ─────────

def _cfg(conn) -> dict:
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key=%s", (CONFIG_KEY,))
        row = c.fetchone()
    return merge_config((row or {}).get("value"))


def fetch_chart(region: str, api_key: str, limit: int, today: dt.date) -> list[dict]:
    payload = _api_get("videos", {
        "part": "snippet,statistics", "chart": "mostPopular",
        "regionCode": region, "maxResults": min(int(limit or CHART_MAX), CHART_MAX),
    }, api_key)
    return parse_chart(payload, region, today)


def fetch_trends(region: str, today: dt.date) -> list[dict]:
    url = f"{TRENDS_RSS}?{urllib.parse.urlencode({'geo': region})}"
    req = urllib.request.Request(url, headers={"Accept": "application/rss+xml"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return parse_trends_rss(resp.read().decode("utf-8", errors="replace"), region, today)


def parse_market(search_payload: dict, videos_payload: dict, work: str,
                 today, rank_base: int) -> list:
    """search.list + videos.list → 시장 행. 순수 — 테스트 대상.

    운영자 지시(8/27): '시장의 신호에서 인사이트가 없다 — 유튜브 쪽 트렌드가 필요하다.'
    일반 검색 트렌드 대신 **우리 작품의 외부 시장**(같은 소재를 다루는 남의 영상 중 지금
    터지는 것)을 일일로 잰다 — 성과 검증 3차의 방법(search→videos)을 그대로 잇는다.
    rank 는 전 작품 연속 번호(rank_base+i) — PK (date,region,source,rank) 충돌 방지.
    작품명은 raw.work 로 실린다."""
    stats = {v.get("id"): v for v in (videos_payload.get("items") or [])}
    rows = []
    for i, it in enumerate((search_payload.get("items") or []), start=1):
        vid = ((it.get("id") or {}).get("videoId"))
        if not vid:
            continue
        v = stats.get(vid) or {}
        sn, st = v.get("snippet") or {}, v.get("statistics") or {}
        s2 = it.get("snippet") or {}
        rows.append({
            "collected_date": today, "region": "KR", "source": "youtube_market",
            "rank": rank_base + i,
            "title": sn.get("title") or s2.get("title"),
            "video_id": vid,
            "channel_title": sn.get("channelTitle") or s2.get("channelTitle"),
            "category_id": sn.get("categoryId"),
            "view_count": _int_or_none(st.get("viewCount")),
            "published_at": sn.get("publishedAt") or s2.get("publishedAt"),
            "raw": json.dumps({"work": work}, ensure_ascii=False),
        })
    return rows


def _market_works(conn, limit: int) -> list:
    """시장을 잴 작품 — prefer_latest(방영 중 표시, 0101) 작품이 대상이다. 상한 초과는
    자르고 로그를 남긴다(search.list 가 작품당 100유닛 — 조용한 폭식을 막는다)."""
    with conn.cursor() as c:
        try:
            c.execute("""SELECT work_title FROM public.work_cards
                          WHERE prefer_latest ORDER BY work_title""")
            works = [r["work_title"] for r in c.fetchall()]
        except Exception as e:                             # noqa: BLE001 — 0101 이전 DB
            print(f"[trend_scout] prefer_latest 조회 실패 — 시장 스윕 생략: {e}")
            try:
                conn.rollback()
            except Exception:                              # noqa: BLE001
                pass
            return []
    if len(works) > limit:
        print(f"[trend_scout] 시장 대상 {len(works)}개 중 {limit}개만 (상한 — 쿼터 보호)")
    return works[:limit]


def fetch_market(work: str, api_key: str, today, rank_base: int) -> list:
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)) \
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    sr = _api_get("search", {
        "part": "id,snippet", "q": work, "type": "video", "order": "viewCount",
        "publishedAfter": after, "regionCode": "KR", "relevanceLanguage": "ko",
        "videoDuration": "short", "maxResults": 10}, api_key)
    ids = [((it.get("id") or {}).get("videoId")) for it in (sr.get("items") or [])]
    ids = [i for i in ids if i]
    vr = _api_get("videos", {"part": "snippet,statistics", "id": ",".join(ids)},
                  api_key) if ids else {}
    return parse_market(sr, vr, work, today, rank_base)


def upsert_rows(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    with conn.cursor() as c:
        c.executemany(
            """INSERT INTO public.trend_snapshot
                   (collected_date, region, source, rank, title, video_id,
                    channel_title, category_id, view_count, published_at, raw, collected_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
               ON CONFLICT (collected_date, region, source, rank) DO UPDATE SET
                   title=EXCLUDED.title, video_id=EXCLUDED.video_id,
                   channel_title=EXCLUDED.channel_title, category_id=EXCLUDED.category_id,
                   view_count=EXCLUDED.view_count, published_at=EXCLUDED.published_at,
                   raw=EXCLUDED.raw, collected_at=now()""",
            [(r["collected_date"], r["region"], r["source"], r["rank"], r["title"],
              r["video_id"], r["channel_title"], r["category_id"], r["view_count"],
              r["published_at"], r["raw"]) for r in rows])
    return len(rows)


def run(conn, cfg):
    conf = _cfg(conn)
    if not conf.get("enabled"):
        return          # 스위치 off — 사람이 켠다(ops_config.trend_scout)
    api_key = _api_key(cfg)
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()   # KST 기준 하루
    limit = int(conf.get("max_per_region") or CHART_MAX)

    total, notes, chart_dead = 0, [], not api_key
    for region in conf["regions"]:
        if not chart_dead:
            try:
                total += upsert_rows(conn, fetch_chart(region, api_key, limit, today))
            except QuotaExceeded as e:
                # 일시 장애 — 남은 차트만 접는다. ⚠ break 는 쿼터가 필요 없는 RSS 까지
                # 다 건너뛰었다(8/27 첫 운행 교훈). 어제 스냅샷은 지우지 않는다.
                chart_dead = True
                notes.append(f"{region}:쿼터소진")
                print(f"[trend_scout] {e} — 남은 차트 보류(RSS 는 계속)")
            except Exception as e:                         # noqa: BLE001 — 한 지역 실패가 전체를 죽이지 않는다
                notes.append(f"{region}:차트실패:{type(e).__name__}:{str(e)[:80]}")
                print(f"[trend_scout] {region} 차트 실패(무시): {type(e).__name__} {e}")
        try:
            total += upsert_rows(conn, fetch_trends(region, today))
        except Exception as e:                             # noqa: BLE001
            notes.append(f"{region}:검색실패:{type(e).__name__}:{str(e)[:80]}")
            print(f"[trend_scout] {region} 검색 트렌드 실패(무시): {type(e).__name__} {e}")

    # 시장 스윕(8/27) — 방영 중 작품의 외부 상위 영상. 작품당 ~101유닛이라 쿼터가
    # 이미 죽었으면(chart_dead) 시도하지 않는다 — 내일 03:00 이 다시 온다.
    if conf.get("market") and api_key and not chart_dead:
        rank_base = 0
        for work in _market_works(conn, int(conf.get("market_max_works") or 5)):
            try:
                total += upsert_rows(conn, fetch_market(work, api_key, today, rank_base))
                rank_base += 100
            except QuotaExceeded:
                notes.append(f"시장:{work}:쿼터소진")
                print(f"[trend_scout] 시장 스윕 쿼터 소진 — {work} 에서 중단")
                break
            except Exception as e:                         # noqa: BLE001
                notes.append(f"시장:{work}:실패:{type(e).__name__}:{str(e)[:60]}")
                print(f"[trend_scout] 시장 {work} 실패(무시): {type(e).__name__} {e}")
                rank_base += 100

    if not api_key:
        notes.append("YOUTUBE_API_KEY 없음 — 검색 트렌드만")
    _note_status(conn, total, notes)
    print(f"[trend_scout] {today} {total}행 수집"
          + (f" ({', '.join(notes)})" if notes else ""))


def _note_status(conn, total: int, notes: list) -> None:
    """수집 성패를 관제가 보는 자리에 남긴다 — 8/27 첫 운행이 0행으로 끝났는데 사유가
    노드 로그에만 있어 원격에서 아무것도 알 수 없었다. 기록 실패는 본 작업을 안 죽인다."""
    import datetime as _dt
    try:
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.ops_config(key, value, note)
                   VALUES ('trend_scout_status', %s,
                           '외부 트렌드 수집 상태(코드가 씀) — 트렌드 탭·운영자가 읽는다')
                   ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
                (json.dumps({"rows": total, "notes": notes[:10],
                             "at": _dt.datetime.now(_dt.timezone.utc)
                                   .isoformat(timespec="seconds")}, ensure_ascii=False),))
    except Exception as e:                                 # noqa: BLE001
        print(f"[trend_scout] 상태 기록 실패(무시): {e}")
