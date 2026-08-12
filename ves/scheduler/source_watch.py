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

REMAIN_SQL = """
WITH used AS (
  SELECT s.work_title, s.use_limit,
         (SELECT count(*) FROM public.work_orders w
           WHERE w.work_title = s.work_title
             AND w.episode IS NOT DISTINCT FROM s.episode
             AND w.status NOT IN ('cancelled','failed')) AS n
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


def target_for(work: str, targets, aliases=None):
    """작품 → 인입 대상 (url, mode, subdir|None). 순수 — 테스트 대상.

    laeebly 드라이브형(single)이 있으면 그 폴더가 정본. 없으면 외부 감시폴더 안의
    '작품명 하위폴더'를 겨냥한다 — 폴더명이 영문이면 aliases 를 뒤집어 찾는다."""
    for _label, url, w, mode in targets or []:
        if mode == "single" and w == work:
            return (url, "single", None)
    rev = {v: k for k, v in (aliases or {}).items()}
    for _label, url, _w, mode in targets or []:
        if mode == "external":
            return (url, "external", rev.get(work, work))
    return None


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
    nodes = sync_nodes(kv.get("drive_sync_nodes"), kv.get("drive_sync_node"))
    open_now = _open_targets(conn)
    made = 0
    for i, work in enumerate(low):
        tgt = target_for(work, targets, aliases)
        if not tgt:
            print(f"[source_watch] {work}: 소스 부족인데 인입 폴더를 모른다 — 사람이 등록 필요")
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
                   VALUES (%s, %s::jsonb, %s, %s, 600, 50)
                   ON CONFLICT (idempotency_key) DO NOTHING""",
                (KIND, json.dumps(params, ensure_ascii=False), key, caps))
            made += c.rowcount
        open_now.add((url, subdir))
    if made:
        print(f"[source_watch] 소스 부족 {len(low)}작품({', '.join(low[:5])}) — 보충 인입 {made}건")
    return made
