#!/usr/bin/env python3
"""drive_balance — 인입 대기 잡을 노는 인입 노드로 옮긴다 (사용자 요청 2026-08-12).

drive_watch 는 잡을 만들 때 인덱스 라운드로빈(i % len(nodes))으로 노드를 핀한다.
그 배분은 '만들 때'만 공평하다 — 실측(8/12):
  mm-01 몫 4건(유부녀 킬러·B급 스튜디오·혜미리예채파·원희는 스무살)이 전부 재시도로 밀리는 동안
  mm-02 는 자기 5건을 09:05 에 끝내고 놀았다. 한 대는 줄이 네 겹, 한 대는 빈손.
핀이 박혀 있으니 claim 이 알아서 옮겨줄 수 없다 — 그래서 주기적으로 다시 나눈다.
running 은 절대 건드리지 않는다(진행 중인 rclone 을 뺏으면 받아둔 캐시가 뜬다).
"""
from __future__ import annotations

from ves.scheduler.drive_watch import sync_nodes

KIND = "sync_drive_folder"


def plan_rebalance(pending, busy, nodes) -> list:
    """대기 잡을 '지금 덜 바쁜 노드'부터 채운다. 바꿀 것만 돌려준다. 순수 — 테스트 대상.

    pending: [(job_id, 현재_핀_노드|None)] — 오래 기다린 순
    busy:    {노드: 진행중 인입 건수}
    nodes:   인입 가능 노드 목록(rclone.conf 가 있는 대들)
    """
    if not nodes:
        return []
    load = {n: int(busy.get(n, 0) or 0) for n in nodes}
    moves = []
    for jid, cur in pending:
        tgt = min(nodes, key=lambda n: (load[n], n))
        load[tgt] += 1
        if tgt != cur:
            moves.append((jid, tgt))
    return moves


def _node_of(caps) -> str | None:
    for c in caps or []:
        if str(c).startswith("node:"):
            return str(c)[5:]
    return None


def run(conn, cfg=None) -> int:
    with conn.cursor() as c:
        c.execute("SELECT key, value FROM public.ops_config "
                  "WHERE key IN ('drive_sync_node','drive_sync_nodes')")
        kv = {r["key"]: r["value"] for r in c.fetchall()}
    nodes = sync_nodes(kv.get("drive_sync_nodes"), kv.get("drive_sync_node"))
    if len(nodes) < 2:
        return 0                      # 한 대뿐이면 나눌 게 없다

    with conn.cursor() as c:
        c.execute("""SELECT node_id, count(*) AS n FROM public.job_queue
                      WHERE kind=%s AND status='running' GROUP BY node_id""", (KIND,))
        busy = {r["node_id"]: r["n"] for r in c.fetchall()}
        c.execute("""SELECT id, required_caps FROM public.job_queue
                      WHERE kind=%s AND status='pending'
                      ORDER BY run_after NULLS FIRST, created_at""", (KIND,))
        pending = [(r["id"], _node_of(r["required_caps"])) for r in c.fetchall()]

    moves = plan_rebalance(pending, busy, nodes)
    for jid, node in moves:
        with conn.cursor() as c:
            c.execute(
                """UPDATE public.job_queue
                      SET required_caps = (
                            SELECT coalesce(array_agg(t.c ORDER BY t.c), '{}'::text[])
                              FROM unnest(required_caps) AS t(c)
                             WHERE t.c NOT LIKE 'node:%%'
                          ) || ARRAY[%s]::text[],
                          updated_at = now()
                    WHERE id=%s AND status='pending'""", (f"node:{node}", jid))
    if moves:
        print(f"[drive_balance] 인입 대기 {len(pending)}건 중 {len(moves)}건 재배치 · 노드 {nodes}")
    return len(moves)
