#!/usr/bin/env python3
"""diskgc — 노드 로컬 디스크 청소 (2026-08-11, 컷오버 후 신설).

왜 필요한가: storage_gc 는 Supabase Storage 만 치운다. 맥 로컬은 아무도 안 치웠고,
매일 20편 생산 + 마스터 캐시(편당 2~3GB)가 쌓여 8/11 mm-01·mm-02 가 디스크 0 으로
멈췄다(인입·생성 전멸). 워커가 스스로 6시간마다 돈다 — 스케줄러 잡이 아니라
루프 안에 두는 이유: 청소는 '그 노드의 자기 디스크' 문제라 큐를 거칠 이유가 없고,
큐가 막혔을 때(디스크 부족이 원인일 때)도 반드시 돌아야 한다.

안전 근거: 로컬 산출물이 지워져도 발행은 Storage 폴백으로 살아 있고(brain.Publish),
소스는 sha 로 다시 받으면 되며(acquire), 인입 캐시는 file_id 로 중복이 걸러진다.
"""
from __future__ import annotations

import os
import pathlib
import shutil
import time

GB = 1000 ** 3

# (상대경로, 보존일) — 홈($VES_HOME) 기준. 보존일 지난 '최상위 항목'만 지운다.
RULES = (
    ("cache/sources", 14),                    # 마스터 원본(2~3GB) — 회차 재사용 여유 2주
    ("engines/ai-video/outputs", 10),         # 생성 산출물 — 검수 지연 여유 10일
    ("cache/drive_sync", 3),                  # 인입 캐시(성공 시엔 어댑터가 즉시 반환)
    ("cache/publish", 2),                     # 발행 폴백 사본
    ("cache/localize", 2),                    # 현지화 작업본
    ("cache/drive_tmp", 1),                   # 인입 임시파일
)
EMERGENCY_FREE_GB = 25    # 이 아래면 보존일 무시하고 오래된 순으로 더 지운다
EMERGENCY_TARGET_GB = 60  # 이만큼 확보되면 멈춘다
INTERVAL_SEC = 6 * 3600


# ───────── 순수 (테스트 대상) ─────────
def expired(entries, now_ts: float, keep_days: int) -> list:
    """[(경로, mtime)] → 보존일 지난 경로들. 순수."""
    cutoff = now_ts - keep_days * 86400
    return [p for p, m in (entries or []) if m < cutoff]


def emergency_plan(entries, free_bytes: int,
                   floor_gb: int = EMERGENCY_FREE_GB,
                   target_gb: int = EMERGENCY_TARGET_GB) -> list:
    """여유가 floor 미만이면 오래된 순으로 target 까지 채울 만큼 고른다.
    [(경로, mtime, 크기)] 입력. 순수 — 테스트 대상."""
    if free_bytes >= floor_gb * GB:
        return []
    need = target_gb * GB - free_bytes
    picked, freed = [], 0
    for p, _m, size in sorted(entries or [], key=lambda e: e[1]):
        if freed >= need:
            break
        picked.append(p)
        freed += size
    return picked


# ───────── 실행부 ─────────
def _entries(root: pathlib.Path):
    out = []
    try:
        for p in root.iterdir():
            try:
                out.append((p, p.stat().st_mtime))
            except OSError:
                pass
    except OSError:
        pass
    return out


def _size(p: pathlib.Path) -> int:
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(p, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def _rm(p: pathlib.Path) -> None:
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        try:
            p.unlink()
        except OSError:
            pass


def run(cfg) -> dict:
    home = pathlib.Path(cfg.home)
    removed, bytes_freed = 0, 0
    for rel, keep_days in RULES:
        root = home / rel
        if not root.is_dir():
            continue
        for p in expired(_entries(root), time.time(), keep_days):
            bytes_freed += _size(p)
            _rm(p)
            removed += 1

    try:
        free = shutil.disk_usage(str(home)).free
    except OSError:
        free = EMERGENCY_FREE_GB * GB
    if free < EMERGENCY_FREE_GB * GB:
        pool = []
        for rel, _d in RULES:
            root = home / rel
            if root.is_dir():
                pool += [(p, m, _size(p)) for p, m in _entries(root)]
        for p in emergency_plan(pool, free):
            bytes_freed += _size(p)
            _rm(p)
            removed += 1

    if removed:
        print(f"[diskgc] {removed}건 삭제 · {bytes_freed / GB:.1f}GB 회수")
    return {"removed": removed, "gb": round(bytes_freed / GB, 1)}
