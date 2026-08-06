#!/usr/bin/env python3
"""upload_artifacts 어댑터(네이티브) — 생성물을 Storage 로 (§8-1·§9).

shorts.mp4 원본 + 검수용 720p preview(~6MB) + 썸네일을 ves-outputs/<run_id>/ 에 올리고
artifacts 카탈로그에 등록한다. preview 가 있어야 폰 검수가 성립한다(대시보드 §10-4).
"""
from __future__ import annotations

import glob
import hashlib
import pathlib
import subprocess

from ves.adapters import base
from ves.storage.supabase_storage import Store

PREVIEW_ARGS = ["-vf", "scale=-2:720", "-c:v", "libx264", "-crf", "28",
                "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]


def run(cfg, conn, job, deps):
    gen = deps.get("generate") or {}
    run_id = gen.get("run_id") or job["params"].get("run_id")
    run_dir = gen.get("run_dir") or job["params"].get("run_dir")
    if not (run_id and run_dir):
        raise base.PermanentError("generate 결과(run_id/run_dir) 없음")

    vids = [v for v in glob.glob(f"{run_dir}/shorts*.mp4") if "_480" not in v]
    if not vids:
        raise base.PermanentError(f"shorts*.mp4 없음: {run_dir}")
    shorts = pathlib.Path(vids[0])

    preview = shorts.with_name("preview.mp4")
    if not preview.exists():
        r = subprocess.run(["ffmpeg", "-y", "-i", str(shorts), *PREVIEW_ARGS, str(preview)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"preview 트랜스코드 실패: {r.stderr[-300:]}")  # transient

    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    uploaded = []
    plan = [(shorts, f"{run_id}/shorts.mp4", "shorts_mp4", "90 days"),
            (preview, f"{run_id}/preview.mp4", "preview_mp4", "30 days")]
    thumb = next(iter(glob.glob(f"{run_dir}/*.jpg") + glob.glob(f"{run_dir}/*.png")), None)
    if thumb:
        plan.append((pathlib.Path(thumb), f"{run_id}/thumb{pathlib.Path(thumb).suffix}",
                     "thumb", "90 days"))

    for path, key, kind, keep in plan:
        store.upload("ves-outputs", key, str(path))
        sha = _sha256(path)
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.artifacts
                       (job_id, work_order_id, kind, sha256, bytes, bucket, object_key, expires_at)
                   VALUES (%s,%s,%s,%s,%s,'ves-outputs',%s, now() + %s::interval)
                   ON CONFLICT (sha256, kind) DO NOTHING""",
                (job["id"], job["work_order_id"], kind, sha, path.stat().st_size, key, keep))
        uploaded.append(key)
    return {"run_id": run_id, "run_dir": run_dir, "uploaded": uploaded}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
