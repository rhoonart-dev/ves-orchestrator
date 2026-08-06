#!/usr/bin/env python3
"""storage_gc — 보관 만료 산출물 삭제 (§9-4, 일 1회 06:00).

Supabase Storage 엔 lifecycle rule 이 없어 우리가 돈다. 삭제 전에 카탈로그를
'expired' 로 갱신해 대시보드가 "영상 없음"이 아니라 "보관 만료"로 표시하게 한다.
마스터(ves-sources)는 이 잡의 대상이 아니다 — 수동 삭제만(§9-4).
"""
from __future__ import annotations

from ves.storage.supabase_storage import Store


def run(conn, cfg):
    with conn.cursor() as c:
        c.execute(
            """SELECT id, bucket, object_key FROM public.artifacts
                WHERE expires_at IS NOT NULL AND expires_at < now()
                  AND bucket <> 'ves-sources' AND kind NOT LIKE '%%expired%%'
                LIMIT 200""")
        rows = c.fetchall()
    if not rows:
        return
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    by_bucket: dict = {}
    for r in rows:
        by_bucket.setdefault(r["bucket"], []).append(r)
    deleted = 0
    for bucket, items in by_bucket.items():
        try:
            store.delete(bucket, [i["object_key"] for i in items])
        except Exception as e:  # noqa: BLE001 — 다음 주기 재시도
            print(f"[storage_gc] {bucket} 삭제 실패: {e}")
            continue
        with conn.cursor() as c:
            c.execute("UPDATE public.artifacts SET kind = kind || '_expired' "
                      "WHERE id = ANY(%s)", ([i["id"] for i in items],))
        deleted += len(items)
    print(f"[storage_gc] {deleted}건 만료 처리")
