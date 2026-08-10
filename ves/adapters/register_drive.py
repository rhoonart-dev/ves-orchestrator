#!/usr/bin/env python3
"""sync_drive_folder 어댑터(네이티브) — 구글 드라이브 소스 자동 인입 (0013).

drive_watch(스케줄러, 매일 07시 KST)가 이 잡을 만든다. 두 원천:
  · 외부 작품 폴더(ops_config.drive_watch_folder) — 하위폴더명 = 작품명(laeebly 정본 표기)
  · laeebly 드라이브형 작품의 download_link 폴더 — 폴더 전체가 그 작품
동작: gdown 으로 목록 조회 → 이미 등록된 파일(registered_by='drive:<file_id>') 제외
→ 새 파일만 다운로드 → sha256 → ves-sources 업로드 → sources 카탈로그 등록 → 임시파일 삭제.
멱등: file_id 기준 + sha256 UNIQUE — 재실행·중복 업로드 안전.
⚠ gdown 공개 폴더 목록은 폴더당 50개 제한 — 회차 폴더 규모에선 충분(넘으면 분할 안내).
"""
from __future__ import annotations

import hashlib
import os
import pathlib

from ves.adapters import base
from ves.storage.supabase_storage import Store

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".ts", ".avi", ".webm")


def plan_new(files, mode: str, work_title, known_ids) -> list:
    """gdown 목록 → [(file_id, 작품, 파일명)]. 순수 — 테스트 대상.
    files: [(id, 상대경로)] · external 모드는 첫 경로 조각=작품명(루트 직치기 파일은 무시)."""
    out = []
    for fid, rel in files or []:
        if not fid or fid in (known_ids or set()):
            continue
        parts = str(rel).replace("\\", "/").split("/")
        name = parts[-1]
        if not name.lower().endswith(VIDEO_EXTS):
            continue
        if mode == "external":
            if len(parts) < 2:
                continue                     # 작품 하위폴더 규약 위반 — 루트 파일은 무시
            work = parts[0]
        else:
            work = work_title
        if work:
            out.append((fid, work, name))
    return out


def _list_folder(url: str) -> list:
    import gdown
    try:
        # gdown 6.x 시그니처(remaining_ok 제거됨 — 플릿 실측 2026-08-10).
        got = gdown.download_folder(url=url, skip_download=True, quiet=True)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"드라이브 목록 실패(공유 설정·URL 확인): {e}")
    files = []
    for f in got or []:
        fid = getattr(f, "id", None)
        rel = getattr(f, "path", None) or getattr(f, "local_path", "") or ""
        files.append((fid, str(rel)))
    return files


def run(cfg, conn, job, deps):
    import gdown
    p = job["params"]
    url, mode = p.get("folder_url"), p.get("mode") or "single"
    if not url:
        raise base.PermanentError("params.folder_url 필요")

    with conn.cursor() as c:
        c.execute("SELECT registered_by, sha256 FROM public.sources "
                  "WHERE registered_by LIKE 'drive:%'")
        rows = c.fetchall()
    known_ids = {r["registered_by"][6:] for r in rows}

    files = _list_folder(url)
    todo = plan_new(files, mode, p.get("work_title"), known_ids)
    if not todo:
        return {"listed": len(files), "new": 0}

    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    tmp_dir = pathlib.Path(cfg.home) / "cache" / "drive_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    srt_by_stem = {str(rel).rsplit("/", 1)[-1].rsplit(".", 1)[0]: fid
                   for fid, rel in files if str(rel).lower().endswith(".srt")}

    done, errors = [], []
    for fid, work, name in todo:
        tmp = tmp_dir / f"{fid}_{name}"
        try:
            gdown.download(id=fid, output=str(tmp), quiet=True)
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError("다운로드 결과 없음")
            h = hashlib.sha256()
            with open(tmp, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            sha, size = h.hexdigest(), tmp.stat().st_size
            okey = f"masters/{sha}"
            store.upload("ves-sources", okey, str(tmp))

            sub_key = None
            stem = name.rsplit(".", 1)[0]
            if stem in srt_by_stem:
                stmp = tmp_dir / f"{fid}_{stem}.srt"
                try:
                    gdown.download(id=srt_by_stem[stem], output=str(stmp), quiet=True)
                    sub_key = f"{okey}.srt"
                    store.upload("ves-sources", sub_key, str(stmp))
                finally:
                    stmp.unlink(missing_ok=True)

            ep = base.guess_episode(name)
            with conn.cursor() as c:
                c.execute(
                    """INSERT INTO public.sources
                           (work_title, episode, sha256, object_key, bytes, has_subtitle,
                            subtitle_key, origin, registered_by, use_limit)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'drive',%s,%s)
                       ON CONFLICT (sha256) DO NOTHING""",
                    (work, ep, sha, okey, size, bool(sub_key), sub_key,
                     f"drive:{fid}", int(p.get("use_limit") or 3)))
            done.append(f"{work}/{name}→{ep or '?'}화")
        except Exception as e:  # noqa: BLE001 — 파일 하나 실패가 배치를 죽이지 않는다
            errors.append(f"{name}: {str(e)[:120]}")
        finally:
            tmp.unlink(missing_ok=True)

    if errors and not done:
        raise RuntimeError("; ".join(errors)[:700])   # 전멸이면 transient 재시도
    return {"listed": len(files), "new": len(todo), "registered": len(done),
            "items": done[:20], "errors": errors[:10]}
