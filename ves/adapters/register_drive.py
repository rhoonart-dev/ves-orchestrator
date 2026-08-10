#!/usr/bin/env python3
"""sync_drive_folder 어댑터(네이티브) — 구글 드라이브 소스 자동 인입 (0013).

drive_watch(스케줄러, 매일 07시 KST)가 이 잡을 만든다. 두 원천:
  · 외부 작품 폴더(ops_config.drive_watch_folder) — 하위폴더명 = 작품명(laeebly 정본 표기)
  · laeebly 드라이브형 작품의 download_link 폴더 — 폴더 전체가 그 작품

접근 경로 2중화(실측 2026-08-10: 권리사 폴더는 계정 공유라 무인증 불가):
  1) rclone 인증 — secrets/rclone.conf 가 있으면 우선 (권리사 폴더 포함 전부 접근)
     · 잡은 ops_config.drive_sync_node 노드로 고정(rclone.conf 가 거기만 있음)
  2) gdown 무인증 — 폴백 (링크 공개 폴더만)
동작: 목록 → 기등록(registered_by='drive:<file_id>') 제외 → 새 파일만 다운로드
→ sha256 → ves-sources 업로드 → sources 등록 → 임시파일 삭제. 멱등(file_id·sha UNIQUE).
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import shutil
import subprocess

from ves.adapters import base
from ves.storage.supabase_storage import Store

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".ts", ".avi", ".webm")
_FOLDER_ID_RE = re.compile(r"/folders/([A-Za-z0-9_-]{20,})")
_RCLONE_PATHS = ("/opt/homebrew/bin/rclone", "/usr/local/bin/rclone")


# ───────── 순수 (테스트 대상) ─────────
def folder_id_of(url: str):
    m = _FOLDER_ID_RE.search(str(url or ""))
    return m.group(1) if m else None


def first_remote(listremotes_out: str):
    """`rclone listremotes` 출력 → 첫 원격('gdrive:' 형태). 없으면 None."""
    for line in str(listremotes_out or "").splitlines():
        line = line.strip()
        if line.endswith(":"):
            return line
    return None


def lsjson_files(raw: str) -> list:
    """`rclone lsjson -R --files-only` → [(id, 상대경로)]. ID 없으면 경로 해시로 대체."""
    try:
        entries = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    out = []
    for e in entries:
        rel = e.get("Path") or e.get("Name")
        if not rel:
            continue
        fid = e.get("ID") or hashlib.sha256(str(rel).encode()).hexdigest()[:28]
        out.append((fid, str(rel)))
    return out


def plan_new(files, mode: str, work_title, known_ids) -> list:
    """목록 → [(file_id, 작품, 상대경로)]. external 모드는 첫 경로 조각=작품명."""
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
            out.append((fid, work, rel))
    return out


# ───────── rclone 경로 ─────────
def _rclone_bin():
    p = shutil.which("rclone")
    if p:
        return p
    for c in _RCLONE_PATHS:
        if pathlib.Path(c).exists():
            return c
    return None


def _rclone_conf(cfg):
    p = pathlib.Path(cfg.home) / "secrets" / "rclone.conf"
    return str(p) if p.exists() else None


def _rc(bin_, conf, *args, timeout=300):
    r = subprocess.run([bin_, "--config", conf, *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "rclone 실패")[-300:])
    return r.stdout


class _Rclone:
    def __init__(self, bin_, conf, folder_id):
        self.b, self.c, self.fid = bin_, conf, folder_id
        self.remote = first_remote(_rc(bin_, conf, "listremotes", timeout=30))
        if not self.remote:
            raise RuntimeError("rclone.conf 에 원격이 없음")

    def list(self):
        raw = _rc(self.b, self.c, "lsjson", "-R", "--files-only",
                  "--drive-root-folder-id", self.fid, self.remote, timeout=300)
        return lsjson_files(raw)

    def fetch(self, fid, rel, dest):
        _rc(self.b, self.c, "copyto", "--drive-root-folder-id", self.fid,
            f"{self.remote}{rel}", str(dest), timeout=3600 * 3)


class _Gdown:
    def __init__(self, url):
        self.url = url
        self._cache = None

    def list(self):
        import gdown
        try:
            got = gdown.download_folder(url=self.url, skip_download=True, quiet=True)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"드라이브 목록 실패(공유 설정·URL 확인): {e}")
        return [(getattr(f, "id", None),
                 str(getattr(f, "path", None) or getattr(f, "local_path", "") or ""))
                for f in got or []]

    def fetch(self, fid, rel, dest):
        import gdown
        gdown.download(id=fid, output=str(dest), quiet=True)


# ───────── 본체 ─────────
def run(cfg, conn, job, deps):
    p = job["params"]
    url, mode = p.get("folder_url"), p.get("mode") or "single"
    if not url:
        raise base.PermanentError("params.folder_url 필요")
    fid_folder = folder_id_of(url)

    bin_, conf = _rclone_bin(), _rclone_conf(cfg)
    if bin_ and conf and fid_folder:
        client, via = _Rclone(bin_, conf, fid_folder), "rclone"
    else:
        client, via = _Gdown(url), "gdown"

    with conn.cursor() as c:
        c.execute("SELECT registered_by FROM public.sources "
                  "WHERE registered_by LIKE 'drive:%'")
        known_ids = {r["registered_by"][6:] for r in c.fetchall()}

    files = client.list()
    todo = plan_new(files, mode, p.get("work_title"), known_ids)
    if not todo:
        return {"via": via, "listed": len(files), "new": 0}

    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    tmp_dir = pathlib.Path(cfg.home) / "cache" / "drive_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    srt_by_stem = {rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]: (fid, rel)
                   for fid, rel in files if rel.lower().endswith(".srt")}

    done, errors = [], []
    for fid, work, rel in todo:
        name = rel.rsplit("/", 1)[-1]
        tmp = tmp_dir / f"{fid[:24]}_{name}"
        try:
            client.fetch(fid, rel, tmp)
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
                sfid, srel = srt_by_stem[stem]
                stmp = tmp_dir / f"{fid[:24]}_{stem}.srt"
                try:
                    client.fetch(sfid, srel, stmp)
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
    return {"via": via, "listed": len(files), "new": len(todo),
            "registered": len(done), "items": done[:20], "errors": errors[:10]}
