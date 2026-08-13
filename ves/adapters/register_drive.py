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


_GLOB_META = "*?[]{}\\"


def rclone_escape(rel: str) -> str:
    """rclone 필터 패턴에서 글롭 문자를 문자 그대로 만든다. 순수 — 테스트 대상.
    (작품 폴더명에 '[', '{' 가 흔하다 — escape 없이 넣으면 엉뚱한 파일이 제외된다)"""
    return "".join("\\" + ch if ch in _GLOB_META else ch for ch in str(rel or ""))


def excludes_for(folder_id: str, known_ids) -> list:
    """이 폴더에서 이미 등록을 마친 상대경로들 → rclone --exclude-from 목록. 순수.

    왜 필요한가(8/12 실측): --max-transfer 로 8G 씩 끊어 받는데, 등록이 끝나면 캐시를 비웠다.
    rclone copy 는 '목적지에 없으면 받는다' 라서 다음 회차가 **같은 앞부분 8G 를 또** 받았고,
    그건 이미 등록된 파일이라 신규 0건 — B급 스튜디오가 199개 중 11개에서 영영 멈춘 원인이다.
    받은 것을 목록으로 빼주면 rclone 이 그다음부터 받는다."""
    pre = f"path|{folder_id}|"
    return sorted({k[len(pre):] for k in (known_ids or set())
                   if isinstance(k, str) and k.startswith(pre) and len(k) > len(pre)})


# 길이 하한 규칙은 base 로 이동(0031: 유튜브 등록·planner·관제와 공용). 이름은 유지.
# 작품별 하한을 쓰려면 base.is_usable(dur, min_sec) 로 부른다 — 드라이브 등록은
# 아직 기본값(180)으로 돈다(작품 카드 연결은 후속).
MIN_USABLE_SEC = base.MIN_USABLE_SEC
is_usable = base.is_usable


def top_folders(files) -> list:
    """목록 → 최상위 폴더명들(파일이 루트에 바로 있으면 제외). 순수 — 테스트 대상.
    외부 감시폴더에 '그 작품 폴더가 실제로 있는지'를 판단하는 근거가 된다."""
    out = set()
    for _fid, rel in files or []:
        parts = str(rel).replace("\\", "/").split("/")
        if len(parts) >= 2 and parts[0].strip():
            out.add(parts[0])
    return sorted(out)


# 소스 길이 → 편수 규칙은 base 로 이동(0027: 유튜브 등록과 공용). 이름은 유지.
use_limit_for = base.use_limit_for


def probe_duration(path) -> float | None:
    """ffprobe 로 재생시간(초). 실패하면 None — 등록 자체를 막지 않는다."""
    exe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(path)],
                           capture_output=True, text=True, timeout=120)
        return float((r.stdout or "").strip()) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
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


def _rc(bin_, conf, *args, timeout=300, ok_rc=(), want_rc=False):
    r = subprocess.run([bin_, "--config", conf, *args],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 and r.returncode not in ok_rc:
        raise RuntimeError((r.stderr or r.stdout or "rclone 실패")[-300:])
    return (r.stdout, r.returncode) if want_rc else r.stdout


class _Rclone:
    """검증된 패턴 그대로: `rclone copy gdrive: <캐시> --drive-root-folder-id <id>`
    (find_work_source.py 실측 — lsjson 은 공유폴더에서 빈 목록을 주는 케이스가 있어 폐기).
    캐시 디렉토리가 남아 있으므로 copy 는 자체 증분 — 새 파일만 내려온다."""

    def __init__(self, bin_, conf, folder_id, cache_root, max_transfer=None, excludes=(),
                 subdir=None):
        self.b, self.c, self.fid = bin_, conf, folder_id
        self.max_transfer = max_transfer
        self.subdir = (subdir or "").strip("/") or None   # 이 하위폴더만 받는다(보충 인입)
        self.capped = False          # --max-transfer 한도로 끊겼는가(=원격에 더 남았다)
        self.remote = first_remote(_rc(bin_, conf, "listremotes", "--long", timeout=30))
        if not self.remote:
            raise RuntimeError("rclone.conf 에 원격이 없음")
        self.cache = pathlib.Path(cache_root) / folder_id
        self.cache.mkdir(parents=True, exist_ok=True)
        self.exclude_file = None
        if excludes:
            ex = pathlib.Path(cache_root) / f"{folder_id}.exclude"
            ex.write_text("".join(f"/{rclone_escape(r)}\n" for r in excludes), encoding="utf-8")
            self.exclude_file = str(ex)

    def _copy(self, *extra):
        """캐시로 복사. --max-transfer 로 이번 회차 분량을 끊는다(soft: 받던 파일은 마무리).

        ★비정상 종료를 치명으로 보지 않는다(8/11 실측): rclone 은 마지막에 디렉토리 modtime 을
        맞추는데, 파일이 하나도 안 내려온 하위폴더는 로컬에 없어 chtimes 가 실패하고 그게
        '오류'로 집계돼 non-zero 로 끝난다. 종전 코드는 이때 예외를 던져 **이미 받아둔 수십 GB
        까지 통째로 버렸다**(B급 199건·혜미리 12건이 이 경우). 성패는 캐시 내용으로 판단한다."""
        args = ["copy", self.remote, str(self.cache),
                "--drive-root-folder-id", self.fid, *extra]
        # 필터는 적힌 순서대로 '먼저 맞는 규칙이 이긴다' — 제외를 앞에 둬야 재다운로드를 막는다.
        if self.exclude_file:      # 이미 등록한 파일은 다시 받지 않는다(진도가 나가게)
            args += ["--exclude-from", self.exclude_file]
        if self.subdir:            # 소스가 마른 작품만 겨냥(다른 작품이 전송 한도를 안 먹게)
            args += ["--include", f"/{rclone_escape(self.subdir)}/**"]
        if self.max_transfer:
            args += ["--max-transfer", self.max_transfer, "--cutoff-mode", "soft"]
        try:
            out, rc = _rc(self.b, self.c, *args, timeout=3600 * 6,
                          ok_rc=PARTIAL_RC, want_rc=True)
            if rc in PARTIAL_RC:
                self.capped = True
            return out
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

    def drop(self, rel) -> None:
        """등록을 마친 파일은 캐시에서 버린다 — 원본은 ves-sources 에 있다.
        이걸 안 하면 8G 씩 이어받는 동안 캐시가 폴더 전체 크기까지 불어난다(mm-01 디스크 0 실측).
        다시 안 받는 건 --exclude-from 이 막아준다."""
        try:
            (self.cache / rel).unlink(missing_ok=True)
        except OSError:
            pass


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
                              max_transfer=max_transfer, subdir=p.get("subdir"),
                              excludes=excludes_for(fid_folder, known_ids)), "rclone"
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

    # 작품별 소스 길이 하한(0032) — 루프 안에서 매번 조회하지 않게 한 번에 읽는다.
    # 카드가 없거나 값이 NULL 인 작품은 base 기본값(180)으로 간다.
    # 0032 미적용 DB 에서는 컬럼이 없어 조회가 실패한다 — 그때는 종전 동작(기본값)으로
    # 내려간다(배포 순서가 어긋나도 인입이 멈추지 않게).
    min_by_work = {}
    try:
        with conn.cursor() as c:
            c.execute("SELECT work_title, min_source_duration_sec FROM public.work_cards "
                      "WHERE min_source_duration_sec IS NOT NULL")
            min_by_work = {r["work_title"]: r["min_source_duration_sec"] for r in c.fetchall()}
    except Exception as e:  # noqa: BLE001 — 0032 이전 DB 호환
        print(f"[register_drive] 작품 카드 하한 조회 실패(기본값 진행): {e}")

    done, errors, skipped, refreshed = [], [], [], []
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
            # 길이로 편수를 정한다(8/12 사용자 결정): 10분 미만 1편·10~30분 2편·30분↑ 3편
            dur = probe_duration(tmp)
            ulim = int(p["use_limit"]) if p.get("use_limit") else use_limit_for(dur)
            # 하한 이하는 비활성으로 등록 — 다시 받지도, 쓰지도 않는다.
            # 하한은 작품 카드값(0032), 없으면 기본 180 — planner·유튜브 등록과 같은 규칙.
            usable = base.is_usable(dur, min_by_work.get(work))
            with conn.cursor() as c:
                # ★같은 파일이 이미 있으면(sha 중복) '건너뛰기'가 아니라 '갱신'이다(8/12 실측).
                #   ① registered_by 를 지금의 경로 키로 바꿔야 다음 회차 제외 목록에 잡힌다 —
                #      8/10 gdown 시절 키(drive:<파일ID>)로 남은 것들은 매번 다시 받히고 있었다.
                #   ② 길이를 못 재고 등록된 옛 소스에 duration_sec 을 채운다(자연스러운 백필).
                #   ③ 길이를 새로 알게 된 경우에만 편수·사용여부를 다시 계산한다.
                c.execute(
                    """INSERT INTO public.sources
                           (work_title, episode, episode_source, sha256, object_key,
                            bytes, duration_sec, has_subtitle, subtitle_key, origin,
                            registered_by, use_limit, is_active)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'drive',%s,%s,%s)
                       ON CONFLICT (sha256) DO UPDATE SET
                           registered_by = EXCLUDED.registered_by,
                           -- 0027 백필은 그때 있던 행만 채웠다. 이후 등록분도 채운다.
                           episode_source = COALESCE(sources.episode_source,
                                                     EXCLUDED.episode_source),
                           duration_sec  = COALESCE(sources.duration_sec, EXCLUDED.duration_sec),
                           use_limit = CASE WHEN sources.duration_sec IS NULL
                                             AND EXCLUDED.duration_sec IS NOT NULL
                                            THEN EXCLUDED.use_limit ELSE sources.use_limit END,
                           is_active = CASE WHEN sources.duration_sec IS NULL
                                             AND EXCLUDED.duration_sec IS NOT NULL
                                            THEN EXCLUDED.is_active ELSE sources.is_active END
                       RETURNING (xmax = 0) AS inserted""",
                    (work, ep, "parsed" if ep is not None else None,
                     sha, okey, size, dur, bool(sub_key), sub_key,
                     f"drive:{fid}", ulim, usable))
                fresh = bool((c.fetchone() or {}).get("inserted"))
            mark = f"{ulim}편" if usable else f"미사용({round((dur or 0)/60,1)}분)"
            if fresh:
                done.append(f"{work}/{name}→{ep or '?'}화·{mark}")
            else:
                refreshed.append(f"{work}/{name}")   # 이미 있던 것 — 새 소스가 아니다
            if not usable:
                skipped.append(f"{name}({round((dur or 0) / 60, 1)}분)")
            drop = getattr(client, "drop", None)
            if drop:
                drop(rel)          # 등록 끝난 파일은 캐시에서 비운다(디스크 상한 유지)
        except Exception as e:  # noqa: BLE001 — 파일 하나 실패가 배치를 죽이지 않는다
            errors.append(f"{name}: {str(e)[:120]}")
        finally:
            tmp.unlink(missing_ok=True)

    if errors and not done and not refreshed:
        raise RuntimeError("; ".join(errors)[:700])   # 전멸이면 transient 재시도
    # 아직 더 있는가: 이번 목록에서 못 다룬 것(remaining) 또는 전송 한도로 끊긴 것(capped).
    # capped 는 '원격에 더 남았다'는 뜻이라 캐시 목록만 보고는 알 수 없다 — rclone 종료코드가 근거.
    capped = bool(getattr(client, "capped", False))
    more = bool(remaining) or capped
    if more and (done or refreshed):
        _queue_continuation(conn, job, remaining)     # 진전이 있을 때만 — 헛도는 이어받기 방지
    if via == "rclone" and done and not errors and not more:
        # 다 받았다 → 남은 캐시 반환(8/11 실측: 11개 폴더 캐시 누적으로 mm-01 디스크 0)
        try:
            shutil.rmtree(client.cache, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
    return {"via": via, "diag": diag, "listed": len(files), "new": len(todo),
            "registered": len(done), "refreshed": len(refreshed),
            "remaining": remaining, "capped": capped, "more": more,
            "items": done[:20], "errors": errors[:10],
            "too_short": len(skipped), "too_short_items": skipped[:10],
            # 이 폴더의 실제 최상위 폴더명 — source_watch 가 '그 작품 폴더가 있긴 한가'를 이걸로 판단한다
            "top_folders": top_folders(files)[:40]}


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
