#!/usr/bin/env python3
"""scan_work_logos 어댑터(네이티브) — 드라이브에서 작품 로고 후보 모으기 (0114).

워크스페이스 작품 관리 '드라이브에서 가져오기' → request_work_logo_scan 이 이 잡을 건다.
폴더: 사람이 넣은 링크, 없으면 레이블리 licensed_video.download_link(드라이브 소스 가져오기와 같은 링크).
rclone 으로 폴더 아래 그림(PNG·JPG·WebP, 6MB 이하)만 받아 → 원본은 ves-work-assets 의 최종 자리에,
미리보기(360px PNG, 투명 유지)는 ves-outputs/logo_scans/<scan>/ 에 올리고 → work_logo_scans.candidates 에 적는다.
넣기는 사람이 고른 뒤 import_work_logos RPC 가 한다(파일은 다시 옮기지 않는다).
작품마다 폴더 구조가 달라 규칙으로 맞추지 않는다 — 이름에 로고·logo·타이틀이 든 것을 위로 올릴 뿐.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import uuid

from ves.adapters import base
from ves.adapters.register_drive import _rc, _rclone_bin, _rclone_conf, first_remote

ASSET_BUCKET, THUMB_BUCKET = "ves-work-assets", "ves-outputs"
MAX_BYTES, MAX_PIXELS = 6 * 1024 * 1024, 16_000_000
MAX_CANDIDATES = 60                  # 더 있으면 로고처럼 보이는 것부터 60개
THUMB_W = 360
_FOLDER_RE = re.compile(r"/folders/([A-Za-z0-9_-]{20,})")
_FILE_RE = re.compile(r"/file/d/([A-Za-z0-9_-]{20,})")
_OPEN_RE = re.compile(r"[?&]id=([A-Za-z0-9_-]{20,})")
LOGOISH_RE = re.compile(r"로고|타이틀|logo|title|\bci\b|\bbi\b|워드마크|wordmark", re.I)
EXTS = {"png": ("image/png", "png"), "jpg": ("image/jpeg", "jpg"), "jpeg": ("image/jpeg", "jpg"),
        "webp": ("image/webp", "webp")}


# ───────── 순수 (테스트 대상) ─────────
def parse_drive_link(text: str):
    """레이블리 download_link(산문 섞임)·사람이 넣은 링크 → (kind, id). kind: folder | file | open | None.
    open(?id=)은 폴더일 수도 파일일 수도 있다 — 폴더로 훑어 보고 비면 폴더 링크를 달라고 한다."""
    s = str(text or "")
    for kind, rx in (("folder", _FOLDER_RE), ("file", _FILE_RE), ("open", _OPEN_RE)):
        m = rx.search(s)
        if m:
            return kind, m.group(1)
    return None, None


def sniff(head: bytes):
    """파일 앞부분으로 형식 — 확장자만 믿지 않는다. (mime, ext) 또는 None."""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def logoish(rel: str) -> bool:
    return bool(LOGOISH_RE.search(rel.replace("_", " ").replace("-", " ")))


def order(cands: list) -> list:
    """로고처럼 보이는 것 먼저, 그다음 경로 순."""
    return sorted(cands, key=lambda c: (not c["logoish"], c["path"].lower()))


def need_folder_reason(kind, found_any: bool) -> str:
    if kind is None:
        return "등록된 드라이브 링크가 없어요. 로고가 들어 있는 폴더 링크를 넣어 주세요."
    if kind == "file":
        return "등록된 링크가 폴더가 아니라 파일 하나예요. 로고가 들어 있는 폴더 링크를 넣어 주세요."
    if found_any:
        return "이 폴더의 그림은 이미 다 넣었어요. 다른 폴더에서 찾으려면 링크를 넣어 주세요."
    return "이 링크에서 그림을 찾지 못했어요. 로고가 들어 있는 폴더 링크를 넣어 주세요."


# ───────── 실행 ─────────
NOW = object()   # 시각 칸은 데이터베이스 시계로


def _set(conn, scan_id, **kv):
    cols = ", ".join(f"{k}=now()" if v is NOW else f"{k}=%s" for k, v in kv.items())
    vals = [json.dumps(v, ensure_ascii=False) if k == "candidates" else v for k, v in kv.items() if v is not NOW]
    with conn.cursor() as c:
        c.execute(f"UPDATE public.work_logo_scans SET {cols} WHERE id=%s", (*vals, scan_id))


def _laeebly(cfg, work_id):
    if not cfg.laeebly_url:
        raise base.PermanentError("이 맥미니는 레이블리에 연결돼 있지 않아요")
    from ves.db import connect
    lae = connect(cfg.laeebly_url)
    try:
        with lae.cursor() as c:
            c.execute("SELECT id::text AS id, title, download_link FROM licensed_video WHERE id::text=%s", (work_id,))
            rows = c.fetchall()
            if len(rows) != 1:
                raise base.PermanentError("레이블리에서 작품을 찾지 못했어요")
            c.execute("SELECT count(*) AS n FROM licensed_video WHERE title=%s", (rows[0]["title"],))
            if c.fetchone()["n"] != 1:
                raise base.PermanentError("같은 제목의 작품이 여러 개예요. 작품 연결을 먼저 확인해 주세요")
            return rows[0]
    finally:
        lae.close()


def _probe(path: pathlib.Path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                        "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
    s = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    return int(s.get("width") or 0), int(s.get("height") or 0)


def _thumb(src: pathlib.Path, dest: pathlib.Path) -> bool:
    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-frames:v", "1",
                        "-vf", f"scale='min({THUMB_W},iw)':-2", str(dest)], capture_output=True, timeout=120)
    return r.returncode == 0 and dest.is_file()


def _copy(bin_, conf, remote, fid, dest, *extra):
    try:
        _rc(bin_, conf, "copy", remote, str(dest), "--drive-root-folder-id", fid, "--ignore-case",
            "--include", "*.{png,jpg,jpeg,webp}", "--max-size", "6M", "--max-depth", "8",
            "--max-transfer", "600M", "--cutoff-mode", "soft", *extra, timeout=900, ok_rc=(8, 9))
    except RuntimeError as e:
        return str(e)[-200:]
    return None


def run(cfg, conn, job, deps):
    from ves.storage.supabase_storage import Store
    scan_id = str((job.get("params") or {}).get("scan_id") or "")
    with conn.cursor() as c:
        c.execute("SELECT * FROM public.work_logo_scans WHERE id::text=%s", (scan_id,))
        scan = c.fetchone()
    if not scan:
        raise base.PermanentError("찾기 기록이 없어요")
    _set(conn, scan_id, status="running", started_at=NOW, node_id=cfg.node_id)
    try:
        return _scan(cfg, conn, scan, scan_id, Store(cfg.supabase_url, cfg.supabase_service_key))
    except base.PermanentError as e:
        _set(conn, scan_id, status="failed", reason=str(e)[:300], finished_at=NOW)
        raise
    except Exception as e:  # noqa: BLE001 — 화면이 '찾는 중'에 멈추지 않게 이유를 남긴다
        _set(conn, scan_id, status="failed", reason=f"찾다가 멈췄어요: {str(e)[:200]}", finished_at=NOW)
        raise base.PermanentError(str(e)[:300]) from e


def _scan(cfg, conn, scan, scan_id, store):
    work = _laeebly(cfg, scan["work_id"])
    url = scan["folder_url"] or work["download_link"]
    kind, fid = parse_drive_link(url)
    _set(conn, scan_id, work_title=work["title"], used_url=(url or "")[:500])
    if kind in (None, "file"):
        _set(conn, scan_id, status="need_folder", reason=need_folder_reason(kind, False), finished_at=NOW)
        return {"scan_id": scan_id, "status": "need_folder"}
    bin_, conf = _rclone_bin(), _rclone_conf(cfg)
    if not bin_ or not conf:
        raise base.PermanentError("이 맥미니에 드라이브 인증(rclone)이 없어요")
    remote = first_remote(_rc(bin_, conf, "listremotes", "--long", timeout=30))
    if not remote:
        raise base.PermanentError("드라이브 인증(rclone)에 원격이 없어요")
    tmp = pathlib.Path(cfg.home) / "cache" / "logo-scans" / scan_id
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        warn = _copy(bin_, conf, remote, fid, tmp)
        if not any(p.is_file() for p in tmp.rglob("*")):
            warn = _copy(bin_, conf, remote, fid, tmp, "--drive-shared-with-me") or warn
        files = sorted(p for p in tmp.rglob("*") if p.is_file())
        with conn.cursor() as c:
            c.execute("SELECT sha256 FROM public.work_asset_versions WHERE work_title=%s", (work["title"],))
            have = {r["sha256"] for r in c.fetchall()}
        cands, seen, skipped = [], set(), 0
        for f in files:
            rel = f.relative_to(tmp).as_posix()
            data = f.read_bytes()
            fmt = sniff(data[:16])
            if not fmt or not 0 < len(data) <= MAX_BYTES:
                continue
            sha = hashlib.sha256(data).hexdigest()
            if sha in seen:
                continue
            seen.add(sha)
            if sha in have:
                skipped += 1
                continue
            w, h = _probe(f)
            if not w or not h or w * h > MAX_PIXELS:
                continue
            cands.append({"path": rel, "name": f.name, "mime": fmt[0], "ext": fmt[1], "bytes": len(data),
                          "width": w, "height": h, "sha256": sha, "logoish": logoish(rel), "_file": f})
        total = len(cands) + skipped
        if not cands:
            if warn and not files:
                raise base.PermanentError(f"드라이브 폴더를 열지 못했어요. 맥미니 계정에 공유됐는지 확인해 주세요 ({warn[:120]})")
            _set(conn, scan_id, status="need_folder", reason=need_folder_reason(kind, skipped > 0),
                 total=total, skipped=skipped, finished_at=NOW)
            return {"scan_id": scan_id, "status": "need_folder"}
        out = []
        for cand in order(cands)[:MAX_CANDIDATES]:
            f = cand.pop("_file")
            aid = str(uuid.uuid4())
            cand.update(id=aid, object_key=f"works/{aid}/{cand['sha256']}.{cand['ext']}",
                        thumb_key=f"logo_scans/{scan_id}/{aid}.png")
            store.upload(ASSET_BUCKET, cand["object_key"], str(f), content_type=cand["mime"])
            th = tmp / f".thumb-{aid}.png"
            if _thumb(f, th):
                store.upload(THUMB_BUCKET, cand["thumb_key"], str(th), content_type="image/png")
            else:
                cand["thumb_key"] = None
            out.append(cand)
        _set(conn, scan_id, status="done", candidates=out, total=total, skipped=skipped, reason=None,
             finished_at=NOW)
        return {"scan_id": scan_id, "status": "done", "candidates": len(out), "total": total}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
