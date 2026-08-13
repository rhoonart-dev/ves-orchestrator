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


def _upload_ts(e):
    """flat-playlist 항목 → 업로드 시각(epoch) | None. 순수."""
    for k in ("timestamp", "release_timestamp", "epoch"):
        v = (e or {}).get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def plan_rows(work_title: str, entries, title_filter: str = "", use_limit=None,
              source_url: str = "", title_episode_regex: str = ""):
    """flat-playlist entries → 등록 행(dict) 목록. 순수 — 테스트 대상.

    영상 단위 회차 체계(운영 합의 2026-08-13, 0027):
      · episode = 제목에서 뽑은 **원본 방송 회차**(episode_source='parsed') — 설명란
        'N화' 표기의 근거. 같은 회차에 영상 여러 개가 나올 수 있다(멱등키는 URL).
      · 못 뽑으면 '오래된 것 = 1번' 위치 서수(episode_source='ordinal') — 항목이
        빠져도 남은 번호가 안 흔들리게 위치 기준을 유지한다. 서수는 설명란에 안 쓴다.
      · use_limit = 길이 비례(base.use_limit_for) — 인자로 주면 그 값으로 고정.
      · 3분 이하는 등록 자체를 건너뛴다(종전엔 planner 가 거르되 번호만 소비했다).
      · published_ts(업로드 시각 epoch) — 같은 회차 안에서의 소비 순서 근거.

    작품 카드 정규식은 **여기서 한 번만** 컴파일한다 — 문법이 깨졌으면 항목을 돌기 전에
    PermanentError 로 끊어야 무한 재시도가 안 생긴다(base.compile_episode_regex)."""
    rx = base.compile_episode_regex(title_episode_regex)
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
        try:
            dur = float(e["duration"]) if (e or {}).get("duration") is not None else None
        except (TypeError, ValueError):
            dur = None
        if dur is not None and dur <= 180:
            continue                      # 예고·쇼츠성(8/12 결정) — 번호도 안 준다
        ep = base.guess_episode_title(title, rx)
        ep_src = "parsed" if ep is not None else "ordinal"
        out.append({"episode": idx if ep is None else ep, "episode_source": ep_src,
                    "url": f"https://www.youtube.com/watch?v={vid}", "title": title,
                    "duration": dur, "published_ts": _upload_ts(e),
                    "use_limit": int(use_limit) if use_limit else base.use_limit_for(dur)})
    return out


def summarize_episodes(rows):
    """등록 행들 → (parsed 수, ordinal 수, 사람용 요약문). 순수 — 테스트 대상.
    대시보드 작업내역에서 정규식 문제를 바로 알아채게 한국어로 말한다."""
    parsed = sum(1 for r in rows or [] if r.get("episode_source") == "parsed")
    ordinal = len(rows or []) - parsed
    note = f"회차 인식: 제목에서 읽음 {parsed}개 · 순번 폴백 {ordinal}개"
    if ordinal:
        note += " — 순번 폴백분은 방송 회차가 아니라서 설명란에 회차를 적지 않습니다"
    return parsed, ordinal, note


def _work_card(conn, work):
    """작품 카드(0028) — 회차 정규식·제목 필터의 정본. 잡 파라미터는 일회성 오버라이드."""
    with conn.cursor() as c:
        c.execute("""SELECT title_episode_regex, title_filter
                       FROM public.work_cards WHERE work_title = %s""", (work,))
        return c.fetchone() or {}


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
    card = _work_card(conn, work)
    regex = p.get("title_episode_regex") or card.get("title_episode_regex") or ""
    rows = plan_rows(work, entries,
                     p.get("title_filter") or card.get("title_filter") or "",
                     p.get("use_limit"), source_url=url, title_episode_regex=regex)

    inserted = 0
    with conn.cursor() as c:
        for r in rows:
            # 멱등키 = (작품, 영상 URL) — 0027. 같은 회차에 영상 여러 개 허용,
            # 재실행 시 같은 영상만 걸러진다(종전 회차 키는 다른 영상을 중복으로 오인).
            c.execute(
                """INSERT INTO public.sources
                       (work_title, episode, episode_source, source_url, origin,
                        registered_by, use_limit, duration_sec, published_ts)
                   VALUES (%s,%s,%s,%s,'youtube',%s,%s,%s,to_timestamp(%s))
                   ON CONFLICT (work_title, source_url)
                     WHERE source_url IS NOT NULL DO NOTHING""",
                (work, r["episode"], r["episode_source"], r["url"],
                 f"register_playlist:{job['id']}", r["use_limit"],
                 r["duration"], r["published_ts"]))
            inserted += c.rowcount
    skipped = len(entries) - len(rows)
    parsed, ordinal, note = summarize_episodes(rows)
    if regex and ordinal:
        # 작품 카드에 정규식이 있는데도 못 읽은 영상 — 정규식이 낡았거나 표기가 바뀐 신호
        print(f"[ALERT] {work}: 지정 정규식으로 회차를 못 읽은 영상 {ordinal}개 — "
              f"작품 카드 title_episode_regex 확인 필요")
    return {"listed": len(entries), "registered_new": inserted,
            "matched": len(rows), "skipped_or_filtered": skipped,
            "episode_parsed": parsed, "episode_ordinal": ordinal, "note": note}
