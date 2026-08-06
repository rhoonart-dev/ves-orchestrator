#!/usr/bin/env python3
"""reaper — 만료 lease 회수 (§6-4, 매분). 죽은/잠든 노드의 잡을 큐로 되돌린다."""
from __future__ import annotations

SQL = """
UPDATE public.job_queue
   SET status = CASE WHEN attempt >= max_attempts THEN 'dead' ELSE 'pending' END,
       node_id = NULL, lease_expires_at = NULL,
       run_after = now() + (interval '1 minute' * power(3, attempt)),
       error = coalesce(error,'') || ' [lease expired]', error_class = 'transient',
       updated_at = now()
 WHERE status = 'running' AND lease_expires_at < now()
RETURNING id, kind, attempt, status;
"""


def run(conn):
    with conn.cursor() as c:
        c.execute(SQL)
        rows = c.fetchall()
    for r in rows:
        tag = "☠ dead" if r["status"] == "dead" else "재큐"
        print(f"[reaper] {r['kind']} {str(r['id'])[:8]} lease 만료 → {tag} (attempt {r['attempt']})")
    return len(rows)
