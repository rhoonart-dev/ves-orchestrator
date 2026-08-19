#!/usr/bin/env python3
"""storage_gc — 보관 만료 산출물 삭제 (§9-4, 일 1회 06:00).

Supabase Storage 엔 lifecycle rule 이 없어 우리가 돈다. 삭제 전에 카탈로그를
'expired' 로 갱신해 대시보드가 "영상 없음"이 아니라 "보관 만료"로 표시하게 한다.
마스터(ves-sources)는 이 잡의 대상이 아니다 — 수동 삭제만(§9-4).

⚠ Storage 의 delete 는 body 필드명(prefixes)과 달리 **정확한 이름만** 지운다 — 일치
0건이어도 200 이라, 편집실의 접두사 행('{h16}/editor/', 0042)을 그대로 넘기던 종전
코드는 조용한 무동작이었고, 그 200 을 성공으로 믿고 '_expired' 마킹까지 해 재시도조차
막았다(2026-08-19 확인 — 0042 이래 편집실 재료가 만료 후에도 전부 잔존).
그래서 '/' 로 끝나는 키는 삭제 전에 list 로 실물 이름을 받아 확장한다.
잔존분 일괄 정리는 deploy/cleanup_editor_leftovers.py.
"""
from __future__ import annotations

from ves.storage.supabase_storage import Store

DELETE_BATCH = 100      # delete 한 번에 넘길 이름 수 — 접두사 하나가 시트 수십 장으로
                        # 확장되므로(4시간물 시트 ~15 + 클로즈업·tts) 요청을 나눈다


def expand_keys(items, lister) -> list:
    """카탈로그 행 → 지울 실물 키 목록. '/' 로 끝나는 키는 접두사 행(편집실 — 재료
    수십 개를 대표 1건으로 등록)이라 lister(prefix)→keys 로 확장한다. 접두사가 이미
    비어 있으면 그 행 몫이 0건일 뿐이다(지울 게 없으니 만료 마킹만 남는다).
    순수(lister 주입) — 테스트 대상."""
    keys = []
    for i in items:
        k = i["object_key"]
        keys += lister(k) if k.endswith("/") else [k]
    return keys


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
            keys = expand_keys(items, lambda p: store.list_keys(bucket, p))
            for n in range(0, len(keys), DELETE_BATCH):
                store.delete(bucket, keys[n:n + DELETE_BATCH])
        except Exception as e:  # noqa: BLE001 — 다음 주기 재시도(마킹 전 실패라 안전)
            print(f"[storage_gc] {bucket} 삭제 실패: {e}")
            continue
        with conn.cursor() as c:
            c.execute("UPDATE public.artifacts SET kind = kind || '_expired' "
                      "WHERE id = ANY(%s)", ([i["id"] for i in items],))
        deleted += len(items)
    print(f"[storage_gc] {deleted}건 만료 처리")
