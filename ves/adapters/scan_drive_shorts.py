#!/usr/bin/env python3
"""scan_drive_shorts — 드라이브 폴더의 **올해** 쇼츠를 아카이브에 등록 (L-P5-3a).

사용자 지시(2026-08-25): "쇼츠 소스는 [드라이브 폴더]에서도 받을 수 있어. 이번년도
것만 사용해서 일본어 입히고 올리게 해주면 되겠다."

## 왜 별도 어댑터인가

`register_drive`(sync_drive_folder)는 **소스 등록**이다 — 파일을 통째로 내려받아
sha256 을 내고 `sources` 에 넣는다(generate 가 쓸 원본). 여기서 필요한 것은 그게
아니라 **목록**이다: 무엇이 있는지 알아야 선별기가 고른다. 파일은 고른 편만
받는다(acquire). 3~6 GB 짜리를 목록 만들자고 전부 받을 수는 없다.

## 연도는 **폴더 이름**으로 읽는다

⚠ 파일·폴더의 ModTime 은 드라이브에 올린 날짜다 — 실측(2026-08-25)에서 2022년 폴더가
전부 `2026-08-03` 이었다. 날짜로 "올해"를 판정하면 4년치가 전부 올해가 된다.
폴더 이름이 `2026_yt_잔망루피_…` 규약이므로 그 앞자리를 쓴다.

## 「클린」

파일 이름에 `클린`/`clean` 이 붙은 것은 **화면에 한글 글자가 없는 마스터**다(사용자
확인). 그런 편은 인페인팅이 필요 없어 route A(자막 트랙만)로 간다 — 가장 비싸고
위험한 단계를 통째로 건너뛴다. 표시가 없는 파일은 **그대로 B** 로 둔다(같은 폴더에
섞여 있다 — 트렌드쇼츠 실측: 클린 표시가 있는 것과 없는 것이 함께 있었다).
"""
from __future__ import annotations

import datetime as dt
import json
import re

from ves.adapters import base
from ves.adapters.register_drive import _rc, _rclone_bin, _rclone_conf, first_remote

VIDEO_EXT = (".mov", ".mp4", ".m4v", ".mkv")
CLEAN_RE = re.compile(r"클린|clean", re.I)
YEAR_RE = re.compile(r"^(\d{4})[_\-]")


# ───────── 순수 (테스트 대상) ─────────

def folder_year(top: str):
    """최상위 폴더명 → 연도. 규약 밖이면 None. 순수.

    ⚠ ModTime 을 쓰지 않는 이유는 모듈 독스트링 참고 — 올린 날짜라 전부 같다."""
    m = YEAR_RE.match(str(top or "").strip())
    return int(m.group(1)) if m else None


def is_video(name: str) -> bool:
    return str(name or "").lower().endswith(VIDEO_EXT)


def route_for(name: str) -> str:
    """파일명 → 권장 route. 순수.

    '클린' = 화면 글자 없음 → A(자막 트랙만). 표시가 없으면 유튜브발과 같이 B(지우고 입힘).
    ⚠ 넘겨짚지 않는다 — 같은 폴더에 표시 있는 것과 없는 것이 섞여 있다(실측)."""
    return "A" if CLEAN_RE.search(str(name or "")) else "B"


def plan_rows(entries: list, year: int) -> list:
    """rclone lsjson(-R) 항목 → 아카이브에 넣을 행. 순수 — 테스트 대상.

    거르는 것: 폴더 · 영상 아닌 파일 · 올해가 아닌 폴더 · 연도 규약 밖 폴더(예: '일어 더빙').
    마지막 것이 중요하다 — 그 폴더는 **우리 산출물**이라 소재로 다시 집으면 순환한다."""
    out = []
    for e in entries or []:
        if e.get("IsDir"):
            continue
        rel = str(e.get("Path") or e.get("Name") or "")
        parts = [s for s in rel.replace("\\", "/").split("/") if s.strip()]
        if len(parts) < 2:
            continue                     # 루트 바로 아래 파일 — 연도를 모른다
        top, name = parts[0], parts[-1]
        if folder_year(top) != year or not is_video(name):
            continue
        fid = e.get("ID")
        if not fid:
            continue                     # id 가 없으면 다시 못 찾는다
        out.append({
            "video_id": f"drive:{fid}",
            "title": name.rsplit(".", 1)[0],
            "url": f"https://drive.google.com/file/d/{fid}/view",
            "published_at": e.get("ModTime"),
            "bytes": int(e.get("Size") or 0),
            "folder": top,
            "route": route_for(name),
            "drive_file_id": fid,
        })
    return out


# ───────── IO ─────────

def _lsjson(cfg, folder_id: str) -> list:
    """폴더 전체 목록(재귀). **받지 않는다.**

    ⚠ register_drive 는 lsjson 을 폐기하고 copy 를 쓴다("공유폴더에서 빈 목록을 주는
    케이스"). 이 폴더에서는 lsjson 이 동작하는 것을 실측했다(2026-08-25). 그래도 빈
    목록은 **성공으로 보지 않는다** — 아래 run() 이 크게 실패한다."""
    b, c = _rclone_bin(), _rclone_conf(cfg)
    remote = first_remote(_rc(b, c, "listremotes", "--long", timeout=30))
    if not remote:
        raise base.PermanentError("rclone.conf 에 원격이 없음")
    raw = _rc(b, c, "lsjson", "-R", remote, "--drive-root-folder-id", folder_id,
              timeout=600)
    try:
        return json.loads(raw or "[]")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"lsjson 파싱 실패: {e}")


def run(cfg, conn, job, deps):
    p = job["params"]
    folder_id = p.get("folder_id")
    if not folder_id:
        raise base.PermanentError("params.folder_id 없음")
    slug = p.get("channel_slug") or "LOOPY"
    year = int(p.get("year") or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).year)

    entries = _lsjson(cfg, folder_id)
    rows = plan_rows(entries, year)
    if not rows:
        # 빈 목록을 성공으로 넘기면 아카이브가 조용히 안 는다 — 폴더 권한·연도 규약이
        # 바뀐 것을 사람이 알아야 한다(loopy_scout 의 '비우지 않는다' 와 같은 규율).
        raise RuntimeError(
            f"{year}년 영상이 하나도 없다 (항목 {len(entries)}개) — 폴더 권한이나 "
            f"'<연도>_' 폴더 규약을 확인하세요")

    new = upd = 0
    for r in rows:
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.external_shorts
                       (video_id, channel_slug, source_handle, title, url,
                        kind, published_at, flags)
                   VALUES (%s,%s,'drive',%s,%s,'short',%s,%s::jsonb)
                   ON CONFLICT (video_id) DO UPDATE
                      SET title = EXCLUDED.title, url = EXCLUDED.url,
                          flags = public.external_shorts.flags || EXCLUDED.flags,
                          updated_at = now()
                   RETURNING (xmax = 0) AS inserted""",
                (r["video_id"], slug, r["title"], r["url"], r["published_at"],
                 json.dumps({"drive": True, "route": r["route"], "folder": r["folder"],
                             "bytes": r["bytes"], "drive_file_id": r["drive_file_id"]},
                            ensure_ascii=False)))
            got = c.fetchone() or {}
        if got.get("inserted"):
            new += 1
        else:
            upd += 1
    clean = sum(1 for r in rows if r["route"] == "A")
    print(f"[scan_drive_shorts] {slug} {year}년 {len(rows)}편 (신규 {new} · 갱신 {upd}) · "
          f"클린 {clean}편(route A)")
    return {"year": year, "rows": len(rows), "new": new, "updated": upd, "clean": clean}
