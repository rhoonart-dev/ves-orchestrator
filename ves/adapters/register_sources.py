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


_UPLOADS_HINTS = ("/videos", "/@", "/channel/", "/user/", "/c/", "uploads")


def is_newest_first(url: str) -> bool:
    """이 원천이 '최신순'으로 오는가. 순수 — 테스트 대상.

    유튜브 채널 업로드 피드(/@handle, /channel/…, /videos)는 최신이 맨 앞이다.
    사람이 만든 재생목록(/playlist?list=…)은 대개 오래된 것이 앞이라 뒤집지 않는다."""
    u = str(url or "").lower()
    if "list=" in u or "/playlist" in u:
        return False
    return any(h in u for h in _UPLOADS_HINTS)


def chronological(entries, source_url: str = "") -> list:
    """항목을 '오래된 것 → 최신' 순으로 세운다. 순수 — 테스트 대상.

    ★사용자 결정(2026-08-12): 소스는 오래된 것부터 쓴다. 회차 번호를 그 순서로 매겨야
      planner 의 '최저 회차부터'가 곧 '오래된 것부터'가 된다.
      종전엔 채널 업로드 피드(최신순)를 그대로 1번부터 매겨 **최신 영상이 1화**였다.
    판단 근거 우선순위: ① 항목의 업로드 시각(timestamp/release_timestamp)
                      ② 없으면 원천 URL 모양(채널 피드면 뒤집는다)"""
    items = list(entries or [])
    def ts(e):
        for k in ("timestamp", "release_timestamp", "epoch"):
            v = (e or {}).get(k)
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        return None
    stamps = [ts(e) for e in items]
    if items and all(s is not None for s in stamps):
        return [e for _s, e in sorted(zip(stamps, items), key=lambda t: t[0])]
    return list(reversed(items)) if is_newest_first(source_url) else items


def plan_rows(work_title: str, entries, title_filter: str = "", use_limit: int = 3,
              source_url: str = ""):
    """flat-playlist entries → [(episode, url, title)]. 순수 — 테스트 대상.
    회차 번호는 '오래된 것 = 1번' 순번(1-base) — 항목이 빠져도 남은 번호가 안 흔들린다."""
    out = []
    norm = lambda s: "".join(str(s or "").split())   # noqa: E731 — 띄어쓰기 무시 대조
    filt = norm(title_filter)
    for idx, e in enumerate(chronological(entries, source_url), start=1):
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
    # 0 = 전량(사용자 결정 2026-08-12: 작품에 맞는 영상 소스를 '모두' 받아 등록한다).
    # 종전 기본 60은 채널 뒤쪽(=오래된) 영상을 통째로 잘라 먹었다.
    limit = int(p.get("max_items") or 0)

    argv = [cfgmod.engine_py(cfg, "ai_video"), "-m", "yt_dlp", "--flat-playlist", "-J"]
    if limit > 0:
        argv += ["--playlist-end", str(limit)]
    argv.append(url)
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
    rows = plan_rows(work, entries, p.get("title_filter") or "",
                     int(p.get("use_limit") or 3), source_url=url)

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
