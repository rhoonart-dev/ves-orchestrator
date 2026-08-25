#!/usr/bin/env python3
"""원자적 claim — 이 설계의 심장 (ARCHITECTURE §6-1).

FOR UPDATE SKIP LOCKED 한 줄이 6대 동시 폴링에서 같은 잡의 중복 실행을 막는다(C1).
시각 연산은 전부 DB now() — 노드 로컬 시계를 lease 판정에 쓰지 않는다.
"""
from __future__ import annotations

CLAIM_SQL = """
WITH claimed AS (
  SELECT j.id, j.lease_ttl_sec
    FROM public.job_queue j
   WHERE j.status = 'pending' AND j.run_after <= now()
     AND j.required_caps <@ %(caps)s::text[]
     AND j.kind <> ALL(%(skip)s::text[])
     AND NOT EXISTS (SELECT 1 FROM public.job_queue d
                      WHERE d.id = ANY(j.depends_on) AND d.status <> 'succeeded')
   ORDER BY j.priority DESC, j.run_after, j.created_at
   FOR UPDATE SKIP LOCKED
   LIMIT 1
)
UPDATE public.job_queue j
   SET status='running', node_id=%(node)s, attempt=j.attempt+1, started_at=now(),
       lease_expires_at = now() + make_interval(secs => c.lease_ttl_sec),
       updated_at=now()
  FROM claimed c
 WHERE j.id = c.id
RETURNING j.*;
"""


def effective_caps(capabilities, node_id: str) -> list:
    """선언 캡 + 자기 지칭 캡('node:mm-01') — 로컬 산출물 어피니티의 짝(§6-1 보강).
    generate 완료 시 executor 가 후속 잡에 'node:<노드>' 캡을 박으면(_pin_dependents),
    그 파일을 가진 노드만 이 캡을 만족해 claim 할 수 있다. (스모크3 실측: 재시도가
    다른 노드로 튀어 'shorts 없음'으로 죽는 사고의 재발 방지)"""
    caps = list(capabilities or [])
    tag = f"node:{node_id}"
    if tag not in caps:
        caps.append(tag)
    return caps


def claim(conn, node_id: str, capabilities: list, skip_kinds=None):
    """잡 1건 원자적 획득. 없으면 None. ('일 있나 보기'와 '내가 가져가기'가 한 쿼리)

    skip_kinds — 이 노드가 '지금' 못 하는 kind(디스크 부족 등 노드 로컬 사정).
    ★못 할 잡은 애초에 집지 않는다. 집었다 반납하면 return_pending 이 run_after 를
    15분 뒤로 미는데 그 유예는 그 노드가 아니라 **모든 노드**에 걸린다 — 8/25 실측:
    디스크가 찬 mm-06 한 대가 무휴면 재폴링으로 15분마다 큐 전체를 밀리초 만에
    쓸어담아 반납하면서, 일일 배치 acquire 20건(19채널)을 2시간 정지시켰다.
    빈 목록이면 종전과 완전히 같다(kind <> ALL('{}') 는 전 행 통과)."""
    with conn.cursor() as c:
        c.execute(CLAIM_SQL, {"node": node_id,
                              "caps": effective_caps(capabilities, node_id),
                              "skip": list(skip_kinds or [])})
        row = c.fetchone()
    if row:
        from ves.db import job_event
        job_event(conn, row["id"], node_id, "pending", "running",
                  {"attempt": row["attempt"]})
    return row


def return_pending(conn, job, delay_sec: int, note: str):
    """자원 포화 등으로 잡을 큐에 되돌린다(시도 미차감 — claim 이 올린 attempt 를 되돌림).
    쿼터/자원 대기가 워커 슬롯을 점유하지 않게 하는 장치(§7)."""
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.job_queue
                  SET status='pending', node_id=NULL, lease_expires_at=NULL,
                      attempt = attempt - 1,
                      run_after = now() + make_interval(secs => %(d)s),
                      updated_at = now()
                WHERE id=%(id)s AND node_id=%(node)s AND attempt=%(att)s
                  AND status='running'""",
            {"id": job["id"], "node": job["node_id"], "att": job["attempt"], "d": delay_sec})
    from ves.db import job_event
    job_event(conn, job["id"], job["node_id"], "running", "pending", {"note": note})
