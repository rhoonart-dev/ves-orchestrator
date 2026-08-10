#!/usr/bin/env python3
"""zanmang_autopilot 어댑터 — 잔망루피 현지화 autopilot 실행 (subprocess 형, 2026-08-10).

구 파이프라인을 재작성하지 않고 편입한다: 그 레포의 .venv 로 `src.autopilot daily` 를
그대로 실행 — 원장(outputs/autopilot.db)·YouTube 토큰·가중치 전부 기존 위치를 쓴다.
관제에는 성공/실패·로그 꼬리가 남고, 승인(approve)은 종전대로 사람이 그 레포 CLI 로.
"""
from __future__ import annotations

import pathlib

from ves.adapters import base


def daily_argv(repo: str) -> list:
    """autopilot daily 실행 argv. 순수 — 테스트 대상."""
    return [f"{repo}/.venv/bin/python", "-m", "src.autopilot", "daily"]


def cwd(cfg, job):
    return (job["params"] or {}).get("repo") or "/Users/steve/dev/video-localization-project"


def build_argv(cfg, job):
    repo = cwd(cfg, job)
    if not pathlib.Path(f"{repo}/.venv/bin/python").exists():
        raise base.PermanentError(
            f"잔망루피 레포 .venv 없음: {repo} — ops_config zanmang_repo 확인")
    return daily_argv(repo)


def parse_result(cfg, job, stdout):
    return {"stdout_tail": (stdout or "")[-500:]}


def classify_error(rc, stderr, stdout):
    blob = (stderr or "") + (stdout or "")
    if "quota" in blob.lower() or "uploadLimitExceeded" in blob:
        return "quota"
    return base.classify_by_patterns(stderr, stdout)
