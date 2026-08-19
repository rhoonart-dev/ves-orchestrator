#!/usr/bin/env python3
"""editor_assets 어댑터 — 검수함 '편집실'이 원본 타임라인을 그릴 재료를 만든다 (2026-08-16).

편집실은 "이 쇼츠가 원본 어디에서 왔는가"를 보여주고 그 구간을 만지게 하는 화면이다.
그러려면 브라우저가 **원본 전체 길이의 시각 재료**를 가져야 하는데, 마스터는 4~5GB 이고
정책상 브라우저가 열 수도 없다(ves-sources 는 RLS 밖). 그래서 원본 자체를 주는 대신
**스크럽용 축소 재료**를 만들어 준다:

  · 스프라이트 시트 — 전역 10초 간격 썸네일(4시간물 ≈ 1440장 ≈ 7MB, 시트로 묶어 지연 로드)
  · 경계 밀집 스프라이트 — 클립 경계 ±15초는 2초 간격(경계를 눈으로 잡을 수 있게)
  · 파형 PNG — 대사·정적 구간이 눈에 보여야 경계를 소리로도 잡는다
  · 타임라인 payload(jsonb) — 클립 구간·제목·자막을 **DB 에 직접** 넣는다

마지막 항목이 설계의 핵심이다. edit_plan.json 은 ves-outputs 에 있어 이론상 브라우저가
받을 수 있지만, ① 스토리지 JSON fetch 는 CORS 에 걸릴 수 있고 ② 자막 원본
(subtitle_segments.json)은 ves-runs 라 아예 못 읽는다. 노드는 두 파일을 모두 로컬에서
읽을 수 있으므로, 여기서 한 번에 정리해 DB 에 넣으면 화면은 평소 쓰던 select 한 번으로
끝난다 — 새 스토리지 정책도, CORS 도 필요 없다. 이미지·영상만 서명 URL 로 가져간다.

온디맨드인 이유: 편집은 소수 영상에만 일어난다. 매 run 마다 만들면 하루 20채널 × 수백 MB
가 쌓인다. 사람이 편집실을 열 때만 만들고 7일 뒤 GC(artifacts.expires_at)가 치운다.
"""
from __future__ import annotations

import glob
import json
import math
import os
import pathlib
import subprocess

from ves import config as cfgmod
from ves.adapters import base
from ves.storage.supabase_storage import Store

THUMB_W = 160                  # 썸네일 가로(세로는 비율 유지) — 4시간물 전역에서도 MB 급
GRID = 10                      # 시트당 10×10 = 100장. 시트 단위 지연 로드의 단위
GLOBAL_INTERVAL = 10.0         # 전역 스크럽 간격(초)
EDGE_INTERVAL = 2.0            # 클립 경계 부근 밀집 간격(초)
EDGE_WINDOW = 15.0             # 경계 ±이 초를 밀집 구간으로
WAVE_SIZE = "1920x120"
ASSET_TTL = "7 days"
TIMEOUT_SEC = 60 * 20

# ── 편집 프리뷰(2026-08-17) — 스프라이트로는 '어디쯤'까지만 알 수 있다. 구간을 프레임
#    단위로 잡으려면 **소리와 움직임이 있는 영상**을 봐야 한다. 두 층으로 준다:
#      · 전체 프리뷰(scan)  — 원본 전체 길이. 360p 로 **목표 용량에 맞춰** 다시 뜬다.
#        소스는 **마스터 우선**(F-206) — 프록시로 뜨면 4fps 를 물려받아 재생이 끊긴다.
#        마스터가 이 노드에 없으면 종전대로 프록시 폴백(화면이 fps 라벨로 알린다).
#      · 구간 클로즈업(closeup) — 쓰인 클립 앞뒤 CLOSEUP_PAD 초를 다시 뜬다. 실제로
#        경계를 잡는 곳은 여기뿐이라, 전체를 고품질로 뜨는 낭비를 피한다. fps=24 는
#        scan 과 같은 규칙으로 **마스터일 때만** — 프록시 폴백은 실제 fps 를 메타에 남긴다.
#    브라우저는 서명 URL + Range 로 필요한 구간만 받는다 — faststart 가 그래서 필수다.
#
#    🛑 리먹스(-c copy)로 시작했다가 실측에서 갈아엎었다(가왕쇼 47분 = 418MB).
#    분석 프록시는 ultrafast·CRF26 이라 4fps 인데도 1.2Mbps 다 — 4시간물이면 2GB 로
#    상한에 걸려 아예 안 올라간다. 그래서 CRF 가 아니라 **총 용량 목표에서 역산한
#    비트레이트**를 쓴다. 길이에 상관없이 크기가 예측되고(길수록 자동으로 낮은 화질),
#    브라우저 seek 응답은 총 크기가 아니라 비트레이트가 좌우하므로 체감도 나쁘지 않다.
PREVIEW_H = 480
CLOSEUP_FPS = 24               # 마스터 소스일 때만 적용 — 프록시(4fps) 폴백엔 걸지 않는다
CLOSEUP_CRF = 26
CLOSEUP_PAD = 90.0             # 클립 앞뒤 여유(초) — 이 밖은 전체 프리뷰로 본다
CLOSEUP_MAX_TOTAL = 40 * 60    # 클로즈업 총합 상한(초). 넘으면 긴 것부터 버린다
SCAN_H = 360                   # 전체 훑기 해상도 — '어디쯤'을 보는 용도
SCAN_FPS = 24                  # 마스터 소스일 때만 적용 — 프록시(4fps) 폴백엔 걸지 않는다
SCAN_GEN = 2                   # scan 세대 — 캐시 판정(0048)은 fps 가 아니라 이것만 본다:
                               # fps 조건이면 마스터 GC 노드가 열 때마다 무한 재생성이 된다
SCAN_TARGET_MB = 300           # 마스터(24fps) 목표 용량 — fps 상향(F-206)으로 150→300
SCAN_TARGET_MB_PROXY = 150     # 4fps 폴백 목표 — 4fps 는 낮은 비트레이트에서 포화하므로
                               # 예산을 올려봐야 화질 이득 없이 회선·스토리지만 쓴다
SCAN_TIMEOUT_SEC = 60 * 60     # scan 전용 ffmpeg 상한 — 마스터(4~5GB) 디코드는 프록시보다
                               # 수십 배 무겁다. 공용 20분이면 장편에서 타임아웃 → scan 없는
                               # ready → 열 때마다 재생성(0048 머리말의 루프)이 된다
SCAN_AUDIO_KBPS = 40           # 대사가 들려야 구간을 잡는다 — 화질보다 이쪽이 중요
SCAN_VMIN_KBPS, SCAN_VMAX_KBPS = 120, 900
SCAN_MAX_BYTES = 400 * 1024 * 1024   # 그래도 이보다 크면 올리지 않는다(회선 보호)


# ───────── 순수 (테스트 대상) ─────────
def sprite_layout(duration_sec: float, interval: float = GLOBAL_INTERVAL,
                  grid: int = GRID) -> dict:
    """전체 길이 → 스프라이트 배치. 순수 — 테스트 대상.

    화면이 "몇 번째 시트의 몇 행 몇 열"을 계산할 수 있어야 하므로 규약을 여기서 못 박는다:
    n번째 썸네일의 원본 시각 = n × interval, 시트 = n // (grid*grid), 위치 = 나머지."""
    dur = max(0.0, float(duration_sec or 0))
    per_sheet = grid * grid
    count = int(math.floor(dur / interval)) + 1 if dur > 0 else 0
    return {"interval": interval, "grid": grid, "thumb_w": THUMB_W,
            "count": count, "sheets": int(math.ceil(count / per_sheet)) if count else 0}


def edge_windows(clips: list, window: float = EDGE_WINDOW,
                 duration_sec: float | None = None) -> list:
    """클립 경계 ±window → 겹침 없이 병합된 구간 목록. 순수 — 테스트 대상.

    경계를 잡을 때만 촘촘한 프레임이 필요하다. 클립 전체를 밀집으로 뜨면 60초 × 여러 클립
    이라 장수가 폭증하는데, 실제로 눈이 필요한 곳은 시작·끝 근처뿐이다."""
    marks: list[tuple[float, float]] = []
    for c in clips or []:
        for t in (float(c.get("start_sec", 0)), float(c.get("end_sec", 0))):
            lo = max(0.0, t - window)
            hi = t + window
            if duration_sec:
                hi = min(hi, float(duration_sec))
            if hi > lo:
                marks.append((lo, hi))
    marks.sort()
    merged: list[list[float]] = []
    for lo, hi in marks:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [{"start_sec": round(a, 2), "end_sec": round(b, 2)} for a, b in merged]


def timeline_from_plan(edit_plan: dict, segments: list | None = None,
                       duration_sec: float | None = None) -> dict:
    """edit_plan.json(+자막) → 편집실 타임라인 payload. 순수 — 테스트 대상.

    좌표계를 두 개 다 담는다:
      · clips[].start_sec/end_sec — **원본 절대초**(타임라인에 그릴 위치)
      · clips[].offset_sec        — 편집본에서 이 클립이 시작하는 초(자막·프리뷰 대조용)
    자막(subtitle_segments.json)은 편집본 기준이라 offset 으로 원본 시각을 역산해 함께 준다
    — 화면에서 자막 줄을 누르면 타임라인의 그 지점이 잡히게 하려면 둘 다 필요하다."""
    plan = edit_plan or {}
    layout = plan.get("layout") or {}
    clips, offset = [], 0.0
    for i, t in enumerate(plan.get("timeline") or []):
        s = float(t.get("clip_start_sec") or 0)
        e = float(t.get("clip_end_sec") or 0)
        dur = max(0.0, e - s)
        clips.append({"idx": i, "role": t.get("role") or "build",
                      "start_sec": round(s, 3), "end_sec": round(e, 3),
                      "dur_sec": round(dur, 3), "offset_sec": round(offset, 3),
                      "use_original_audio": bool(t.get("use_original_audio", True)),
                      "note": t.get("subtitle") or ""})
        offset += dur
    subs = []
    for j, sg in enumerate(segments or []):
        st = float(sg.get("start_sec") or 0)
        en = float(sg.get("end_sec") or 0)
        subs.append({"idx": j, "edited_start": round(st, 3), "edited_end": round(en, 3),
                     "source_sec": _to_source_sec(st, clips), "text": sg.get("text") or ""})
    return {"schema": "editor_timeline/v1",
            "duration_sec": round(float(duration_sec or 0), 3),
            "top_title": layout.get("top_title") or "",
            "bottom_label": layout.get("bottom_label") or "",
            "total_clip_sec": round(offset, 3),
            "clips": clips, "subtitles": subs}


def tts_from_checkpoints(resources: dict | None, silence_cut: dict | None) -> list:
    """checkpoint_resources(우선) / checkpoint_silence_cut → 편집실 내레이션 목록. 순수.

    resources 의 tts_cue_files[].cue 가 정본이다 — 실제로 합성·렌더된 cue 라서
    문구(fit 으로 짧아진 최종본)와 편집본 시각(start/end)이 다 있다. resources 가
    없으면(구 run·중간 실패) silence_cut 의 앵커 cue 로 폴백 — 문구·원본시각·창은
    있지만 편집본 시각은 모른다(None). source_time_sec 없는 cue(구 스키마)는
    신원이 없어 편집 대상이 못 되므로 뺀다 — 화면에 보였다가 수정이 조용히
    사라지는 것보다 안 보이는 편이 낫다."""
    cues = []
    for cf in (resources or {}).get("tts_cue_files") or []:
        c = cf.get("cue") or {}
        if c.get("source_time_sec") is None:
            continue
        cues.append({"edited_start": c.get("start_sec"), "edited_end": c.get("end_sec"),
                     **_tts_common(c)})
    if not cues:
        variants = (silence_cut or {}).get("variants") or []
        for c in (variants[0].get("tts_cues") or []) if variants else []:
            if c.get("source_time_sec") is None:
                continue
            cues.append({"edited_start": None, "edited_end": None, **_tts_common(c)})
    cues.sort(key=lambda x: x["source_sec"])
    for i, c in enumerate(cues):
        c["idx"] = i
    return cues


def _tts_common(c: dict) -> dict:
    """cue → 화면 공통 필드. source_sec 이 좌표이자 신원(edit_overrides/v2 규약)."""
    return {"source_sec": round(float(c["source_time_sec"]), 3),
            "duration_sec": round(float(c.get("duration_sec") or 3.0), 3),
            "voice": c.get("voice") or "ko_female",
            "speed": c.get("speed") or "normal",
            "text": str(c.get("text") or "")}


def _to_source_sec(edited_sec: float, clips: list):
    """편집본 시각 → 원본 절대초. 클립 밖이면 None. 순수."""
    for c in clips or []:
        off, dur = float(c["offset_sec"]), float(c["dur_sec"])
        if off <= edited_sec <= off + dur:
            return round(float(c["start_sec"]) + (edited_sec - off), 3)
    return None


def sprite_key(run_id: str, kind: str, n: int) -> str:
    """스프라이트 시트 스토리지 키. 순수 — 테스트 대상."""
    return f"{base.storage_key(run_id, 'editor')}/{kind}_{n:03d}.jpg"


def sprite_cmd(src: str, out_pattern: str, interval: float, grid: int = GRID,
               width: int = THUMB_W, start: float | None = None,
               end: float | None = None) -> list:
    """스프라이트 시트 생성 ffmpeg argv. 순수 — 테스트 대상.

    -ss/-to 를 **입력 앞**에 두어 긴 소스에서도 탐색이 빠르다(밀집 구간용). fps 필터는
    interval 의 역수 — 10초 간격이면 fps=1/10."""
    argv = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if start is not None:
        argv += ["-ss", f"{start:.3f}"]
    if end is not None:
        argv += ["-to", f"{end:.3f}"]
    argv += ["-i", src,
             "-vf", f"fps=1/{interval},scale={width}:-2,tile={grid}x{grid}",
             "-qscale:v", "6", out_pattern]
    return argv


def wave_cmd(src: str, out: str, size: str = WAVE_SIZE) -> list:
    """파형 PNG 생성 argv. 순수 — 테스트 대상."""
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-filter_complex", f"showwavespic=s={size}:colors=#5b8def",
            "-frames:v", "1", out]


def scan_bitrate_kbps(duration_sec: float, target_mb: int = SCAN_TARGET_MB,
                      audio_kbps: int = SCAN_AUDIO_KBPS) -> int:
    """전체 훑기 영상의 비디오 비트레이트. 순수 — 테스트 대상.

    총 용량 목표에서 오디오 몫을 빼고 역산한다. 길수록 자동으로 낮은 화질이 되지만,
    4시간물이 2GB 가 되어 아예 못 쓰게 되는 것보다 낫다(2026-08-17 실측)."""
    dur = max(1.0, float(duration_sec or 0))
    budget_kbit = target_mb * 8192.0            # MB → kbit
    v = budget_kbit / dur - audio_kbps
    return int(max(SCAN_VMIN_KBPS, min(SCAN_VMAX_KBPS, v)))


def scan_cmd(src: str, out: str, duration_sec: float, height: int = SCAN_H,
             fps: int | None = None, target_mb: int = SCAN_TARGET_MB) -> list:
    """전체 훑기 인코딩 argv. 순수 — 테스트 대상.

    ABR(-b:v + maxrate/bufsize)로 크기를 예측 가능하게 한다. faststart 가 없으면
    브라우저가 중간 재생을 위해 파일 전체를 받는다 — 필수다. GOP 는 소스 fps 를
    모르므로 프레임이 아니라 **시간**으로 준다(-g 는 프레임 단위라 keyint_min 과
    함께 -force_key_frames 로 2초마다 박는다).
    fps 는 마스터 소스일 때만(F-206) — 4fps 프록시에 fps=24 를 걸면 같은 그림을
    여섯 번 복제해 비트레이트만 낭비한다. 필터는 fps 가 scale 보다 **앞** —
    버릴 프레임까지 스케일하지 않는다."""
    v = scan_bitrate_kbps(duration_sec, target_mb)
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", src,
            "-vf", (f"fps={fps}," if fps else "") + f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", f"{v}k", "-maxrate", f"{int(v*1.5)}k", "-bufsize", f"{v*2}k",
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-c:a", "aac", "-b:a", f"{SCAN_AUDIO_KBPS}k", "-ac", "1",
            "-movflags", "+faststart", out]


def closeup_cmd(src: str, out: str, start: float, end: float,
                height: int = PREVIEW_H, fps: int | None = CLOSEUP_FPS,
                crf: int = CLOSEUP_CRF) -> list:
    """구간 클로즈업 인코딩 argv. 순수 — 테스트 대상.

    -ss 는 입력 앞(빠른 탐색), -to 는 입력 뒤에 **구간 길이**로 준다 — 앞에 두면
    -ss 와 같은 기준이라 잘리는 지점이 달라진다. fps 는 마스터 소스일 때만
    (scan 과 같은 이유, F-206) — 4fps 프록시에 fps=24 를 걸면 같은 그림을 여섯 번
    복제해 '정밀'을 사칭한다. 필터는 fps 가 scale 보다 앞 — 버릴 프레임까지
    스케일하지 않는다. 키프레임은 2초마다, 프레임(-g)이 아니라 **시간**으로 —
    폴백에선 소스 fps 를 모른다(scan_cmd 와 같은 이유)."""
    return ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, start):.3f}", "-i", src,
            "-t", f"{max(0.0, end - start):.3f}",
            "-vf", (f"fps={fps}," if fps else "") + f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-force_key_frames", "expr:gte(t,n_forced*2)",
            "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", out]


def closeup_windows(clips: list, pad: float = CLOSEUP_PAD,
                    duration_sec: float | None = None,
                    max_total: float = CLOSEUP_MAX_TOTAL) -> list:
    """클립 앞뒤 pad 초 → 병합된 클로즈업 구간. 순수 — 테스트 대상.

    edge_windows 와 달리 **클립 전체**를 감싼다(경계만이 아니라 그 안도 보면서 고쳐야
    한다). 총합이 max_total 을 넘으면 긴 구간부터 버린다 — 4시간물에서 클립이 많으면
    클로즈업만 수백 MB 가 되는데, 그건 전체 프리뷰로 보면 되는 영역이다."""
    marks = []
    for c in clips or []:
        lo = max(0.0, float(c.get("start_sec", 0)) - pad)
        hi = float(c.get("end_sec", 0)) + pad
        if duration_sec:
            hi = min(hi, float(duration_sec))
        if hi > lo:
            marks.append((lo, hi))
    marks.sort()
    merged: list[list[float]] = []
    for lo, hi in marks:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    out = [{"start_sec": round(a, 2), "end_sec": round(b, 2)} for a, b in merged]
    total = sum(w["end_sec"] - w["start_sec"] for w in out)
    while out and total > max_total:
        longest = max(out, key=lambda w: w["end_sec"] - w["start_sec"])
        total -= longest["end_sec"] - longest["start_sec"]
        out.remove(longest)
    return sorted(out, key=lambda w: w["start_sec"])


def pick_master(edit_plan: dict, run_dir: str) -> str | None:
    """클로즈업을 뜰 원본. 없으면 None — 그러면 프록시로 뜬다(4fps 한계). 순수."""
    p = ((edit_plan or {}).get("input") or {}).get("video_path")
    return p if p and os.path.exists(p) else None


def pick_scrub_source(run_dir: str, master_path: str | None = None) -> str | None:
    """스크럽 재료로 쓸 영상 — 480p 프록시 우선, 없으면 마스터. 순수(파일 존재만 봄).

    프록시는 4fps 라 10초 간격 썸네일에 충분하고, 마스터(4~5GB)보다 훨씬 빨리 훑는다.
    타임코드는 프록시가 원본과 1:1 이라(전체 인코딩·CFR) 좌표 변환이 필요 없다."""
    cands = sorted(glob.glob(os.path.join(run_dir, "*_480.mp4")))
    if cands:
        return cands[0]
    return master_path if master_path and os.path.exists(master_path) else None


def pick_scan_source(master: str | None, scrub_src: str | None):
    """전체 훑기(scan)를 뜰 소스 — 마스터 우선. 순수(존재 확인은 호출자 몫).

    스프라이트·파형은 4fps 프록시로 충분하지만(pick_scrub_source), scan 은 사람이
    **재생**하는 영상이라 프록시로 뜨면 4fps 를 물려받아 끊긴다(F-206). 마스터가
    이 노드에 없으면(캐시 GC 뒤) 종전대로 프록시 — 화면이 fps 라벨로 사실을 알린다.
    반환은 **항상** (경로, 마스터 여부) — 호출부가 언팩하므로 None 을 돌려주지
    않는다. scrub_src 존재는 호출자(run)가 보장한다. 클로즈업도 같은 규칙을 쓴다
    (재생 영상은 마스터 우선, 폴백이면 fps 필터 없이 사실대로 기록)."""
    return (master, True) if master else (scrub_src, False)


# ───────── 실행부 ─────────
def run(cfg, conn, job, deps):
    p = job["params"] or {}
    run_id = p.get("run_id")
    review_id = p.get("review_id")
    if not run_id:
        raise base.PermanentError("params.run_id 없음 — 편집실 요청 RPC 확인")

    eng = cfgmod.engine_dir(cfg, "ai_video")
    run_dir = p.get("run_dir") or str(pathlib.Path(eng) / (p.get("outdir") or "outputs") / run_id)
    if not os.path.isdir(run_dir):
        raise base.PermanentError(
            f"run 디렉토리 없음: {run_dir} — 이 노드에 그 run 이 없거나 정리됐습니다")

    plan_path = pathlib.Path(run_dir) / "edit_plan.json"
    if not plan_path.exists():
        raise base.PermanentError(f"edit_plan.json 없음: {run_dir}")
    edit_plan = json.loads(plan_path.read_text(encoding="utf-8"))

    segments = []
    seg_path = pathlib.Path(run_dir) / "subtitle_segments.json"
    if seg_path.exists():
        try:
            segments = json.loads(seg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"[editor] 자막 로드 실패(비치명): {e}")

    src = pick_scrub_source(run_dir, (edit_plan.get("input") or {}).get("video_path"))
    if not src:
        raise base.PermanentError(
            f"스크럽 원본 없음(프록시·마스터 모두): {run_dir} — 프록시는 재생성 가능하나 "
            f"이 잡은 만들지 않는다(무거운 인코딩은 생성 파이프라인 몫)")

    # 내레이션(TTS) cue — 편집실 내레이션 탭 재료. 로드 실패는 비치명(탭이 비어 보일 뿐).
    def _ckpt(name):
        p2 = pathlib.Path(run_dir) / name
        try:
            return json.loads(p2.read_text(encoding="utf-8")) if p2.exists() else None
        except (OSError, ValueError) as e:
            print(f"[editor] {name} 로드 실패(비치명): {e}")
            return None

    duration = _probe_duration(src)
    tl = timeline_from_plan(edit_plan, segments, duration)
    tl["tts"] = tts_from_checkpoints(_ckpt("checkpoint_resources.json"),
                                     _ckpt("checkpoint_silence_cut.json"))
    layout = sprite_layout(duration)
    edges = edge_windows(tl["clips"], duration_sec=duration)

    work = pathlib.Path(cfg.home) / "cache" / "editor" / run_id
    work.mkdir(parents=True, exist_ok=True)
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    assets: dict = {"global": [], "edges": [], "wave": None}

    # 전역 스프라이트
    if layout["count"]:
        pat = str(work / "g_%03d.jpg")
        _ffmpeg(sprite_cmd(src, pat, GLOBAL_INTERVAL))
        assets["global"] = _upload_seq(store, run_id, "g", sorted(work.glob("g_*.jpg")))

    # 경계 밀집 스프라이트 — 구간별로 따로 뜨고, 어느 구간인지 함께 기록
    for wi, w in enumerate(edges):
        pat = str(work / f"e{wi}_%03d.jpg")
        _ffmpeg(sprite_cmd(src, pat, EDGE_INTERVAL,
                           start=w["start_sec"], end=w["end_sec"]))
        keys = _upload_seq(store, run_id, f"e{wi}", sorted(work.glob(f"e{wi}_*.jpg")))
        if keys:
            assets["edges"].append({**w, "interval": EDGE_INTERVAL, "grid": GRID,
                                    "thumb_w": THUMB_W, "keys": keys})

    # 파형
    wav_out = work / "wave.png"
    try:
        _ffmpeg(wave_cmd(src, str(wav_out)))
        if wav_out.exists():
            wkey = f"{base.storage_key(run_id, 'editor')}/wave.png"
            store.upload("ves-outputs", wkey, str(wav_out))
            assets["wave"] = wkey
    except RuntimeError as e:      # 무음 트랙이면 실패할 수 있다 — 파형 없이 진행
        print(f"[editor] 파형 생성 실패(비치명): {e}")

    # 편집 프리뷰 — 실패해도 편집실은 열려야 한다(스프라이트로 보기는 된다)
    assets["media"] = _build_media(cfg, store, run_id, run_dir, src,
                                   pick_master(edit_plan, run_dir), tl, duration, work)

    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.editor_assets
                   (run_id, work_order_id, review_id, status, duration_sec,
                    timeline, sprites, node_id, expires_at, updated_at)
               VALUES (%s,%s,%s,'ready',%s,%s::jsonb,%s::jsonb,%s, now() + %s::interval, now())
               ON CONFLICT (run_id) DO UPDATE SET
                   work_order_id=excluded.work_order_id, review_id=excluded.review_id,
                   status='ready', duration_sec=excluded.duration_sec,
                   timeline=excluded.timeline, sprites=excluded.sprites,
                   node_id=excluded.node_id, error=NULL,
                   expires_at=excluded.expires_at, updated_at=now()""",
            (run_id, job.get("work_order_id"), review_id, duration,
             json.dumps(tl, ensure_ascii=False),
             json.dumps({**layout, "assets": assets}, ensure_ascii=False),
             cfg.node_id, ASSET_TTL))
    # 스토리지 GC 가 치우도록 카탈로그에도 남긴다(대표 1건 — 시트는 같은 접두사)
    _catalog(conn, job, run_id, assets)
    med = assets.get("media") or {}
    print(f"[editor] 준비 완료 — 길이 {duration:.0f}s · 전역 시트 {len(assets['global'])}장 · "
          f"경계 구간 {len(assets['edges'])}개 · 프리뷰 {med.get('scan_bytes',0)/1e6:.0f}MB · "
          f"클로즈업 {len(med.get('closeups') or [])}개")
    return {"run_id": run_id, "duration_sec": duration,
            "sheets": len(assets["global"]), "edge_windows": len(assets["edges"]),
            "wave": bool(assets["wave"]),
            "scan_mb": round(med.get("scan_bytes", 0) / 1e6, 1),
            "closeups": len(med.get("closeups") or []),
            "closeup_mb": round(sum(c.get("bytes", 0) for c in (med.get("closeups") or [])) / 1e6, 1)}


def _build_media(cfg, store, run_id, run_dir, scrub_src, master, tl, duration, work) -> dict:
    """편집 프리뷰(전체 + 구간 클로즈업) 생성·업로드. 실패는 비치명 — 보기는 스프라이트로
    되므로 편집실 자체를 막지 않는다. 반환값이 그대로 sprites.assets.media 에 들어간다."""
    media: dict = {"scan": None, "scan_bytes": 0, "closeups": [], "source": None}
    prefix = base.storage_key(run_id, "editor")

    # ① 전체 프리뷰 — 목표 용량에 맞춰 360p 로 다시 뜬다(리먹스는 2GB 가 된다).
    #    소스는 마스터 우선(F-206) — 프록시로 뜨면 4fps 를 물려받아 재생이 끊긴다.
    try:
        scan_src, scan_hq = pick_scan_source(master, scrub_src)
        # 비트레이트 역산은 **인코딩 소스의 길이** 기준 — 프록시가 부분 인코딩된 run 이면
        # 프록시 길이로 역산한 비트레이트가 마스터 전체 길이에서 목표 용량을 넘긴다.
        scan_dur = _probe_duration(scan_src) if scan_hq else duration
        target = SCAN_TARGET_MB if scan_hq else SCAN_TARGET_MB_PROXY
        kbps = scan_bitrate_kbps(scan_dur, target)
        scan_out = work / "scan.mp4"
        _ffmpeg(scan_cmd(scan_src, str(scan_out), scan_dur,
                         fps=SCAN_FPS if scan_hq else None, target_mb=target),
                timeout=SCAN_TIMEOUT_SEC)
        size = scan_out.stat().st_size
        if size > SCAN_MAX_BYTES:
            print(f"[editor] 전체 프리뷰 {size/1e6:.0f}MB — 상한 초과, 올리지 않음")
            scan_out.unlink(missing_ok=True)
        else:
            key = f"{prefix}/scan.mp4"
            store.upload("ves-outputs", key, str(scan_out))
            media.update(scan=key, scan_bytes=size,
                         source="master" if scan_hq else "proxy",
                         scan_fps=SCAN_FPS if scan_hq else _probe_fps(scan_src),
                         scan_gen=SCAN_GEN, scan_kbps=kbps)
            print(f"[editor] 전체 프리뷰 {size/1e6:.1f}MB ({kbps}kbps · "
                  f"{'master ' + str(SCAN_FPS) + 'fps' if scan_hq else 'proxy'}) 업로드")
            scan_out.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001
        print(f"[editor] 전체 프리뷰 실패(비치명): {e}")

    # ② 구간 클로즈업 — 마스터가 있으면 마스터에서(움직임이 살아 있다), 없으면 프록시에서.
    #    fps=24 는 scan 과 같은 규칙(F-206) — 프록시 폴백에 걸면 4fps 를 여섯 배 복제해
    #    메타·라벨이 '정밀 구간(24fps)'을 사칭한다(사용자가 F-206 증상을 새 버그로 오인).
    #    폴백은 소스 fps 그대로 뜨고 실제 값을 기록해 화면 라벨이 사실을 말하게 한다.
    csrc, chq = pick_scan_source(master, scrub_src)
    media["closeup_source"] = "master" if chq else "proxy"
    cfps = CLOSEUP_FPS if chq else _probe_fps(csrc)
    media["closeup_fps"] = cfps
    for wi, w in enumerate(closeup_windows(tl.get("clips"), duration_sec=duration)):
        out = work / f"c{wi}.mp4"
        try:
            _ffmpeg(closeup_cmd(csrc, str(out), w["start_sec"], w["end_sec"],
                                fps=CLOSEUP_FPS if chq else None))
            key = f"{prefix}/c{wi}.mp4"
            store.upload("ves-outputs", key, str(out))
            media["closeups"].append({**w, "key": key, "bytes": out.stat().st_size,
                                      "fps": cfps})
            out.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001
            print(f"[editor] 클로즈업 {wi} 실패(비치명): {e}")
            out.unlink(missing_ok=True)
    if media["closeups"]:
        mb = sum(c["bytes"] for c in media["closeups"]) / 1e6
        print(f"[editor] 클로즈업 {len(media['closeups'])}개 {mb:.1f}MB "
              f"({media['closeup_source']} · {cfps or '?'}fps)")
    return media


def _catalog(conn, job, run_id, assets):
    total = len(assets.get("global") or []) + sum(
        len(e.get("keys") or []) for e in (assets.get("edges") or []))
    if not total:
        return
    try:
        # DO UPDATE 인 이유: 재워밍(만료 하루 전 재생성, 0045/0048 RPC)이 화면 TTL
        # (editor_assets.expires_at)을 +7일로 다시 미는데, 카탈로그가 DO NOTHING 으로
        # 최초 시각에 머물면 GC 가 화면이 아직 서명 URL 로 쓰는 재료를 지운다.
        # 두 TTL 은 항상 같이 민다.
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.artifacts
                       (job_id, work_order_id, kind, sha256, bytes, bucket, object_key,
                        expires_at)
                   VALUES (%s,%s,'editor_assets',%s,0,'ves-outputs',%s, now() + %s::interval)
                   ON CONFLICT (sha256, kind) DO UPDATE SET
                       expires_at = excluded.expires_at, job_id = excluded.job_id,
                       work_order_id = excluded.work_order_id""",
                (job["id"], job.get("work_order_id"), f"editor:{run_id}",
                 f"{base.storage_key(run_id, 'editor')}/", ASSET_TTL))
    except Exception as e:  # noqa: BLE001 — 카탈로그 실패가 편집실을 막지 않는다
        print(f"[editor] 카탈로그 등록 실패(비치명): {e}")


def _upload_seq(store, run_id, kind, paths) -> list:
    keys = []
    for n, f in enumerate(paths):
        k = sprite_key(run_id, kind, n)
        store.upload("ves-outputs", k, str(f))
        keys.append(k)
        f.unlink(missing_ok=True)
    return keys


def _ffmpeg(argv, timeout: float = TIMEOUT_SEC):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패: {(r.stderr or r.stdout)[-300:]}")


def _ffprobe_entry(path: str, entries: str, select: str | None = None) -> str:
    """ffprobe 단일 항목 조회 — probe 헬퍼들의 공통 스캐폴딩(정책은 각자 유지)."""
    argv = ["ffprobe", "-v", "error"]
    if select:
        argv += ["-select_streams", select]
    argv += ["-show_entries", entries, "-of", "default=nw=1:nk=1", path]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    return (r.stdout or "").strip()


def _probe_fps(path: str) -> float | None:
    """영상 fps — 화면 라벨용 메타일 뿐이라 실패해도 None(재료 생성을 막지 않는다)."""
    try:
        num, _, den = _ffprobe_entry(path, "stream=avg_frame_rate", "v:0").partition("/")
        f = float(num) / float(den or 1)
        return round(f, 2) if f > 0 else None
    except (ValueError, ZeroDivisionError, subprocess.SubprocessError, OSError):
        return None


def _probe_duration(path: str) -> float:
    try:
        return float(_ffprobe_entry(path, "format=duration") or "0")
    except ValueError:
        raise base.PermanentError(f"길이 판독 실패: {path}") from None


def on_failure(cfg, conn, job, error: str) -> None:
    """실패도 화면에 남긴다 — 편집실이 '준비 중' 상태로 영원히 도는 것보다 낫다."""
    try:
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.editor_assets
                       (run_id, work_order_id, review_id, status, error, updated_at)
                   VALUES (%s,%s,%s,'failed',%s, now())
                   ON CONFLICT (run_id) DO UPDATE SET status='failed',
                       error=excluded.error, updated_at=now()""",
                ((job["params"] or {}).get("run_id"), job.get("work_order_id"),
                 (job["params"] or {}).get("review_id"), (error or "")[:500]))
    except Exception as e:  # noqa: BLE001
        print(f"[editor] 실패 기록 실패: {e}")
