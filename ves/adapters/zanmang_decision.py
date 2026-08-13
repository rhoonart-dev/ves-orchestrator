#!/usr/bin/env python3
"""zanmang_decision 어댑터 — 관제 검수함의 잔망루피 결정을 원장에 확정한다 (2026-08-12).

검수함에서 사람이 누른 것을 video-localization-project 원장에 반영하는 실행부다.
그 레포는 재작성하지 않는다 — 이미 승인과 업로드가 나뉘어 있어서 CLI 를 그대로 부른다.

  승인: `approve <id>`(업로드 패키지 생성 → approved) → `upload <id>`(비공개 업로드 +
        19:00 JST 다음 빈 슬롯으로 예약 공개). 공개 '결정'은 사람이 이미 했고 여기는 기계적 실행.
  반려: `mark --state skipped <id>` — 안 하면 다음 daily 가 같은 건을 또 검수함에 올린다.

네이티브형인 이유: 승인은 두 명령(approve→upload)을 순서대로 돌려야 하고, 그 사이에
원장 상태를 봐야 하기 때문이다(중간에 죽어도 다시 돌릴 수 있게 — 아래 멱등 규칙).

멱등(재시도 안전):
  · 이미 approved 면 approve 를 건너뛰고 upload 만 — 패키지 재생성으로 시간 낭비하지 않는다.
  · 이미 uploaded 면 아무것도 하지 않고 성공 — 같은 영상을 두 번 올리지 않는다(R10 사고 방지).
"""
from __future__ import annotations

import pathlib
import re
import subprocess

from ves.adapters import base
from ves.adapters import zanmang

TIMEOUT_SEC = 60 * 30          # 패키지 생성 + 업로드. 현지화(수십 분)는 이미 끝난 뒤다.
_URL_RE = re.compile(r"https://youtu\.be/([A-Za-z0-9_-]{6,})")


# ───────── 순수 (테스트 대상) ─────────
def plan(state: str, action: str) -> list:
    """원장 상태 + 결정 → 실행할 task 목록. 순수 — 테스트 대상.

    이 표가 멱등의 전부다. 알 수 없는 상태면 빈 목록(사람이 봐야 한다)."""
    if action == "skip":
        return [] if state in ("skipped", "uploaded") else ["mark"]
    if action != "publish":
        raise base.PermanentError(f"알 수 없는 결정: {action}")
    if state == "uploaded":
        return []                       # 이미 올라갔다 — 재업로드 금지
    if state == "approved":
        return ["upload"]               # 패키지는 있다 — 업로드만
    if state == "pending_approval":
        return ["approve", "upload"]
    return []                           # processing/failed 등 — 손대지 않는다


def parse_youtube_url(stdout: str):
    """upload 로그에서 게시 URL 추출. 순수 — 테스트 대상."""
    m = _URL_RE.search(stdout or "")
    return m.group(0) if m else None


# ───────── 실행부 ─────────
def _ledger_state(repo, video_id):
    rows = zanmang.pending_rows(pathlib.Path(repo) / zanmang.LEDGER_REL)
    if any(r["video_id"] == video_id for r in rows):
        return "pending_approval"
    import sqlite3
    p = pathlib.Path(repo) / zanmang.LEDGER_REL
    if not p.exists():
        raise base.PermanentError(f"원장 없음: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT state FROM videos WHERE video_id=?", (video_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise base.PermanentError(f"원장에 없는 video_id: {video_id}")
    return row[0]


def run(cfg, conn, job, deps):
    p = job["params"] or {}
    vid = p.get("video_id")
    action = p.get("action") or "publish"
    repo = p.get("repo") or zanmang.DEFAULT_REPO
    if not vid:
        raise base.PermanentError("params.video_id 없음")
    if not pathlib.Path(f"{repo}/.venv/bin/python").exists():
        raise base.PermanentError(f"잔망루피 레포 .venv 없음: {repo}")

    state = _ledger_state(repo, vid)
    tasks = plan(state, action)
    if not tasks:
        return {"video_id": vid, "action": action, "state": state, "skipped": True,
                "note": f"원장 상태 '{state}' — 할 일 없음(이미 반영됨)"}

    out = {"video_id": vid, "action": action, "from_state": state, "ran": []}
    for task in tasks:
        argv = zanmang.action_argv(repo, task, vid,
                                   state="skipped" if task == "mark" else None,
                                   privacy=p.get("privacy") if task == "upload" else None,
                                   publish_at=p.get("publish_at") if task == "upload" else None)
        r = subprocess.run(argv, cwd=repo, capture_output=True, text=True,
                           timeout=TIMEOUT_SEC)
        tail = ((r.stdout or "") + "\n" + (r.stderr or ""))[-500:]
        if r.returncode != 0:
            cls = base.classify_by_patterns(r.stderr or "", r.stdout or "")
            msg = f"{task} 실패: {tail}"
            if cls == "permanent":
                raise base.PermanentError(msg)
            if cls == "quota":
                raise base.QuotaError(msg)     # 유튜브 업로드 한도 — 내일 다시
            raise RuntimeError(msg)
        out["ran"].append(task)
        if task == "upload":
            url = parse_youtube_url(r.stdout or "")
            if url:
                out["youtube_url"] = url
        out[f"{task}_tail"] = tail[-200:]
    return out
