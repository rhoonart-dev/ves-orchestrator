#!/usr/bin/env python3
"""acquire 어댑터(네이티브) — 소스 확인 + content-addressed 캐시 워밍 (§8-1·§9).

sources 에 등록된 마스터를 Storage 에서 노드 캐시로 내린다. 미등록이면 human_required —
"하루 20번 Drive"가 아니라 "작품·회차당 1번 등록"으로 바뀐 그 지점(§9-2).
캐시 경로는 sha 만으로 결정되므로 후속 generate 와 데이터 전달이 필요 없다.
"""
from __future__ import annotations

import hashlib
import pathlib

from ves import config as cfgmod
from ves.adapters import base
from ves.storage.supabase_storage import Store


def run(cfg, conn, job, deps):
    p = job["params"]
    with conn.cursor() as c:
        c.execute("SELECT sha256, object_key, bytes, subtitle_key FROM public.sources "
                  "WHERE work_title=%s AND episode IS NOT DISTINCT FROM %s",
                  (p["work_title"], p.get("episode")))
        src = c.fetchone()
    if src is None:
        if p.get("source_url"):                    # YouTube 소스 작품은 캐시 불필요
            return {"source": "url"}
        raise base.HumanRequired(
            f"소스 미등록: {p['work_title']} ep{p.get('episode')} — 대시보드 [소스 등록] 필요")
    if not src.get("sha256"):
        # 0012 URL 소스 행(sha 없음) — 캐시 불필요, generate 가 --youtube-url 로 직접
        # (첫 전체 회전 실측: URL 행이 존재한다는 이유로 sha 경로에 빠져 404 나던 결함)
        if p.get("source_url"):
            return {"source": "url"}
        raise base.PermanentError(
            f"소스 행에 sha·URL 둘 다 없음: {p['work_title']} ep{p.get('episode')}")

    dest = pathlib.Path(cfgmod.source_cache_path(cfg, src["sha256"]))
    if dest.exists() and dest.stat().st_size == (src["bytes"] or dest.stat().st_size):
        return {"source": "cache_hit", "sha256": src["sha256"]}

    dest.parent.mkdir(parents=True, exist_ok=True)
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    tmp = dest.with_suffix(".part")
    store.download("ves-sources", src["object_key"], str(tmp))

    h = hashlib.sha256()
    with open(tmp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != src["sha256"]:             # content-addressed 무결성(§9-2)
        tmp.unlink(missing_ok=True)
        raise RuntimeError("다운로드 sha256 불일치 — 재시도")  # transient
    tmp.rename(dest)

    if src.get("subtitle_key"):
        store.download("ves-sources", src["subtitle_key"], str(dest) + ".srt")
    return {"source": "downloaded", "sha256": src["sha256"], "bytes": dest.stat().st_size}


def should_pin(result) -> bool:
    """파일형(내려받음/캐시 적중)만 generate 를 이 노드로 고정. URL 소스는 아무 노드나
    generate 가 스스로 내려받으므로 핀 없음 — 한 노드 쏠림 방지. 순수 — 테스트 대상."""
    return (result or {}).get("source") in ("downloaded", "cache_hit")


def post_success(cfg, conn, job, result):
    """★acquire→generate 어피니티(첫 전체 회전 실측): acquire 는 mm-06, generate 는
    다른 노드에 떨어져 '소스 캐시 없음' 즉사 — upload/ingest/evaluate 핀(_pin_dependents)과
    같은 규약으로 이 구간만 빠져 있던 것을 메운다."""
    if not should_pin(result):
        return
    cap = [f"node:{cfg.node_id}"]
    with conn.cursor() as c:
        c.execute(
            """UPDATE public.job_queue
                  SET required_caps = required_caps || %s::text[], updated_at=now()
                WHERE work_order_id=%s AND kind='generate' AND status='pending'
                  AND NOT required_caps @> %s::text[]""",
            (cap, job["work_order_id"], cap))
