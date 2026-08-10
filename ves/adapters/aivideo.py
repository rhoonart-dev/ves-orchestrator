#!/usr/bin/env python3
"""generate 어댑터 — ai-video app.cli create_shorts (subprocess 형).

params 계약(planner 가 채움):
  work_title(laeebly 정본) · source_sha256 | source_url · episode · max_shorts
  topic · no_research(기본 true) · no_subtitles(sources.has_subtitle=false 면 true)
  flags{silence,length,loudness} — 라운드 노브(§12) · resource('gemini:<GCP>')
경로: 소스는 content-addressed 캐시(sha 만으로 결정) — acquire 가 워밍, 여기선 경로 계산만.
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import re

from ves import config as cfgmod
from ves.adapters import base

# ai-video 14단계 순서 — 재개 스텝 선택(★⑦)의 기준 (README 파이프라인 표)
STEP_ORDER = ["research", "probe", "proxy", "chunk", "character_index",
              "chunk_transcribe", "gemini", "graph", "story", "silence_cut",
              "resources", "render", "validate"]

_RUNLOG_RE = re.compile(r"([^/\s]+)/run_log\.json")

# 이 잡의 산출물(run_dir)을 로컬에서 읽는 후속 kind — executor 가 완료 시 이 노드로 고정
# (upload=글롭, ingest/evaluate=--run-dir. publish 는 검수 후 별도 생성이라 대상 밖 —
#  스토리지 폴백(Phase 2)이 정답이며, 그 전까지는 같은 노드 유지가 사실상 강제됨)
PIN_DEPENDENT_KINDS = ("upload_artifacts", "ingest", "evaluate")


def branding_flags(card, policy) -> list:
    """작품 카드 branding.logo → --design-work-image 플래그 (가이드 자동화 2026-08-10).
    규약 정본은 brain channel_registry.py(§로고) — 여기와 그쪽이 같은 works.json 을 읽으므로
    scene_loop 과 신규 파이프라인의 로고가 항상 일치한다. 카드에 logo 없으면 텍스트(종전)."""
    brand = ((card or {}).get("branding") or {})
    if not brand.get("logo"):
        return []
    flags = ["--design-work-image", str(brand["logo"])]
    box = brand.get("box") or (policy or {}).get("logo_box")
    if box and "x" in str(box).lower():
        w, h = str(box).lower().split("x", 1)
        try:
            flags += ["--design-work-image-width", str(int(w)),
                      "--design-work-image-height", str(int(h))]
        except ValueError:
            pass
    align = brand.get("align") or (policy or {}).get("logo_align")
    if align in ("top", "center"):
        flags += ["--design-work-align", str(align)]
    return flags


def _brain_json(cfg, name):
    p = pathlib.Path(cfgmod.engine_dir(cfg, "brain")) / "config" / name
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw.get("works", raw) if isinstance(raw, dict) and "works" in raw else raw
    except (OSError, json.JSONDecodeError):
        return {}


# ───────── 순수 (테스트 대상) ─────────
def build_argv_pure(py: str, params: dict, source_path: str | None) -> list:
    p = params
    cmd = [py, "-u", "-m", "app.cli", "create_shorts",
           "--title", p["work_title"],
           "--max-shorts", str(p.get("max_shorts") or 1)]
    if source_path:
        cmd += ["--video", source_path]
    elif p.get("source_url"):
        cmd += ["--youtube-url", p["source_url"]]
    if p.get("topic"):
        cmd += ["--topic", p["topic"]]
    if p.get("episode") is not None:
        cmd += ["--episode", str(p["episode"])]
    if p.get("no_research", True):
        cmd += ["--no-research"]
    if p.get("no_subtitles"):        # 자막 미제공 작품 합의(brain CLAUDE.md §5)
        cmd += ["--no-subtitles"]
    f = p.get("flags") or {}
    if f.get("silence"):
        cmd += ["--silence-profile", f["silence"]]
    if f.get("length"):
        cmd += ["--length-profile", f["length"]]
    if f.get("loudness"):
        cmd += ["--loudness-lufs", str(f["loudness"])]
    cmd += ["--outdir", p.get("outdir") or "outputs"]
    return cmd


def pick_resume_step(checkpoint_filenames) -> str | None:
    """checkpoint_<step>.json 목록 → --from-step 값(마지막 완료 스텝 재실행부터).
    없으면 None(처음부터)."""
    done = []
    for fn in checkpoint_filenames:
        name = str(fn).rsplit("/", 1)[-1]
        if name.startswith("checkpoint_") and name.endswith(".json"):
            step = name[len("checkpoint_"):-len(".json")]
            if step in STEP_ORDER:
                done.append(step)
    if not done:
        return None
    return max(done, key=STEP_ORDER.index)


def extract_partial_run_id(stdout: str) -> str | None:
    """실패 출력에서도 run 디렉토리명 회수 — 재개(★⑦)의 근거. autogen.parse_job_id 계약."""
    m = _RUNLOG_RE.search(stdout or "")
    return m.group(1) if m else None


def provenance_ok(run_log: dict) -> bool:
    """R8 판정 — ai-video run_log 실제 스키마는 {input, steps, job_id, provenance}
    (스모크3 실측: 최상위 'provenance_complete' 키는 존재한 적이 없다. 그 키를 읽던
    종전 코드는 건강한 런을 전부 막았다). ingest(T0-2)와 같은 기준을 쓴다:
    provenance 에 git_sha 와 config 스냅샷이 있으면 완전. 레거시 키는 관용 허용."""
    rl = run_log or {}
    prov = rl.get("provenance") or {}
    if bool(prov.get("git_sha")) and bool(prov.get("config")):
        return True
    return bool(rl.get("provenance_complete"))   # 레거시/미래 엔진 호환


# ───────── 어댑터 인터페이스 ─────────
def cwd(cfg, job):
    return cfgmod.engine_dir(cfg, "ai_video")


def env(cfg, job):
    e = dict(os.environ)
    e["AI_VIDEO_ROOT"] = cfgmod.engine_dir(cfg, "ai_video")
    return e


def resource(cfg, job):
    return (job.get("params") or {}).get("resource")   # 'gemini:VES01' — planner 가 채움(§7)


def build_argv(cfg, job):
    p = job["params"]
    src = cfgmod.source_cache_path(cfg, p["source_sha256"]) if p.get("source_sha256") else None
    if src and not pathlib.Path(src).exists():
        raise base.PermanentError(f"소스 캐시 없음: {src} — acquire 선행 확인")
    argv = build_argv_pure(cfgmod.engine_py(cfg, "ai_video"), p, src)
    # 로고(가이드 자동화): 작품 카드에 branding.logo 가 있으면 scene_loop 과 같은 플래그
    argv += branding_flags(_brain_json(cfg, "works.json").get(p.get("work_title")),
                           _brain_json(cfg, "loop_policy.json"))
    return argv


def resume_argv(cfg, job, partial_run_id):
    """★⑦ 재시도는 이어달리기 — 같은 run_id 로 마지막 체크포인트부터."""
    argv = build_argv(cfg, job)
    outdir = (job["params"].get("outdir") or "outputs")
    run_dir = pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / outdir / partial_run_id
    step = pick_resume_step(glob.glob(str(run_dir / "checkpoint_*.json")))
    argv += ["--job-id", partial_run_id]
    if step:
        argv += ["--from-step", step]
    return argv


def parse_result(cfg, job, stdout):
    rid = extract_partial_run_id(stdout)
    if not rid:
        raise base.PermanentError("stdout 에서 run_id 를 못 찾음 — ai-video 출력 계약 확인")
    outdir = (job["params"].get("outdir") or "outputs")
    run_dir = pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / outdir / rid
    run_log = {}
    rl = run_dir / "run_log.json"
    if rl.exists():
        try:
            run_log = json.loads(rl.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            run_log = {}
    if not provenance_ok(run_log):   # R8: provenance 없이 succeeded 불가
        raise base.PermanentError(
            f"provenance 불완전(provenance.git_sha/config 스냅샷 없음) — R8 (run={rid})")
    return {"run_id": rid, "run_dir": str(run_dir), "provenance_complete": True}


def classify_error(rc, stderr, stdout):
    return base.classify_by_patterns(stderr, stdout)


def is_already_done(cfg, job):
    """멱등: 직전 성공 run 이 있으면 스킵 — result 에 run_id 가 남아있는 경우."""
    rid = ((job.get("result") or {}).get("run_id"))
    if not rid:
        return False
    outdir = (job["params"].get("outdir") or "outputs")
    rl = pathlib.Path(cfgmod.engine_dir(cfg, "ai_video")) / outdir / rid / "run_log.json"
    return rl.exists()
