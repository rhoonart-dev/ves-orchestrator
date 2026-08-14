#!/usr/bin/env python3
"""유튜브 소스의 업로드 시각(sources.published_ts) 백필 — **기본은 dry-run**.

왜 필요한가: planner 는 같은 회차 안에서 `COALESCE(published_ts, created_at)` 순으로
소스를 고른다. 그런데 published_ts 가 **전부 비어 있다**(8/14 실측: 도깨비 45건·
커리어데이 82건 모두 0건). 목록을 빠르게 받는 yt-dlp --flat-playlist 가 업로드 시각을
주지 않기 때문이다. 그래서 정렬이 등록 시각(created_at)으로 밀려나고, 그건 '등록 잡이
목록을 훑은 순서'다 — tvN 플레이리스트는 최신순이라 **최신 영상이 먼저 소비된다**.
(오래된 것부터 쓴다는 2026-08-12 사용자 결정과 반대 방향이다.)

레거시 장부(source_usage_legacy)도 회차 단위라 planner 가 '앞선 행부터' 차감하는데,
그 '앞'이 최신순이면 엉뚱한 영상에 소진이 찍힌다. published_ts 를 채우면 두 문제가
같이 풀린다 — 정렬이 진짜 업로드 순이 된다.

왜 API 인가: 대안을 다 시험했다(8/14).
  · yt-dlp --flat-playlist         → 업로드 시각 없음(키는 있으나 값이 null)
  · youtubetab:approximate_date    → 플레이리스트·채널 피드 모두 0건
  · RSS(feeds/videos.xml)          → 플레이리스트·채널 모두 404
  · 영상 하나씩 yt-dlp             → 되지만 영상 수만큼 요청(248건이면 그만큼)
YouTube Data API videos.list 는 **한 번에 50개**를 정확한 시각으로 준다. 할당량은
호출당 1 unit(하루 10,000, 영상 업로드 한 건이 1,600) — 조회는 사실상 공짜다.

자격증명(둘 중 하나):
    YOUTUBE_API_KEY=...        # 공개 영상 조회는 API 키로 충분하다
    또는 --access-token <OAuth 액세스 토큰>   # 발행용 자격증명을 이미 쓰고 있다면 그쪽

사용:
    # 무엇이 어떻게 바뀌는지만 본다 (아무것도 바꾸지 않는다)
    python3 deploy/backfill_published_ts.py --work "도깨비 10주년 여행"
    python3 deploy/backfill_published_ts.py --all
    # 실제로 채운다 (비어 있는 행만 — 이미 값이 있으면 건드리지 않는다)
    python3 deploy/backfill_published_ts.py --work "도깨비 10주년 여행" --apply
    # 이미 있는 값까지 다시 받아 덮는다
    python3 deploy/backfill_published_ts.py --all --apply --refresh

환경: SUPABASE_URL · SUPABASE_SERVICE_KEY (register_source.py 와 같다).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/videos"
BATCH = 50                      # videos.list 한 번에 받을 수 있는 최대 id 수


def die(msg):
    print(f"✗ {msg}", file=sys.stderr)
    raise SystemExit(1)


def env(k):
    return os.environ.get(k) or die(f"환경변수 {k} 필요")


def req(url, method="GET", headers=None, data=None, timeout=60):
    r = urllib.request.Request(url, method=method, headers=headers or {}, data=data)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def video_id(url: str):
    """소스 URL → 유튜브 영상 id | None. 순수."""
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{6,})", str(url or ""))
    if m:
        return m.group(1)
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{6,})", str(url or ""))
    return m.group(1) if m else None


def chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def fetch_published(ids, api_key=None, token=None) -> dict:
    """영상 id 목록 → {id: publishedAt(ISO8601)}. 없는 id 는 빠진 채 돌아온다
    (비공개·삭제된 영상 — 채울 값이 없으니 그대로 둔다)."""
    out = {}
    for part in chunks(ids, BATCH):
        q = {"part": "snippet", "id": ",".join(part), "maxResults": str(BATCH)}
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            q["key"] = api_key
        st, body = req(f"{API}?{urllib.parse.urlencode(q)}", headers=headers)
        if st != 200:
            die(f"YouTube API {st}: {body[:300]}")
        for it in (json.loads(body).get("items") or []):
            pub = ((it.get("snippet") or {}).get("publishedAt"))
            if it.get("id") and pub:
                out[it["id"]] = pub
    return out


def order_key(row):
    """planner 와 같은 정렬 키 — 지금 화면·배정이 쓰는 순서를 재현한다."""
    return (row.get("published_ts") or row.get("created_at") or "", str(row.get("id")))


def preview(rows, found):
    """회차별로 '지금 순서 → 채운 뒤 순서'를 보여준다. 순서가 그대로면 조용히 넘어간다."""
    by_ep = {}
    for r in rows:
        by_ep.setdefault(r.get("episode"), []).append(r)
    changed = 0
    for ep in sorted(by_ep, key=lambda x: (x is None, x)):
        group = by_ep[ep]
        now = sorted(group, key=order_key)
        new = sorted(group, key=lambda r: (found.get(video_id(r["source_url"]))
                                           or r.get("published_ts")
                                           or r.get("created_at") or "", str(r["id"])))
        if [r["id"] for r in now] == [r["id"] for r in new]:
            continue
        changed += 1
        print(f"\n  [{ep if ep is not None else '단편'}회차] 순서가 바뀝니다")
        for i, r in enumerate(new, 1):
            pub = found.get(video_id(r["source_url"]))
            was = now.index(r) + 1
            mark = "  " if was == i else "→ "
            print(f"    {mark}{i:>2}. (지금 {was:>2}위) {(pub or '시각없음')[:10]} "
                  f"{r['source_url'].rsplit('=', 1)[-1]}")
    if not changed:
        print("  (회차별 순서 변화 없음 — 값만 채워집니다)")


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--work", help="작품명(laeebly 정본 표기)")
    g.add_argument("--all", action="store_true", help="유튜브 소스가 있는 전 작품")
    ap.add_argument("--apply", action="store_true", help="실제로 DB 에 쓴다(기본은 dry-run)")
    ap.add_argument("--refresh", action="store_true",
                    help="이미 published_ts 가 있는 행도 다시 받아 덮는다")
    ap.add_argument("--api-key", help="YouTube Data API 키(없으면 YOUTUBE_API_KEY)")
    ap.add_argument("--access-token", help="OAuth 액세스 토큰(발행용 자격증명을 쓸 때)")
    a = ap.parse_args()

    token = a.access_token
    key = a.api_key or os.environ.get("YOUTUBE_API_KEY")
    if not (token or key):
        die("YOUTUBE_API_KEY 환경변수 또는 --api-key/--access-token 이 필요합니다")

    base = env("SUPABASE_URL").rstrip("/")
    skey = env("SUPABASE_SERVICE_KEY")
    H = {"Authorization": f"Bearer {skey}", "apikey": skey}

    sel = "id,work_title,episode,source_url,published_ts,created_at"
    url = (f"{base}/rest/v1/sources?select={sel}&origin=eq.youtube"
           f"&source_url=not.is.null&order=work_title,episode")
    if a.work:
        url += f"&work_title=eq.{urllib.parse.quote(a.work)}"
    st, body = req(url, headers=H)
    if st != 200:
        die(f"sources 조회 실패 {st}: {body[:300]}")
    rows = json.loads(body)
    if not rows:
        die("대상 소스가 없습니다 — 작품명을 확인하세요(laeebly 정본 표기)")

    todo = [r for r in rows if a.refresh or not r.get("published_ts")]
    ids = sorted({video_id(r["source_url"]) for r in todo} - {None})
    print(f"대상: 소스 {len(rows)}건 · 채울 것 {len(todo)}건 · 조회할 영상 {len(ids)}개 "
          f"(API 호출 {(len(ids) + BATCH - 1) // BATCH}회)")
    if not ids:
        print("채울 것이 없습니다 — 이미 전부 값이 있습니다(--refresh 로 다시 받을 수 있습니다)")
        return

    found = fetch_published(ids, api_key=key, token=token)
    missing = [i for i in ids if i not in found]
    print(f"받아온 업로드 시각: {len(found)}개"
          + (f" · 못 받은 영상 {len(missing)}개(비공개·삭제 — 그대로 둡니다)" if missing else ""))
    for i in missing[:5]:
        print(f"    못 받음: https://youtu.be/{i}")

    # 작품별로 순서가 어떻게 바뀌는지 먼저 보여준다 — 되돌리기 어려운 변경이라
    by_work = {}
    for r in rows:
        by_work.setdefault(r["work_title"], []).append(r)
    for work, group in by_work.items():
        if not any(video_id(r["source_url"]) in found for r in group):
            continue
        print(f"\n■ {work}")
        preview(group, found)

    if not a.apply:
        print("\n[dry-run] 아무것도 바꾸지 않았습니다 — 반영하려면 --apply")
        return

    n = 0
    for r in todo:
        pub = found.get(video_id(r["source_url"]))
        if not pub:
            continue
        st, body = req(f"{base}/rest/v1/sources?id=eq.{r['id']}", method="PATCH",
                       headers={**H, "Content-Type": "application/json",
                                "Prefer": "return=minimal"},
                       data=json.dumps({"published_ts": pub}).encode("utf-8"))
        if st not in (200, 204):
            die(f"갱신 실패 {st}: {body[:200]}")
        n += 1
    print(f"\n✓ {n}건에 업로드 시각을 채웠습니다. "
          "planner 의 회차 내 순서가 이제 업로드 순입니다.")


if __name__ == "__main__":
    main()
