#!/usr/bin/env python3
"""zanmang_daily — 잔망루피 현지화 autopilot 을 VES 잡으로 편입 (2026-08-10, 매일 10:00 KST).

mac6 의 검증된 구 파이프라인(video-localization-project `src.autopilot daily`:
스캔→일본 적합도 채점→현지화→승인 대기→승인분 자동 예약 업로드)을 그대로 실행하되,
스케줄·실행·관제(성공/실패/로그)를 VES 가 잡는다 — 재작성 없이 편입부터(기획서 §10-①).
승인(approve)은 종전대로 사람 몫. 가드: ops_config zanmang_pipeline='on' 일 때만 —
mac6 의 launchd(com.rhoonart.loopy-autopilot)를 내린 뒤 켜야 이중 실행이 없다.
"""
from __future__ import annotations

import datetime as dt
import json

DEFAULT_REPO = "/Users/steve/dev/video-localization-project"
KST = dt.timezone(dt.timedelta(hours=9))


def _cfg_kv(conn, key, default=None):
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key=%s", (key,))
        row = c.fetchone()
    return (row and row.get("value")) or default


def run(conn, cfg):
    if _cfg_kv(conn, "zanmang_pipeline") != "on":
        return   # 스위치 off — mac6 launchd 정리 전까지 대기(이중 실행 방지)
    repo = _cfg_kv(conn, "zanmang_repo", DEFAULT_REPO)
    node = _cfg_kv(conn, "zanmang_node", "mm-06")
    today = dt.datetime.now(KST).date().isoformat()
    params = {"repo": repo, "task": "daily", "date": today,
              "channel_name": "잔망루피 일본", "work_title": "잔망루피 숏폼 현지화"}
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.job_queue
                   (kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec)
               VALUES ('zanmang_autopilot', %s::jsonb, %s, ARRAY[]::uuid[], %s, 900)
               ON CONFLICT (idempotency_key) DO NOTHING""",
            (json.dumps(params, ensure_ascii=False), f"zanmang:{today}",
             ["localize", f"node:{node}"]))
    print(f"[zanmang_daily] {today} 잡 등록 (repo={repo}, node={node})")
