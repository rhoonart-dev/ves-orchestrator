#!/usr/bin/env python3
"""source_watch — 소스가 말라가는 작품을 찾아 먼저 채운다 (사용자 요청 2026-08-12).

drive_watch 는 하루 한 번, 모든 폴더를 같은 무게로 훑는다. 그래서 이런 일이 생긴다(8/12 실측):
  · 언더커버셰프는 180편치가 쌓여 있는데 인입은 계속 그쪽에도 8G 를 쓴다
  · 언니네 산지직송은 **0편** — 그 채널은 오늘 만들 게 없다
소모는 채널이 하고(채널당 하루 1편), 보충은 폴더가 한다. 둘을 이어주는 게 이 태스크다.

하는 일(1시간마다):
  ① 작품별 남은 편수 = Σ(use_limit − 사용횟수) · 며칠치 = 남은 편수 ÷ 배정 채널 수
  ② 임계(기본 3일치) 이하인 작품에 대해 그 작품 폴더만 겨냥한 인입 잡을 즉시 건다
     - laeebly 드라이브형이면 그 폴더 전체
     - 외부 감시폴더 소속이면 params.subdir 로 그 작품 하위폴더만(다른 작품에 8G 를 안 뺏긴다)
  ③ 같은 대상이 이미 대기·진행 중이면 건너뛴다. 폴더를 모르면 알림만 남긴다.
"""
from __future__ import annotations

import datetime as dt
import json

from ves.scheduler.drive_watch import collect_targets, sync_nodes

KST = dt.timezone(dt.timedelta(hours=9))
LOW_DAYS = 3.0        # 이 일수 이하로 남으면 보충
KIND = "sync_drive_folder"
# claim 은 ORDER BY priority DESC — '큰 숫자가 먼저'다(기본 100).
# 8/12 실측: 급한 보충 인입에 50 을 줬다가 오히려 뒤로 밀렸다. 앞세우려면 100 보다 커야 한다.
REFILL_PRIORITY = 150

REMAIN_SQL = """
WITH used AS (
  SELECT s.work_title, s.use_limit,
         -- 행(=영상) 단위 집계(0027) — 매칭 정본은 wo_matches_source 하나다
         (SELECT count(*) FROM public.work_orders w
           WHERE w.status NOT IN ('cancelled','failed')
             AND public.wo_matches_source(
                   w.work_title, w.source_sha256, w.source_url,
                   s.work_title, s.sha256, s.source_url)) AS n
    FROM public.sources s WHERE s.is_active)
SELECT u.work_title,
       sum(greatest(u.use_limit - u.n, 0))::int AS remaining,
       (SELECT count(*) FROM public.channels_mirror c
         WHERE c.works @> ARRAY[u.work_title])::int AS channels
  FROM used u GROUP BY 1
"""


def runway_days(remaining, channels) -> float:
    """남은 편수 → 며칠치. 채널이 여럿이면 하루에 그 수만큼 빠진다. 순수 — 테스트 대상.
    배정 채널이 0이면 소모되지 않으므로 무한(보충 대상 아님)."""
    ch = int(channels or 0)
    if ch <= 0:
        return float("inf")
    return max(float(remaining or 0), 0.0) / ch


def needs_refill(rows, low_days: float = LOW_DAYS) -> list:
    """작품 목록 → 보충이 급한 순서. 순수 — 테스트 대상.
    rows: [{work_title, remaining, channels}]"""
    scored = []
    for r in rows or []:
        w = (r or {}).get("work_title")
        if not w:
            continue
        d = runway_days(r.get("remaining"), r.get("channels"))
        if d <= low_days:
            scored.append((d, w))
    return [w for _d, w in sorted(scored, key=lambda t: (t[0], t[1]))]


def pick_subdir(work: str, folders, aliases=None):
    """작품 → 외부 감시폴더 안의 실제 하위폴더명. 없으면 None. 순수 — 테스트 대상.

    ★추측하지 않는다(8/12 실측): 별칭 맵을 뒤집어 'kimbujang' 을 넣었더니 실제 폴더는
    '김부장' 이라 --include 가 아무것도 못 잡고 조용히 0건으로 끝났다. 그래서 실제로 본
    폴더 목록(직전 인입 잡의 top_folders)에 있는 이름만 쓴다."""
    have = set(folders or [])
    if work in have:
        return work
    for folder, canon in (aliases or {}).items():      # 별칭은 '폴더명 → 작품 정본명'
        if canon == work and folder in have:
            return folder
    return None


def target_for(work: str, targets, aliases=None, folders=None):
    """작품 → 인입 대상 (url, mode, subdir|None). 없으면 None. 순수 — 테스트 대상.

    laeebly 드라이브형(single)이 있으면 그 폴더가 정본(하위폴더 겨냥 불필요).
    없으면 외부 감시폴더에 그 작품 폴더가 '실제로 있을 때만' 겨냥한다."""
    for _label, url, w, mode in targets or []:
        if mode == "single" and w == work:
            return (url, "single", None)
    sub = pick_subdir(work, folders, aliases)
    if not sub:
        return None                       # 받을 곳이 없다 — 사람이 올려야 한다
    for _label, url, _w, mode in targets or []:
        if mode == "external":
            return (url, "external", sub)
    return None


def known_folders(conn) -> list:
    """직전에 외부 감시폴더를 통째로 훑은 잡이 본 최상위 폴더 목록."""
    with conn.cursor() as c:
        c.execute("""SELECT result->'top_folders' AS f FROM public.job_queue
                      WHERE kind=%s AND status='succeeded'
                        AND params->>'subdir' IS NULL
                        AND result ? 'top_folders'
                      ORDER BY finished_at DESC NULLS LAST LIMIT 1""", (KIND,))
        row = c.fetchone()
    return list((row or {}).get("f") or [])


def _open_targets(conn) -> set:
    """이미 대기·진행 중인 인입 대상 (folder_url, subdir) — 중복 발사 방지."""
    with conn.cursor() as c:
        c.execute("""SELECT params->>'folder_url' AS u, params->>'subdir' AS s
                       FROM public.job_queue
                      WHERE kind=%s AND status IN ('pending','running')""", (KIND,))
        return {(r["u"], r["s"]) for r in c.fetchall()}


def run(conn, cfg) -> int:
    now = dt.datetime.now(KST)
    with conn.cursor() as c:
        c.execute(REMAIN_SQL)
        rows = [dict(r) for r in c.fetchall()]
        c.execute("SELECT key, value FROM public.ops_config "
                  "WHERE key IN ('drive_sync_node','drive_sync_nodes',"
                  "'drive_folder_aliases','source_low_days')")
        kv = {r["key"]: r["value"] for r in c.fetchall()}
    try:
        aliases = json.loads(kv.get("drive_folder_aliases") or "{}")
    except json.JSONDecodeError:
        aliases = {}
    low_days = float(kv.get("source_low_days") or LOW_DAYS)

    low = needs_refill(rows, low_days)
    if not low:
        return 0

    targets = collect_targets(conn, cfg)
    folders = known_folders(conn)
    nodes = sync_nodes(kv.get("drive_sync_nodes"), kv.get("drive_sync_node"))
    open_now = _open_targets(conn)
    made = 0
    for i, work in enumerate(low):
        tgt = target_for(work, targets, aliases, folders)
        if not tgt:
            print(f"[ALERT] {work}: 소스가 곧 바닥인데 받아올 폴더가 없다 — "
                  f"권리사 드라이브에 폴더가 없거나 이름이 다르다. 사람이 올려야 함 "
                  f"(감시폴더의 하위폴더: {', '.join(folders) or '목록 없음'})")
            continue
        url, mode, subdir = tgt
        if (url, subdir) in open_now:
            continue                      # 이미 받고 있다
        params = {"folder_url": url, "mode": mode, "reason": "low_source"}
        if subdir:
            params["subdir"] = subdir
        if mode == "single":
            params["work_title"] = work
        caps = ["network"] + ([f"node:{nodes[i % len(nodes)]}"] if nodes else [])
        key = f"source-refill|{url}|{subdir or '-'}|{now.strftime('%Y-%m-%dT%H')}"
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.job_queue
                       (kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
                   VALUES (%s, %s::jsonb, %s, %s, 600, %s)
                   ON CONFLICT (idempotency_key) DO NOTHING""",
                (KIND, json.dumps(params, ensure_ascii=False), key, caps, REFILL_PRIORITY))
            made += c.rowcount
        open_now.add((url, subdir))
    if made:
        print(f"[source_watch] 소스 부족 {len(low)}작품({', '.join(low[:5])}) — 보충 인입 {made}건")
    return made
