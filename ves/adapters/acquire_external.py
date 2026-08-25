#!/usr/bin/env python3
"""외부 소재 내려받기 — 아카이브에서 고른 편의 **파일**을 구한다 (L-P5-3b).

`acquire` 의 종전 경로는 우리 `sources` 에 등록된 마스터를 캐시로 내리는 것이다.
아카이브(external_shorts)에서 고른 편은 그 표에 없다 — 원천이 둘이다:

    drive_file_id 있음 → 구글 드라이브 (rclone · 인증 필요)
    아니면              → 유튜브 URL (yt-dlp)

## 왜 한 번 다시 인코딩하는가

드라이브 마스터는 3~6분짜리 ProRes 로 **3~6 GB** 다(실측). 그걸 그대로 들고 다니면
① 스토리지 왕복이 편당 10 GB 를 넘고 ② 노드 여유 디스크(26~28 GB)가 몇 편에 찬다.
받자마자 H.264 로 줄이면 수백 MB 가 된다 — 어차피 최종 발행본은 H.264 다.

⚠ 재인코딩은 세대 손실이다. 그래서 CRF 를 낮게(18) 잡고 오디오는 그대로 복사한다.
   품질을 더 지켜야 하면 `transcode: false` 로 끄고 원본을 그대로 올린다(느리고 크다).

## 왜 스토리지를 거치는가

드라이브 인증(rclone.conf)은 **mm-01·mm-02** 에 있고 현지화 스택은 **mm-06** 에 있다
(실측 2026-08-25). 두 일이 다른 기계에서 벌어지므로 파일이 그 사이를 건너야 한다.
⚠ 나중에 mm-06 에 rclone.conf 를 두면 이 왕복을 없앨 수 있다 — 그때는 acquire 를
   같은 노드로 핀하고 로컬 경로를 그대로 넘기면 된다(별건).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

from ves.adapters import base
from ves.storage.supabase_storage import Store

BUCKET = "ves-sources"
CRF = "18"                      # 낮을수록 고품질 — 18 은 시각적 무손실에 가깝다
TRANSCODE_ABOVE_BYTES = 300 * 1024 * 1024      # 이보다 작으면 굳이 다시 안 만든다


# ───────── 순수 (테스트 대상) ─────────

def external_key(video_id: str) -> str:
    """아카이브 id → 스토리지 키. 순수.

    ⚠ `drive:1AbC…` 처럼 콜론이 들어간다 — 키에 그대로 쓰면 400 이다(base.storage_key
    주석의 한글 키 사고와 같은 부류). 접두사를 살려 두되 안전한 문자로만 적는다."""
    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(video_id or ""))
    return f"external/{safe}.mp4"


def needs_transcode(path_name: str, size_bytes: int, want: bool) -> bool:
    """다시 인코딩할까. 순수 — 테스트 대상.

    끄면(want=False) 절대 안 한다. 켜져 있어도 **작고 이미 mp4** 면 건드리지 않는다 —
    멀쩡한 파일을 세대만 깎는 짓이다."""
    if not want:
        return False
    if str(path_name or "").lower().endswith(".mp4") and size_bytes <= TRANSCODE_ABOVE_BYTES:
        return False
    return True


def ytdlp_argv(url: str, out: str) -> list:
    """유튜브 내려받기 argv. 순수 — 테스트 대상.

    화질은 1080p 까지로 묶는다 — 원본이 4K 여도 발행본이 1080 이고, 큰 파일은 디스크·
    시간만 먹는다."""
    return ["yt-dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b",
            "--merge-output-format", "mp4", "--no-playlist",
            "-o", out, url]


def rclone_argv(remote: str, file_id: str, dest_dir: str) -> list:
    """드라이브 파일 하나만 받는 argv. 순수 — 테스트 대상.

    `--drive-root-folder-id` 에 **파일 id** 를 주면 그 파일 하나가 루트가 된다
    (register_drive 가 폴더에 쓰는 것과 같은 노브)."""
    return ["copy", remote, dest_dir, "--drive-root-folder-id", file_id]


def ffmpeg_argv(src: str, dst: str, crf: str = CRF) -> list:
    """H.264 재인코딩 argv. 순수 — 테스트 대상. 오디오는 손대지 않는다(복사)."""
    return ["-y", "-i", src, "-c:v", "libx264", "-crf", crf, "-preset", "veryfast",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", dst]


# ───────── IO ─────────

def _probe_duration(path) -> float | None:
    exe = shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"
    try:
        r = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(path)],
                           capture_output=True, text=True, timeout=120)
        return float((r.stdout or "").strip()) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _fetch_drive(cfg, file_id: str, work: pathlib.Path) -> pathlib.Path:
    from ves.adapters.register_drive import _rc, _rclone_bin, _rclone_conf, first_remote
    b, c = _rclone_bin(), _rclone_conf(cfg)
    if not c:
        raise base.PermanentError(
            "rclone.conf 가 없는 노드입니다 — 드라이브 소재는 인증이 있는 노드에서만 "
            "받습니다(ops_config.drive_sync_node)")
    remote = first_remote(_rc(b, c, "listremotes", "--long", timeout=30))
    if not remote:
        raise base.PermanentError("rclone.conf 에 원격이 없음")
    _rc(b, c, *rclone_argv(remote, file_id, str(work)), timeout=3600 * 3)
    got = [p for p in work.iterdir() if p.is_file()]
    if not got:
        raise RuntimeError(f"드라이브에서 받은 파일이 없다: {file_id}")
    return max(got, key=lambda p: p.stat().st_size)


def _fetch_youtube(url: str, work: pathlib.Path) -> pathlib.Path:
    if not shutil.which("yt-dlp"):
        raise base.PermanentError("yt-dlp 가 없는 노드입니다")
    out = str(work / "src.%(ext)s")
    r = subprocess.run(ytdlp_argv(url, out), capture_output=True, text=True,
                       timeout=3600 * 2)
    got = [p for p in work.iterdir() if p.is_file()]
    if r.returncode != 0 or not got:
        raise RuntimeError(f"yt-dlp 실패: {(r.stderr or r.stdout or '')[-300:]}")
    return max(got, key=lambda p: p.stat().st_size)


def _transcode(src: pathlib.Path, dst: pathlib.Path) -> None:
    exe = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    r = subprocess.run([exe, *ffmpeg_argv(str(src), str(dst))],
                       capture_output=True, text=True, timeout=3600 * 3)
    if r.returncode != 0 or not dst.exists():
        raise RuntimeError(f"재인코딩 실패: {(r.stderr or '')[-300:]}")


def run(cfg, conn, job, deps):
    p = job["params"]
    vid = p.get("external_video_id")
    if not vid:
        raise base.PermanentError("params.external_video_id 없음")
    key = external_key(vid)
    store = Store(cfg.supabase_url, cfg.supabase_service_key)

    work = pathlib.Path(cfg.home) / "cache" / "external" / key.split("/")[-1][:-4]
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)     # 지난 시도의 잔재로 최대 파일을 잘못 고른다
    work.mkdir(parents=True, exist_ok=True)
    src = final = None
    try:
        if p.get("drive_file_id"):
            src = _fetch_drive(cfg, p["drive_file_id"], work)
        elif p.get("source_url"):
            src = _fetch_youtube(p["source_url"], work)
        else:
            raise base.PermanentError("drive_file_id 도 source_url 도 없음")

        size = src.stat().st_size
        if needs_transcode(src.name, size, bool(p.get("transcode", True))):
            final = work / "out.mp4"
            _transcode(src, final)
            print(f"[acquire/external] 재인코딩 {size/1e9:.2f}GB → "
                  f"{final.stat().st_size/1e9:.2f}GB")
        else:
            final = src

        dur = _probe_duration(final)
        store.upload(BUCKET, key, str(final))
        out_bytes = final.stat().st_size
    finally:
        # ⚠ 성공하든 실패하든 지운다 — GB 급이라 남기면 노드 디스크가 며칠에 찬다.
        shutil.rmtree(work, ignore_errors=True)

    # 길이는 여기서 처음 안다(드라이브 목록에는 없다) — 아카이브에 돌려준다.
    if dur:
        with conn.cursor() as c:
            c.execute("""UPDATE public.external_shorts
                            SET duration_sec = %s, updated_at = now()
                          WHERE video_id = %s AND duration_sec IS NULL""", (dur, vid))
    print(f"[acquire/external] {vid} → {BUCKET}/{key} "
          f"({out_bytes/1e6:.0f}MB · {dur or 0:.1f}s)")
    return {"source": "external", "external_key": key, "bucket": BUCKET,
            "bytes": out_bytes, "duration_sec": dur}
