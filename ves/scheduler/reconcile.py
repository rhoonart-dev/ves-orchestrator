#!/usr/bin/env python3
"""reconcile — 발행분 ↔ youtube_studio 연결 + measure/audit 잡 예약 (§8-3, 매시).

★⑧ measure 의 앵커는 업로드 시각이 아니라 **실제 공개 시각**이다. 기계는 private/unlisted
까지만 올리고 공개는 사람이 Studio 에서 하므로, 공개 시각은 여기(reconcile)가
clips.published_at 으로 발견한다. run_after 는 하한일 뿐 — 최종 판정 가능 여부는
커버리지 게이트(brain loop_controller)가 정한다(D2 유지).
"""
from __future__ import annotations

import json
import subprocess

from ves import config as cfgmod
from ves.adapters.base import idem_key

# Phase 4 스위치: measure/audit 잡 자동 예약. brain 판정 CLI 접합 전까지 False.
CREATE_MEASURE_JOBS = False


def run(conn, cfg):
    _run_brain_reconcile(cfg)
    if CREATE_MEASURE_JOBS:
        _schedule_measures(conn)


def _run_brain_reconcile(cfg):
    """brain reconcile_published.py 호출 — 미연결 auto_edit ↔ youtube_studio 정합."""
    brain = cfgmod.engine_dir(cfg, "brain")
    try:
        r = subprocess.run(
            [cfgmod.engine_py(cfg, "brain"), f"{brain}/scripts/reconcile_published.py", "--apply"],
            cwd=brain, capture_output=True, text=True, timeout=600)
        tail = (r.stdout or r.stderr or "")[-300:]
        print(f"[reconcile] brain rc={r.returncode} {tail}")
    except Exception as e:  # noqa: BLE001
        print(f"[reconcile] 실행 실패: {e}")


def _schedule_measures(conn):
    """공개 시각이 확인된 클립에 measure 잡 예약(멱등). ★⑧"""
    with conn.cursor() as c:
        c.execute(
            """SELECT c.id AS clip_id, c.video_external_id, c.published_at
                 FROM public.clips c
                WHERE c.source='auto_edit' AND c.video_external_id IS NOT NULL
                  AND c.published_at IS NOT NULL
                  AND NOT EXISTS (
                        SELECT 1 FROM public.job_queue j
                         WHERE j.kind='measure'
                           AND j.params->>'clip_id' = c.id::text)""")
        rows = c.fetchall()
    for r in rows:
        params = {"clip_id": str(r["clip_id"]), "content_id": r["video_external_id"]}
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.job_queue
                       (kind, params, idempotency_key, required_caps, run_after)
                   VALUES ('measure', %s::jsonb, %s, '{analyze}',
                           %s::timestamptz + interval '11 days')
                   ON CONFLICT (idempotency_key) DO NOTHING""",
                (json.dumps(params), idem_key(r["clip_id"], "measure", params),
                 r["published_at"]))
    if rows:
        print(f"[reconcile] measure 예약 검토 {len(rows)}건")
