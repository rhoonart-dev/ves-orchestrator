#!/usr/bin/env python3
"""drive_watch — 매일 새 드라이브 소스 감지 (0013, 사용자 요청 2026-08-10).

두 원천을 훑어 sync_drive_folder 잡을 만든다(무거운 일은 워커가):
  1) 외부 작품 폴더: ops_config.drive_watch_folder — 하위폴더명 = 작품명 규약
  2) laeebly 드라이브형: channels.json 배정 작품의 licensed_video.download_link 폴더
멱등: (폴더, 날짜) 해시 키 — 하루 1회. 실제 파일 중복은 어댑터가 file_id/sha 로 거른다.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from ves.scheduler.planner import _load_channels

_FOLDER_RE = re.compile(r"drive\.google\.com/drive/folders/([A-Za-z0-9_-]{20,})")


def folder_url_of(download_link: str):
    """laeebly download_link(산문 HTML 섞임) → 정규 폴더 URL. 순수."""
    m = _FOLDER_RE.search(str(download_link or ""))
    return f"https://drive.google.com/drive/folders/{m.group(1)}" if m else None


def run(conn, cfg):
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date().isoformat()
    targets = []   # (label, url, work_title|None, mode)

    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key='drive_watch_folder'")
        row = c.fetchone()
    if row and row["value"]:
        targets.append(("외부폴더", row["value"], None, "external"))

    works = sorted({w for ch in _load_channels(cfg) for w in (ch.get("works") or [])})
    if works and cfg.laeebly_url:
        try:
            from ves.db import connect
            lae = connect(cfg.laeebly_url)
            try:
                with lae.cursor() as c:
                    c.execute("SELECT title, download_link FROM licensed_video "
                              "WHERE title = ANY(%s)", (works,))
                    for r in c.fetchall():
                        url = folder_url_of(r["download_link"])
                        if url:
                            targets.append((r["title"], url, r["title"], "single"))
            finally:
                lae.close()
        except Exception as e:  # noqa: BLE001 — laeebly 장애가 외부폴더 감시를 막지 않는다
            print(f"[drive_watch] laeebly 조회 실패(건너뜀): {e}")

    # rclone.conf 가 있는 노드로 고정(권리사 폴더 인증 접근 — 실측 2026-08-10)
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key='drive_sync_node'")
        row = c.fetchone()
    caps = ["network"] + ([f"node:{row['value']}"] if row and row.get("value") else [])

    made = 0
    for label, url, work, mode in targets:
        params = {"folder_url": url, "mode": mode, "use_limit": 3}
        if work:
            params["work_title"] = work
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.job_queue
                       (kind, params, idempotency_key, required_caps, lease_ttl_sec)
                   VALUES ('sync_drive_folder', %s::jsonb,
                           encode(extensions.digest(%s,'sha256'),'hex'),
                           %s, 600)
                   ON CONFLICT (idempotency_key) DO NOTHING""",
                (json.dumps(params, ensure_ascii=False), f"drive-sync|{url}|{today}", caps))
            made += c.rowcount
    print(f"[drive_watch] 대상 {len(targets)}곳 · 신규 잡 {made}건 · caps={caps} ({today})")
