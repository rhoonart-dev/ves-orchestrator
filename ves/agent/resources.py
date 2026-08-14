#!/usr/bin/env python3
"""자원 세마포어 — Gemini(GCP 프로젝트별)·YT 업로드 동시 상한 (§7, ★⑥).

check-and-insert 는 동시 실행 시 상한을 초과하는 레이스가 있으므로
pg_advisory_xact_lock 으로 자원 단위 직렬화한다(트랜잭션 종료 시 자동 해제).
획득 실패 = 포화 → 호출측은 잡을 pending 으로 반납하고 다음 잡을 본다.
"""
from __future__ import annotations

from ves.db import tx

DEFAULT_TTL_MIN = 90  # 생성 최장(~68분) + 여유. 잡이 죽어도 이 시각 후 자동 소멸.


def acquire(conn, resource: str, job_id, node_id: str, ttl_min: int = DEFAULT_TTL_MIN) -> bool:
    with tx(conn):
        with conn.cursor() as c:
            c.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"ves:res:{resource}",))
            # 재진입 안전(8/14 실측 수리): 같은 잡의 재획득은 ① 상한 계산에서 자기
            # 리스를 빼고 ② 충돌 시 만료시각을 **갱신**한다. 종전 DO NOTHING 은 잡이
            # 죽어 리스가 만료된 뒤 재클레임하면 자기 묘비(만료 행)에 막혀 영원히
            # '자원 포화'를 받았다 — 피의 게임 X generate 가 3분 간격 claim→반납을
            # 5시간 반복(01:57 만료 행 + ON CONFLICT DO NOTHING 교착).
            c.execute(
                """INSERT INTO public.resource_leases(resource, job_id, node_id, expires_at)
                   SELECT %(r)s, %(j)s, %(n)s, now() + make_interval(mins => %(ttl)s)
                    WHERE (SELECT count(*) FROM public.resource_leases
                            WHERE resource = %(r)s AND expires_at > now()
                              AND job_id <> %(j)s)
                        < coalesce((SELECT max_active FROM public.resource_limits
                                     WHERE resource = %(r)s), 999)
                   ON CONFLICT (resource, job_id) DO UPDATE
                       SET expires_at = excluded.expires_at, node_id = excluded.node_id
                   RETURNING resource""",
                {"r": resource, "j": job_id, "n": node_id, "ttl": ttl_min})
            return c.fetchone() is not None


def release(conn, resource: str, job_id) -> None:
    with conn.cursor() as c:
        c.execute("DELETE FROM public.resource_leases WHERE resource=%s AND job_id=%s",
                  (resource, job_id))
