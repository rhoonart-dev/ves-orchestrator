#!/usr/bin/env python3
"""psycopg 연결 헬퍼. lazy import — 순수 로직 테스트가 DB 의존 없이 돌게 한다."""
from __future__ import annotations

import os
from contextlib import contextmanager


def connect(dsn: str | None = None):
    import psycopg
    from psycopg.rows import dict_row
    return psycopg.connect(dsn or os.environ["PIPELINE_DB_URL"],
                           autocommit=True, row_factory=dict_row)


@contextmanager
def tx(conn):
    """명시적 트랜잭션 블록 (autocommit 연결 위에서)."""
    with conn.transaction():
        yield conn


def job_event(conn, job_id, node_id, frm, to, detail=None):
    """상태 전이 감사 로그(§5 job_events). 실패해도 본 작업을 죽이지 않는다."""
    import json
    try:
        with conn.cursor() as c:
            c.execute(
                "INSERT INTO job_events(job_id, node_id, from_status, to_status, detail) "
                "VALUES (%s,%s,%s,%s,%s::jsonb)",
                (job_id, node_id, frm, to, json.dumps(detail or {}, ensure_ascii=False)))
    except Exception as e:  # noqa: BLE001
        print(f"[job_event] 기록 실패(무시): {type(e).__name__} {e}")
