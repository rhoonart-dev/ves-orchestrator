#!/usr/bin/env python3
"""loopy_drive — 드라이브 쇼츠 목록 잡을 매일 만든다 (L-P5, 2026-08-25).

사용자 지시: "쇼츠 소스는 [드라이브 폴더]에서도 받을 수 있어. 이번년도 것만 사용해서
일본어 입히고 올리게 해주면 되겠다."

무거운 일(rclone 목록)은 워커가 한다 — 스케줄러는 잡만 만든다(drive_watch 와 같은 규약).
⚠ 잡은 **rclone.conf 가 있는 노드**로 고정한다(`ops_config.drive_sync_node`). 없으면
어느 노드가 집어도 인증이 없어 실패한다.

목록만 만든다. 파일(3~6 GB)은 **고른 편만** acquire 가 받는다.
"""
from __future__ import annotations

import datetime as dt
import json

CONFIG_KEY = "loopy_drive_scout"
KIND = "scan_drive_shorts"

DEFAULTS = {"enabled": False, "channel_slug": "LOOPY", "folder_id": "", "year": None}


def merge_config(raw) -> dict:
    """ops_config 값 → 설정. 깨졌으면 기본값(수집이 안 돌 뿐 관제를 막지 않는다). 순수."""
    cfg = dict(DEFAULTS)
    try:
        if raw:
            got = json.loads(raw)
            if isinstance(got, dict):
                cfg.update(got)
    except ValueError:
        pass
    return cfg


def target_year(conf: dict, today: dt.date) -> int:
    """설정에 연도가 박혀 있으면 그것, 아니면 **오늘 연도**. 순수 — 테스트 대상.

    해가 바뀌면 저절로 새 폴더를 본다 — 사람이 매년 고쳐야 하면 언젠가 잊는다."""
    y = conf.get("year")
    try:
        return int(y) if y else today.year
    except (TypeError, ValueError):
        return today.year


def run(conn, cfg):
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key = %s", (CONFIG_KEY,))
        got = c.fetchone()
        conf = merge_config(got.get("value") if got else None)
        if not conf.get("enabled"):
            return          # 스위치 off — 사람이 켠다
        if not conf.get("folder_id"):
            print(f"[loopy_drive] folder_id 없음 — ops_config.{CONFIG_KEY} 확인")
            return
        c.execute("SELECT value FROM public.ops_config WHERE key='drive_sync_node'")
        node = ((c.fetchone() or {}).get("value") or "").strip()

    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    year = target_year(conf, today)
    caps = ["network"] + ([f"node:{node}"] if node else [])
    params = {"folder_id": conf["folder_id"], "channel_slug": conf["channel_slug"],
              "year": year}
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.job_queue
                   (kind, params, idempotency_key, required_caps, lease_ttl_sec)
               VALUES (%s, %s::jsonb,
                       encode(extensions.digest(%s,'sha256'),'hex'), %s, 900)
               ON CONFLICT (idempotency_key) DO NOTHING""",
            (KIND, json.dumps(params, ensure_ascii=False),
             f"loopy-drive|{conf['folder_id']}|{year}|{today}", caps))
        made = c.rowcount
    print(f"[loopy_drive] {conf['channel_slug']} {year}년 목록 잡 {made}건 "
          f"(노드 {node or '지정 없음'})")
