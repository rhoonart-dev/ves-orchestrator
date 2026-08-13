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


def _preview_stale(preview, shorts) -> bool:
    """preview 를 (재)생성해야 하는가 — 없거나 **shorts 보다 오래됐으면** True.

    🛑 존재 여부만 보면 안 된다: 템플릿 변경 재렌더(from_step=render)는 shorts.mp4 만
    다시 쓰고 옛 preview.mp4 가 남아 있어, 검수함이 **재렌더 전 영상**을 계속 재생한다
    (2026-08-12 B급_스튜디오_4bf13c55 실측 — preview 12:50 vs shorts 14:28)."""
    if not preview.exists():
        return True
    try:
        return preview.stat().st_mtime < shorts.stat().st_mtime
    except OSError:
        return True


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
    if _preview_stale(preview, shorts):
        r = subprocess.run(["ffmpeg", "-y", "-i", str(shorts), *PREVIEW_ARGS, str(preview)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"preview 트랜스코드 실패: {r.stderr[-300:]}")  # transient

    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    uploaded = []
    # 키는 base.storage_key 로 ASCII 화(★스모크3: 한글 run_id 그대로 쓰면 400 InvalidKey)
    plan = [(shorts, base.storage_key(run_id, "shorts.mp4"), "shorts_mp4", "90 days"),
            (preview, base.storage_key(run_id, "preview.mp4"), "preview_mp4", "30 days")]
    thumb = next(iter(glob.glob(f"{run_dir}/*.jpg") + glob.glob(f"{run_dir}/*.png")), None)
    if thumb:
        plan.append((pathlib.Path(thumb),
                     base.storage_key(run_id, f"thumb{pathlib.Path(thumb).suffix}"),
                     "thumb", "90 days"))
    # edit_plan(8/13): JP 변환(vlp convert_short)의 원료 — 제목·자막 텍스트, 클립 타이밍,
    # 나레이션 구간, 믹스 게인이 전부 들어 있다. 이게 있어야 OCR 없이 일본어판을 만든다.
    # localize 는 다른 맥(mm-06)에서 돌므로 스토리지를 경유해야 한다(§8-1 분산 원칙).
    for name, kind in (("edit_plan.json", "edit_plan"), ("run_log.json", "run_log")):
        f = pathlib.Path(run_dir) / name
        if f.exists():
            plan.append((f, base.storage_key(run_id, name), kind, "90 days"))

    for path, key, kind, keep in plan:
        try:
            store.upload("ves-outputs", key, str(path))
        except RuntimeError as e:
            # 스토리지 4xx(429 제외)는 재시도 무의미 — attempt 3회 소각 방지(스모크3 실측)
            msg = str(e)
            if _is_permanent_storage_error(msg):
                raise base.PermanentError(msg)
            raise
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


def _is_permanent_storage_error(msg: str) -> bool:
    """'storage upload 4xx' 중 429(쿼터)만 빼고 permanent. 순수 — 테스트 대상."""
    import re
    m = re.search(r"storage upload (\d{3})", msg)
    return bool(m) and m.group(1).startswith("4") and m.group(1) != "429"


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
