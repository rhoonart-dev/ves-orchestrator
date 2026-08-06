#!/usr/bin/env python3
"""lease 갱신·완료·실패 — 전부 소유권 조건부(펜싱, ★⑤ R16).

lease 만료로 잡이 재배정된 뒤에도 원래 노드가 살아 돌고 있는 '좀비 워커'가
남의 잡이 된 작업을 덮어쓰지 못하게, 모든 전이에 (node_id, attempt, status) 조건을 건다.
갱신 0행 = 소유권 상실 = 즉시 서브프로세스 kill (executor 가 수행).
부수효과: 사람이 대시보드에서 running 잡을 cancelled 로 바꾸면 같은 경로로 ~갱신주기 안에 중단된다.
"""
from __future__ import annotations

import json
import threading

from ves.adapters.base import backoff_minutes
from ves.db import job_event

_FENCE = "id=%(id)s AND node_id=%(node)s AND attempt=%(att)s AND status='running'"


def _p(job, **kw):
    return {"id": job["id"], "node": job["node_id"], "att": job["attempt"], **kw}


def renew(conn, job) -> bool:
    """lease 연장. False = 소유권 상실(만료 회수·취소 포함) → 호출측은 작업을 즉시 중단."""
    with conn.cursor() as c:
        c.execute(
            f"""UPDATE public.job_queue
                   SET lease_expires_at = now() + make_interval(secs => lease_ttl_sec),
                       updated_at = now()
                 WHERE {_FENCE} RETURNING id""", _p(job))
        return c.fetchone() is not None


def complete(conn, job, result: dict) -> bool:
    """성공 보고(펜싱). False 면 소유권 상실 — 결과는 orphan 처리(호출측)."""
    with conn.cursor() as c:
        c.execute(
            f"""UPDATE public.job_queue
                   SET status='succeeded', result=%(res)s::jsonb, finished_at=now(),
                       lease_expires_at=NULL, updated_at=now()
                 WHERE {_FENCE} RETURNING id""",
            _p(job, res=json.dumps(result or {}, ensure_ascii=False)))
        ok = c.fetchone() is not None
    if ok:
        job_event(conn, job["id"], job["node_id"], "running", "succeeded", {})
    return ok


def fail(conn, job, error: str, error_class: str,
         until: str | None = None, result_patch: dict | None = None) -> bool:
    """실패 보고(펜싱). error_class 가 재시도 정책을 결정한다(§6-5):
       transient → 백오프 재큐(상한 도달 시 dead) · quota → run_after=리셋시각, attempt 미차감
       permanent → failed · human_required → blocked
    result_patch: 부분 산출(partial_run_id 등) 병합 — 재개(★⑦)의 근거."""
    backoff = backoff_minutes(job["attempt"])
    with conn.cursor() as c:
        c.execute(
            f"""UPDATE public.job_queue
                   SET status = CASE
                         WHEN %(cls)s = 'permanent'      THEN 'failed'
                         WHEN %(cls)s = 'human_required' THEN 'blocked'
                         WHEN %(cls)s = 'quota'          THEN 'pending'
                         WHEN attempt >= max_attempts    THEN 'dead'
                         ELSE 'pending' END,
                       run_after = CASE
                         WHEN %(cls)s = 'quota'
                           THEN coalesce(%(until)s::timestamptz, now() + interval '1 hour')
                         ELSE now() + make_interval(mins => %(backoff)s) END,
                       attempt = CASE WHEN %(cls)s = 'quota' THEN attempt - 1 ELSE attempt END,
                       error=%(err)s, error_class=%(cls)s,
                       result = coalesce(result,'{{}}'::jsonb) || %(patch)s::jsonb,
                       node_id=NULL, lease_expires_at=NULL,
                       finished_at = CASE WHEN %(cls)s='permanent' THEN now() ELSE finished_at END,
                       updated_at=now()
                 WHERE {_FENCE} RETURNING status""",
            _p(job, cls=error_class, until=until, backoff=backoff,
               err=(error or "")[-1000:],
               patch=json.dumps(result_patch or {}, ensure_ascii=False)))
        row = c.fetchone()
    if row:
        job_event(conn, job["id"], job["node_id"], "running", row["status"],
                  {"error_class": error_class, "error": (error or "")[-300:]})
    return row is not None


class LeaseRenewer:
    """백그라운드 lease 갱신 스레드. 갱신 실패(소유권 상실) 시 lost 이벤트 set →
    executor 가 서브프로세스를 kill 한다. 갱신 주기 = TTL/4."""

    def __init__(self, connect_fn, job):
        self._connect, self._job = connect_fn, job
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *a):
        self._stop.set()
        self._t.join(timeout=5)

    def _loop(self):
        interval = max(int(self._job.get("lease_ttl_sec") or 120) // 4, 15)
        while not self._stop.wait(interval):
            try:
                conn = self._connect()
                try:
                    if not renew(conn, self._job):
                        self.lost.set()
                        return
                finally:
                    conn.close()
            except Exception as e:  # noqa: BLE001 — DB 일시 단절은 다음 주기에 재시도
                print(f"[lease] 갱신 오류(재시도 예정): {type(e).__name__} {e}")
