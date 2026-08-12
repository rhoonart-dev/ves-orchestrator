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
    """`rclone listremotes --long` 출력('이름: 타입') → 선택 우선순위:
    ① 이름 gdrive(검증 컨벤션) ② 타입 drive 인 첫 원격 ③ 첫 원격.
    (실측 2026-08-10: 알파벳순 첫 원격을 집으면 다른 계정/백엔드로 새는 사고)"""
    rows = []
    for ln in str(listremotes_out or "").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ":" in ln:
            name, _, typ = ln.partition(":")
            rows.append((name.strip() + ":", typ.strip()))
    for r, _t in rows:
        if r.lower() == "gdrive:":
            return r
    for r, t in rows:
        if t == "drive":
            return r
    return rows[0][0] if rows else None


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


def episode_from_path(rel: str):
    """파일명 → 상위 폴더명 순으로 회차 추정. 순수 — 테스트 대상.
    실측(SNL8, 2026-08-10): 회차가 파일명(SNL_803…)이 아니라 폴더명(' 3화/')에 있었다 —
    파일명만 보던 종전 로직은 6개 전부 NULL 등록 → 회차 순환·사용집계가 깨졌다."""
    parts = [s.strip() for s in str(rel or "").replace("\\", "/").split("/") if s.strip()]
    for seg in reversed(parts):                     # 파일명 → 가까운 폴더 순
        ep = base.guess_episode(seg)
        if ep is not None:
            return ep
    return None


def plan_new(files, mode: str, work_title, known_ids, aliases=None) -> list:
    """목록 → [(file_id, 작품, 상대경로)]. external 모드는 첫 경로 조각=작품명.
    aliases: 영문 폴더명 → 작품 정본명(ops_config.drive_folder_aliases, 실측 2026-08-10)."""
    out = []
    amap = aliases or {}
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
            work = amap.get(parts[0], parts[0])
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


# rclone 종료코드: 8·9 = --max-transfer 한도 도달(정상적인 '여기까지'). 실패가 아니다.
PARTIAL_RC = (8, 9)


def _rc(bin_, conf, *args, timeout=300, ok_rc=()):
    r = subprocess.run([bin_, "--config", conf, *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and r.returncode not in ok_rc:
        raise RuntimeError((r.stderr or r.stdout or "rclone 실패")[-300:])
    return r.stdout


class _Rclone:
    """검증된 패턴 그대로: `rclone copy gdrive: <캐시> --drive-root-folder-id <id>`
    (find_work_source.py 실측 — lsjson 은 공유폴더에서 빈 목록을 주는 케이스가 있어 폐기).
    캐시 디렉토리가 남아 있으므로 copy 는 자체 증분 — 새 파일만 내려온다."""

    def __init__(self, bin_, conf, folder_id, cache_root, max_transfer=None):
        self.b, self.c, self.fid = bin_, conf, folder_id
        self.max_transfer = max_transfer
        self.remote = first_remote(_rc(bin_, conf, "listremotes", "--long", timeout=30))
        if not self.remote:
            raise RuntimeError("rclone.conf 에 원격이 없음")
        self.cache = pathlib.Path(cache_root) / folder_id
        self.cache.mkdir(parents=True, exist_ok=True)

    def _copy(self, *extra):
        """캐시로 복사. --max-transfer 로 이번 회차 분량을 끊는다(soft: 받던 파일은 마무리).

        ★비정상 종료를 치명으로 보지 않는다(8/11 실측): rclone 은 마지막에 디렉토리 modtime 을
        맞추는데, 파일이 하나도 안 내려온 하위폴더는 로컬에 없어 chtimes 가 실패하고 그게
        '오류'로 집계돼 non-zero 로 끝난다. 종전 코드는 이때 예외를 던져 **이미 받아둔 수십 GB
        까지 통째로 버렸다**(B급 199건·혜미리 12건이 이 경우). 성패는 캐시 내용으로 판단한다."""
        args = ["copy", self.remote, str(self.cache),
                "--drive-root-folder-id", self.fid, *extra]
        if self.max_transfer:
            args += ["--max-transfer", self.max_transfer, "--cutoff-mode", "soft"]
        try:
            return _rc(self.b, self.c, *args, timeout=3600 * 6, ok_rc=PARTIAL_RC)
        except RuntimeError as e:
            self.warn = str(e)[-200:]
            return ""

    def list(self):
        self.diag = f"remote={self.remote}"
        self.warn = None
        if self.max_transfer:
            self.diag += f" · max_transfer={self.max_transfer}"
        self._copy()
        if not any(self.cache.rglob("*")):
            # 공유 형태에 따라 shared-with-me 플래그가 필요한 케이스(실측 진단용 2차 시도)
            self.diag += " · retry=shared-with-me"
            self._copy("--drive-shared-with-me")
        if self.warn:
            self.diag += f" · rclone경고={self.warn[:80]}"
        out = []
        for p in sorted(self.cache.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(self.cache))
                out.append((f"path|{self.fid}|{rel}", rel))
        return out

    def fetch(self, fid, rel, dest):
        src = self.cache / rel
        if not src.is_file():
            raise RuntimeError(f"캐시에 없음: {rel}")
        shutil.copyfile(src, dest)


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

    # 배치 인입(8/11 사용자 요청): 큰 폴더는 한 번에 다 받지 않고 회차로 나눈다 —
    # 한 번에 다 받는 구조에선 중간에 깨지면 아무것도 못 건진다(B급 스튜디오 실측).
    with conn.cursor() as c:
        c.execute("SELECT key, value FROM public.ops_config "
                  "WHERE key IN ('drive_batch_limit','drive_max_transfer','drive_folder_aliases')")
        kv = {r["key"]: r["value"] for r in c.fetchall()}
        c.execute("SELECT registered_by FROM public.sources "
                  "WHERE registered_by LIKE 'drive:%'")
        known_ids = {r["registered_by"][6:] for r in c.fetchall()}
    batch_limit = int(p.get("batch_limit") or kv.get("drive_batch_limit") or 200)
    max_transfer = p.get("max_transfer") or kv.get("drive_max_transfer") or "40G"
    row = {"value": kv.get("drive_folder_aliases")}

    bin_, conf = _rclone_bin(), _rclone_conf(cfg)
    if bin_ and conf and fid_folder:
        cache_root = pathlib.Path(cfg.home) / "cache" / "drive_sync"
        client, via = _Rclone(bin_, conf, fid_folder, cache_root,
                              max_transfer=max_transfer), "rclone"
    else:
        client, via = _Gdown(url), "gdown"
    try:
        aliases = json.loads((row or {}).get("value") or "{}")
    except json.JSONDecodeError:
        aliases = {}

    files = client.list()
    diag = getattr(client, "diag", via)
    if not files and mode == "single":
        # mm-02 실측(8/10): 무권한 계정 conf 는 오류 대신 '빈 목록'을 돌려준다 —
        # 권리사 폴더가 진짜 비어 있을 일은 없으므로 조용한 성공 대신 크게 실패(재시도→dead 가시화)
        raise RuntimeError(f"폴더 목록 0건 — 인증 계정의 접근 권한 의심 ({diag})")
    todo_all = plan_new(files, mode, p.get("work_title"), known_ids, aliases)
    todo, remaining = todo_all[:batch_limit], max(0, len(todo_all) - batch_limit)
    if not todo:
        return {"via": via, "diag": diag, "listed": len(files), "new": 0, "remaining": 0}

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

            ep = episode_from_path(rel)
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
    if remaining and done:
        _queue_continuation(conn, job, remaining)
    if via == "rclone" and done and not errors and not remaining:
        # 전량 성공 → 로컬 벌크 캐시 반환(8/11 실측: 11개 폴더 캐시 누적으로 mm-01 디스크 0).
        # 다음 daily 는 재다운로드 비용이 들지만, 등록은 known_ids 가 걸러 중복되지 않는다.
        try:
            shutil.rmtree(client.cache, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
    return {"via": via, "diag": diag, "listed": len(files), "new": len(todo),
            "registered": len(done), "remaining": remaining,
            "items": done[:20], "errors": errors[:10]}


def _queue_continuation(conn, job, remaining: int) -> None:
    """남은 파일이 있으면 '이어받기' 잡을 건다 — 같은 폴더·같은 노드, 10분 뒤.
    멱등키에 회차 번호를 넣어 매번 새 잡이 되지만, 진전이 있을 때만(done>0) 건다."""
    p = dict(job["params"] or {})
    seq = int(p.get("batch_seq") or 1) + 1
    p["batch_seq"] = seq
    key = f"{job['idempotency_key']}#b{seq}"
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.job_queue
                   (kind, params, idempotency_key, required_caps, lease_ttl_sec, run_after)
               VALUES ('sync_drive_folder', %s::jsonb, %s, %s, 600, now() + interval '10 minutes')
               ON CONFLICT (idempotency_key) DO NOTHING""",
            (json.dumps(p, ensure_ascii=False), key, job.get("required_caps") or ["network"]))
    print(f"[register_drive] 남은 {remaining}건 — 이어받기 예약(batch {seq})")
