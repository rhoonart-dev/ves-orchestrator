#!/usr/bin/env python3
"""localize 어댑터 — video-localization-project (subprocess 형, mm-06 전담 caps:localize).

Phase 3 통합 대상: SQLite 원장(8상태)을 job_queue/review_queue 로 사상하고
QA hold → review_queue(kind='localization_qa') 로 승격한다.
스켈레톤: process_video Level B 경로만. 실측 판별(precheck)·더빙(C)은 Phase 3 에서 배선.
"""
from __future__ import annotations

import os

from ves import config as cfgmod
from ves.adapters import base


def cwd(cfg, job):
    return cfgmod.engine_dir(cfg, "localization")


def env(cfg, job):
    return dict(os.environ)


def build_argv(cfg, job):
    p = job["params"]
    return [cfgmod.engine_py(cfg, "localization"), "-m", "src.process_video",
            "--video", p["video_path"], "--video-id", p["video_id"],
            "--level", p.get("level", "B"),
            "--content-type", p.get("content_type", "mukbang"),
            "--backend", p.get("backend", "lama")]


def parse_result(cfg, job, stdout):
    return {"stdout_tail": (stdout or "")[-400:]}


def classify_error(rc, stderr, stdout):
    blob = (stderr or "").lower()
    if "cuda" in blob or "mps" in blob or "weight" in blob:
        return "permanent"    # 가중치/GPU 미구성 — 재시도 무의미, 노드 셋업 문제
    return base.classify_by_patterns(stderr, stdout)
