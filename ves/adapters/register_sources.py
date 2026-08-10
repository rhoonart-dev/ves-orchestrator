#!/usr/bin/env python3
"""register_playlist 어댑터(네이티브) — 구 관제 소스 이관 (laeebly 유튜브형 작품).

laeebly guide 가 지정한 플레이리스트/공식채널을 yt-dlp --flat-playlist 로 전개해
sources 에 회차 순번대로 URL 등록한다. 파일 다운로드 없음 — 목록만.
  · 멱등: (work_title, 회차) 부분 유니크(0012) — 재실행해도 중복 없음
  · 비공개/삭제 항목은 건너뜀(소스 사멸 대응 — 도깨비 1번 영상 실측)
  · title_filter: 공식채널(tvN Joy 등)처럼 여러 프로그램이 섞인 원천에서 제목 필터
yt-dlp 는 ai-video venv 모듈로 실행(런치디 PATH 에 brew 가 없어도 확정 동작).
"""
from __future__ import annotations

from ves import config as cfgmod
from ves.adapters import base


def plan_rows(work_title: str, entries, title_filter: str = "", use_limit: int = 3):
    """flat-playlist entries → [(episode, url, title)]. 순수 — 테스트 대상.
    회차 번호는 원천 목록의 순번(1-base) — 항목이 빠져도 남은 회차 번호가 안 흔들린다."""
    out = []
    norm = lambda s: "".join(str(s or "").split())   # noqa: E731 — 띄어쓰기 무시 대조
    filt = norm(title_filter)
    for idx, e in enumerate(entries or [], start=1):
        vid = (e or {}).get("id")
        title = str((e or {}).get("title") or "")
        if not vid:
            continue
        if title in ("[Private video]", "[Deleted video]"):
            continue                      # 사멸 항목 — 등록해봤자 acquire 에서 죽는다
        if filt and filt not in norm(title):
            continue                      # '놀라운토요일'≈'놀라운 토요일' (플릿 실측)
        out.append((idx, f"https://www.youtube.com/watch?v={vid}", title))
    return out


def run(cfg, conn, job, deps):
    import json
    import subprocess
    p = job["params"]
    work, url = p.get("work_title"), p.get("playlist_url")
    if not (work and url):
        raise base.PermanentError("params.work_title/playlist_url 필요")
    limit = int(p.get("max_items") or 60)

    argv = [cfgmod.engine_py(cfg, "ai_video"), "-m", "yt_dlp",
            "--flat-playlist", "-J", "--playlist-end", str(limit), url]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        cls = base.classify_by_patterns(r.stderr or "", r.stdout or "")
        msg = (r.stderr or r.stdout or "")[-500:]
        if cls == "permanent":
            raise base.PermanentError(msg)
        raise RuntimeError(msg)           # transient — 네트워크 등은 백오프 재시도

    try:
        data = json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        raise base.PermanentError("yt-dlp 출력 파싱 실패 — --flat-playlist -J 계약 확인")
    entries = data.get("entries") or ([data] if data.get("id") else [])
    rows = plan_rows(work, entries, p.get("title_filter") or "", int(p.get("use_limit") or 3))

    inserted = 0
    with conn.cursor() as c:
        for ep, vurl, title in rows:
            c.execute(
                """INSERT INTO public.sources
                       (work_title, episode, source_url, origin, registered_by, use_limit)
                   VALUES (%s,%s,%s,'youtube',%s,%s)
                   ON CONFLICT (work_title, (COALESCE(episode,-1)))
                     WHERE source_url IS NOT NULL DO NOTHING""",
                (work, ep, vurl, f"register_playlist:{job['id']}",
                 int(p.get("use_limit") or 3)))
            inserted += c.rowcount
    skipped = len(entries) - len(rows)
    return {"listed": len(entries), "registered_new": inserted,
            "matched": len(rows), "skipped_or_filtered": skipped}
