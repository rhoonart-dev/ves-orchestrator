#!/usr/bin/env python3
"""channels_sync — channels.json(정본) → channels_mirror(RPC 검증용 사본) (★② R17).

정본은 파일이다. 미러는 대시보드 RPC(R10)가 참조하는 읽기 사본일 뿐이며,
워커·발행·토큰 발급은 계속 파일만 읽는다(기존 코드 무변경). synced_sha 로 신선도 추적(지표17).
"""
from __future__ import annotations

import json
import pathlib
import subprocess

from ves import config as cfgmod


# ───────── 순수 (테스트 대상) ─────────
def plan_sync(file_records: list, mirror_slugs: set) -> tuple:
    """(upsert 대상 레코드들, 삭제할 slug들). 파일이 정본 — 파일에 없는 미러 행은 지운다."""
    file_slugs = {r.get("token_slug") for r in file_records if r.get("token_slug")}
    upserts = [r for r in file_records if r.get("token_slug")]
    deletes = sorted(mirror_slugs - file_slugs)
    return upserts, deletes


# ───────── 실행부 ─────────
def run(conn, cfg):
    brain = cfgmod.engine_dir(cfg, "brain")
    p = pathlib.Path(brain) / "config" / "channels.json"
    if not p.exists():
        print(f"[channels_sync] channels.json 없음: {p}")
        return
    records = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        records = records.get("channels") or []
    sha = _brain_sha(brain)

    with conn.cursor() as c:
        c.execute("SELECT token_slug FROM public.channels_mirror")
        mirror = {r["token_slug"] for r in c.fetchall()}
    upserts, deletes = plan_sync(records, mirror)

    with conn.cursor() as c:
        for r in upserts:
            c.execute(
                """INSERT INTO public.channels_mirror
                       (token_slug, name, channel_id, gcp_project, geoblock_capable, works,
                        design, synced_sha, synced_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now())
                   ON CONFLICT (token_slug) DO UPDATE SET
                       name=EXCLUDED.name, channel_id=EXCLUDED.channel_id,
                       gcp_project=EXCLUDED.gcp_project,
                       geoblock_capable=EXCLUDED.geoblock_capable,
                       works=EXCLUDED.works, design=EXCLUDED.design,
                       synced_sha=EXCLUDED.synced_sha, synced_at=now()""",
                (r["token_slug"], r.get("name"), r.get("channel_id"), r.get("gcp_project"),
                 bool(r.get("geoblock_capable")), r.get("works") or [],
                 json.dumps(r["design"], ensure_ascii=False) if r.get("design") is not None else None,
                 sha))
        for slug in deletes:
            c.execute("DELETE FROM public.channels_mirror WHERE token_slug=%s", (slug,))
    print(f"[channels_sync] upsert {len(upserts)} · delete {len(deletes)} (sha {sha[:7] if sha else '?'})")


def _brain_sha(path):
    r = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip() if r.returncode == 0 else ""
