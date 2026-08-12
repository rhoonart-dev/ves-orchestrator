#!/usr/bin/env python3
"""Slack 알림 — 사람이 지금 알아야 하는 것만 (updater.py 의 TODO(Phase 2) 이행).

원칙: **알림 실패가 본 작업을 절대 죽이지 않는다.** 웹훅이 없으면 로그만 남기고 조용히 넘어간다.
웹훅 URL 은 종전대로 env 파일에만 둔다(ves.env 의 SLACK_WEBHOOK_URL — ARCHITECTURE §5).
"""
from __future__ import annotations

import json
import os
import urllib.request

TIMEOUT_SEC = 5


def alert(text: str) -> bool:
    """[ALERT] 로 찍고 Slack 에도 보낸다. 실제로 보냈으면 True.

    로그 접두사를 [ALERT] 로 맞춘 이유: 기존 updater·planner·source_watch 가 이미 이 접두사로
    남기고 있어서, 웹훅이 없는 환경에서도 같은 방식으로 찾을 수 있다.
    """
    print(f"[ALERT] {text}")
    url = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    if not url:
        return False
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as r:   # noqa: S310 — 고정 웹훅
            return 200 <= getattr(r, "status", 0) < 300
    except Exception as e:  # noqa: BLE001 — 알림 실패가 본 작업을 죽이지 않는다
        print(f"[notify] Slack 전송 실패(무시): {type(e).__name__} {e}")
        return False
