#!/usr/bin/env python3
"""zanmang_autopilot 어댑터 — 잔망루피 현지화 autopilot 실행 (subprocess 형, 2026-08-10).

구 파이프라인을 재작성하지 않고 편입한다: 그 레포의 .venv 로 `src.autopilot <task>` 를
그대로 실행 — 원장(outputs/autopilot.db)·YouTube 토큰·가중치 전부 기존 위치를 쓴다.
관제에는 성공/실패·단계별 건수가 남고, 승인(approve)은 종전대로 사람이 그 레포 CLI 로.

⚠ 이 CLI 는 진행 로그를 전부 logging(=stderr) 으로 낸다 — WANT_STDERR 로 stderr 를
받아 요약한다(8/11 실측: 성공했는데 stdout 이 비어 '무슨 일이 있었는지' 알 수 없었다).
"""
from __future__ import annotations

import pathlib
import re

from ves.adapters import base

WANT_STDERR = True                       # executor 계약: parse_result(cfg, job, out, err)
DEFAULT_REPO = "/opt/ves/engines/video-localization-project"
TASKS = ("daily", "status", "scan", "score", "report", "pending")

# 로그 한 줄 → 관제에 남길 지표 (원문 문구는 src/autopilot.py 의 log.info 계약)
_METRICS = [
    ("scanned",   re.compile(r"scan 완료: 수집 (\d+)편")),
    ("new",       re.compile(r"scan 완료: 수집 \d+편, 신규 (\d+)편")),
    ("scored",    re.compile(r"scor\w*[: ]+(\d+)\s*편")),
    ("processed", re.compile(r"process\w*[: ]+(\d+)\s*편")),
    ("approved",  re.compile(r"승인[^0-9]{0,10}(\d+)\s*편")),
    ("uploaded",  re.compile(r"업로드[^0-9]{0,10}(\d+)\s*편")),
]


def daily_argv(repo: str, task: str = "daily") -> list:
    """autopilot 실행 argv. 순수 — 테스트 대상. 허용 task 만(임의 실행 차단)."""
    if task not in TASKS:
        raise base.PermanentError(f"허용되지 않은 task: {task} (허용: {', '.join(TASKS)})")
    return [f"{repo}/.venv/bin/python", "-m", "src.autopilot", task]


def summarize(stderr: str) -> dict:
    """진행 로그(stderr) → 지표 dict + 마지막 줄들. 순수 — 테스트 대상."""
    text = stderr or ""
    out = {}
    for key, rx in _METRICS:
        m = rx.search(text)
        if m:
            out[key] = int(m.group(1))
    lines = [ln for ln in text.splitlines() if ln.strip()]
    out["log_tail"] = "\n".join(lines[-12:])[-900:]
    out["idle"] = not any(v for k, v in out.items() if k != "log_tail" and isinstance(v, int))
    return out


def cwd(cfg, job):
    return (job["params"] or {}).get("repo") or DEFAULT_REPO


def build_argv(cfg, job):
    repo = cwd(cfg, job)
    if not pathlib.Path(f"{repo}/.venv/bin/python").exists():
        raise base.PermanentError(
            f"잔망루피 레포 .venv 없음: {repo} — ops_config zanmang_repo 확인")
    return daily_argv(repo, (job["params"] or {}).get("task") or "daily")


def parse_result(cfg, job, stdout, stderr=""):
    res = summarize(stderr)
    if stdout:
        res["stdout_tail"] = stdout[-400:]
    return res


def classify_error(rc, stderr, stdout):
    blob = (stderr or "") + (stdout or "")
    if "quota" in blob.lower() or "uploadLimitExceeded" in blob:
        return "quota"
    return base.classify_by_patterns(stderr, stdout)
