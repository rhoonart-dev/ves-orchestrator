#!/usr/bin/env python3
"""register_playlist 어댑터(네이티브) — 구 관제 소스 이관 (laeebly 유튜브형 작품).

laeebly guide 가 지정한 플레이리스트/공식채널을 yt-dlp --flat-playlist 로 전개해
sources 에 회차 순번대로 URL 등록한다. 파일 다운로드 없음 — 목록만.
  · 멱등: (work_title, 회차) 부분 유니크(0012) — 재실행해도 중복 없음
  · 비공개/삭제 항목은 건너뜀(소스 사멸 대응 — 도깨비 1번 영상 실측)
  · title_filter: 공식채널(tvN Joy 등)처럼 여러 프로그램이 섞인 원천에서 제목 필터
yt-dlp 는 ai-video venv 모듈로 실행(런치디 PATH 에 brew 가 없어도 확정 동작).

재실행은 **정정(訂正)이기도 하다**(2026-08-13). 0027 이전 등록분은 길이·업로드시각이
비어 있어 ① use_limit 이 전량 기본값 3 이고 ② planner 의 길이 하한 방어가 길이 미상을
통과시킨다 — 도깨비 10주년 여행에서 1분 8초짜리 예고편이 소스로 뽑혔다.
그래서 충돌 시 DO NOTHING 이 아니라 **비어 있는 칸만 채우고**(사람이 정한 값은 보존),
목록에서 사멸·쇼츠성으로 확인된 기등록 행은 비활성으로 내린다.
회차(episode)만은 손대지 않는다 — 바꾸면 source_usage_legacy 의 (작품·채널·회차)
매칭이 끊겨 레거시 사용분이 사라진다. 그 이행은 deploy/reparse_youtube_episodes.py 가
장부를 확인하며 따로 한다.
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


def episode_trend(entries, episode_regex=None) -> int:
    """목록의 회차 번호가 뒤로 갈수록 커지는가. 순수 — 테스트 대상.
    +1 = 오래된 것부터(그대로) · -1 = 최신부터(뒤집어야 함) · 0 = 판단 불가.

    URL 모양(is_newest_first)은 추측이다 — "사람이 만든 재생목록은 대개 오래된 것이 앞"
    이라는 가정이 tvN Joy 작품 재생목록에서 통째로 어긋났다(8/14 실측: 도깨비·언더커버셰프·
    칼라페 모두 최신순인데 뒤집지 않아 최신 영상이 1번이 됐다). 제목에서 회차를 읽을 수
    있으면 그게 목록의 실제 방향을 말해준다 — 추측 대신 데이터를 본다.

    같은 회차 영상이 여럿이라 같은 번호가 이어지는 것은 방향 판단에서 무시한다(비긴다).
    표본이 적거나(4개 미만) 증감이 팽팽하면 0 — 부르는 쪽이 종전 규칙으로 폴백한다."""
    eps = []
    for e in entries or []:
        n = base.guess_episode_title((e or {}).get("title") or "", episode_regex or "")
        if n is not None:
            eps.append(n)
    if len(eps) < 4:
        return 0
    up = sum(1 for a, b in zip(eps, eps[1:]) if b > a)
    down = sum(1 for a, b in zip(eps, eps[1:]) if b < a)
    if abs(up - down) < 2:            # 팽팽하면 판단하지 않는다(뒤죽박죽인 목록)
        return 0
    return 1 if up > down else -1


def chronological(entries, source_url: str = "", episode_regex=None) -> list:
    """항목을 '오래된 것 → 최신' 순으로 세운다. 순수 — 테스트 대상.

    ★사용자 결정(2026-08-12): 소스는 오래된 것부터 쓴다. 회차 번호를 그 순서로 매겨야
      planner 의 '최저 회차부터'가 곧 '오래된 것부터'가 된다.
      종전엔 채널 업로드 피드(최신순)를 그대로 1번부터 매겨 **최신 영상이 1화**였다.
    판단 근거 우선순위: ① 항목의 업로드 시각(timestamp/release_timestamp)
                      ② 제목에서 읽은 회차의 증감(episode_trend) — 8/14 추가
                      ③ 없으면 원천 URL 모양(채널 피드면 뒤집는다)
    ②가 필요한 이유: --flat-playlist 는 업로드 시각을 주지 않는다(실측 전 작품 0건).
    그래서 ①은 사실상 안 타고 ③의 추측만 남아 있었다."""
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
    trend = episode_trend(items, episode_regex)
    if trend:
        return list(reversed(items)) if trend < 0 else items
    return list(reversed(items)) if is_newest_first(source_url) else items


def is_dead_entry(e) -> bool:
    """비공개·삭제된 항목인가. 순수 — 테스트 대상.

    yt-dlp 는 비공개 항목의 title 을 **None** 으로 돌려준다(8/13 실측: 도깨비 10주년 여행
    SGeB_VFBIy0). 종전의 '[Private video]' 문자열 대조는 title 을 빈 문자열로 바꿔 받고
    있어 이걸 못 걸렀다 — 사멸 영상이 그대로 등록되고 generate 가 Private video 로 죽는다."""
    if not e:
        return True
    title = e.get("title")
    if title is None:
        return True
    return str(title) in ("[Private video]", "[Deleted video]")


def entry_duration(e):
    """flat-playlist 항목 → 길이(초) | None(미상). 순수 — 길이 판단은 한 곳에서만 한다."""
    try:
        v = (e or {}).get("duration")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def out_of_range(title, episode_rx=None, start_episode=None) -> bool:
    """시작 회차(0041) 밖인가. 순수 — 테스트 대상.

    · 제목에서 읽은 회차 < start_episode → True(범위 밖)
    · **회차를 못 읽어도 True** — 서수 폴백은 1부터라 start_episode 보다 늘 작고,
      planner 는 최저 회차부터 고른다. 남겨두면 시작 회차 설정이 통째로 무력해진다.
    · start_episode 가 없으면 언제나 False — 기존 작품 동작 그대로."""
    if not start_episode:
        return False
    ep = base.guess_episode_title(title or "", episode_rx or "")
    return ep is None or ep < int(start_episode)


def unusable_urls(entries, min_duration=None, exclude_rx=None,
                  episode_rx=None, start_episode=None) -> list:
    """목록상 **이미 등록돼 있다면 내려야 할** 영상 URL. 순수 — 테스트 대상.

    plan_rows 가 거르는 항목(사멸·길이 하한 이하·제외 패턴)은 '등록만 안 될' 뿐이라,
    0027 이전에 등록된 같은 영상은 활성으로 남는다. 그 행들은 duration_sec 이 비어 있어
    planner 의 하한 방어도 통과한다 — 등록 잡이 목록을 다시 볼 때 함께 내려야 사람 손이
    안 든다(도깨비 10주년 여행 8/14: 예고·티저 18건을 손으로 내렸다).
    ★거르는 규칙은 plan_rows 와 같은 함수(base.is_usable · base.title_excluded)를 쓴다 —
      등록에서 뺀 것과 비활성으로 내리는 것이 어긋나면 매 실행마다 등록·해제가 오간다.
    ★title_filter 로 걸러진 항목은 넣지 않는다. '이 작품이 아니다'는 판단이라, 같은 원천을
      공유하는 다른 작품의 행을 내릴 수 있다(공식채널 원천)."""
    out = []
    for e in entries or []:
        vid = (e or {}).get("id")
        if not vid:
            continue
        if (is_dead_entry(e)
                or not base.is_usable(entry_duration(e), min_duration)
                or base.title_excluded((e or {}).get("title"), exclude_rx)
                or out_of_range((e or {}).get("title"), episode_rx, start_episode)):
            out.append(f"https://www.youtube.com/watch?v={vid}")
    return out


def _upload_ts(e):
    """flat-playlist 항목 → 업로드 시각(epoch) | None. 순수."""
    for k in ("timestamp", "release_timestamp", "epoch"):
        v = (e or {}).get(k)
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
    return None


def plan_rows(work_title: str, entries, title_filter: str = "", use_limit=None,
              source_url: str = "", title_episode_regex: str = "", min_duration=None,
              title_exclude_regex=None, start_episode=None):
    """flat-playlist entries → 등록 행(dict) 목록. 순수 — 테스트 대상.

    영상 단위 회차 체계(운영 합의 2026-08-13, 0027):
      · episode = 제목에서 뽑은 **원본 방송 회차**(episode_source='parsed') — 설명란
        'N화' 표기의 근거. 같은 회차에 영상 여러 개가 나올 수 있다(멱등키는 URL).
      · 못 뽑으면 '오래된 것 = 1번' 위치 서수(episode_source='ordinal') — 항목이
        빠져도 남은 번호가 안 흔들리게 위치 기준을 유지한다. 서수는 설명란에 안 쓴다.
      · use_limit = 길이 비례(base.use_limit_for) — 인자로 주면 그 값으로 고정.
      · 길이 하한 이하는 등록 자체를 건너뛴다(종전엔 planner 가 거르되 번호만 소비했다).
        하한은 작품 카드의 min_source_duration_sec, 없으면 기본 180(0031).
      · title_exclude_regex 에 걸리는 제목은 등록하지 않는다(0037) — 예고·선공개·티저는
        길이 하한만으로 못 거른다(언더커버셰프 [9화 선공개] 10분 24초 실측).
      · start_episode 미만은 등록하지 않는다(0041) — 장수 방영작의 운영 시작점.
        회차를 못 읽은 항목(서수)도 함께 제외한다: 서수는 1부터라 시작 회차보다 늘 작아
        planner 가 그것부터 집는다(놀라운 토요일 410화 — 재생목록엔 344화부터 있다).
      · published_ts(업로드 시각 epoch) — 같은 회차 안에서의 소비 순서 근거.

    작품 카드 정규식은 **여기서 한 번만** 컴파일한다 — 문법이 깨졌으면 항목을 돌기 전에
    PermanentError 로 끊어야 무한 재시도가 안 생긴다(base.compile_episode_regex)."""
    rx = base.compile_episode_regex(title_episode_regex)
    ex = base.compile_exclude_regex(title_exclude_regex)   # 여기서 한 번만 컴파일
    out = []
    norm = lambda s: "".join(str(s or "").split())   # noqa: E731 — 띄어쓰기 무시 대조
    filt = norm(title_filter)
    # 정렬에도 회차 정규식을 넘긴다 — 목록 방향을 제목의 회차 증감으로 판단한다
    for idx, e in enumerate(chronological(entries, source_url, rx), start=1):
        vid = (e or {}).get("id")
        title = str((e or {}).get("title") or "")
        if not vid:
            continue
        if is_dead_entry(e):
            continue                      # 사멸 항목 — 등록해봤자 acquire 에서 죽는다
        if filt and filt not in norm(title):
            continue                      # '놀라운토요일'≈'놀라운 토요일' (플릿 실측)
        if base.title_excluded(title, ex):
            continue                      # 예고·선공개·티저 — 본편이 아니다(0037)
        if out_of_range(title, rx, start_episode):
            continue                      # 시작 회차 밖 — 쓰지 않기로 한 회차(0041)
        dur = entry_duration(e)
        if not base.is_usable(dur, min_duration):
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
    """작품 카드(0028) — 회차 정규식·제목 필터의 정본. 잡 파라미터는 일회성 오버라이드.

    0037 컬럼이 아직 없는 DB 에서도 돈다 — 코드가 마이그레이션보다 먼저 배포되는 순간이
    반드시 생긴다(노드는 claim 경계마다 갱신하고, SQL 적용은 사람이 한다). 그 창에서
    등록 잡이 통째로 깨지지 않게 종전 컬럼만으로 한 번 더 시도한다(planner 의 0016
    이전 DB 호환과 같은 방식)."""
    with conn.cursor() as c:
        try:
            c.execute("""SELECT title_episode_regex, title_filter,
                                min_source_duration_sec, title_exclude_regex,
                                start_episode
                           FROM public.work_cards WHERE work_title = %s""", (work,))
            return c.fetchone() or {}
        except Exception as e:  # noqa: BLE001 — 0037 이전 DB(컬럼 없음)
            print(f"[register_playlist] 제외 패턴 컬럼 없음 — 0037 미적용 DB 로 진행: {e}")
            conn.rollback()                # 실패한 트랜잭션을 열어둔 채 다음 질의를 못 한다
    with conn.cursor() as c:
        c.execute("""SELECT title_episode_regex, title_filter, min_source_duration_sec
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

    # 유튜브는 요청 로케일에 맞춰 제목을 **자동 번역**해 돌려준다. 기본값이면 영어 제목이 와
    # 'EP.4' 같은 표기가 사라지고 회차 파싱이 서수 폴백으로 떨어진다 — 도깨비 10주년 여행
    # 실측(8/13): 제목에서 회차 읽음 14/30 → lang=ko 로 28/30. 소스는 전부 국내 방송이다.
    argv = [cfgmod.engine_py(cfg, "ai_video"), "-m", "yt_dlp", "--flat-playlist", "-J",
            "--extractor-args", f"youtube:lang={p.get('metadata_lang') or 'ko'}"]
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
    # 길이 하한(0031) — 잡 파라미터가 일회성 오버라이드, 없으면 작품 카드.
    # 등록에서 빼는 기준과 기등록 행을 내리는 기준이 같아야 한다(unusable_urls).
    min_duration = p.get("min_duration") or card.get("min_source_duration_sec")
    # 제외 패턴(0037)도 한 번만 컴파일해 등록·비활성 두 경로에 같은 것을 넘긴다 —
    # 문법이 깨졌으면 항목을 돌기 전에 PermanentError 로 끊는다.
    # 시작 회차(0041) — 장수 방영작의 운영 시작점. 잡 파라미터가 일회성 오버라이드.
    start_ep = p.get("start_episode") or card.get("start_episode")
    exclude = base.compile_exclude_regex(
        p.get("title_exclude_regex") or card.get("title_exclude_regex") or "")
    rows = plan_rows(work, entries,
                     p.get("title_filter") or card.get("title_filter") or "",
                     p.get("use_limit"), source_url=url, title_episode_regex=regex,
                     min_duration=min_duration, title_exclude_regex=exclude,
                     start_episode=start_ep)

    inserted = backfilled = deactivated = 0
    with conn.cursor() as c:
        # 0040 이전 DB(제목 컬럼 없음)에서도 돈다 — _work_card 와 같은 이유(배포 창).
        try:
            c.execute("SELECT title FROM public.sources LIMIT 0")
            has_title = True
        except Exception:  # noqa: BLE001
            conn.rollback()
            has_title = False
            print("[register_playlist] sources.title 컬럼 없음 — 0040 미적용 DB 로 진행")
        for r in rows:
            # 멱등키 = (작품, 영상 URL) — 0027. 같은 회차에 영상 여러 개 허용,
            # 재실행 시 같은 영상만 걸러진다(종전 회차 키는 다른 영상을 중복으로 오인).
            # ★충돌 시 빈 칸만 채운다: 길이를 몰라 기본값 3 으로 등록된 0027 이전 행을
            #   길이 비례 편수로 되돌린다. 길이를 이미 알던 행의 use_limit 은 사람이 정한
            #   값일 수 있어 건드리지 않는다(register_drive 와 같은 규칙).
            #   제목(0040)도 빈 칸만 — 등록 시점 박제라 갱신하지 않는다.
            # ★episode 는 갱신하지 않는다 — source_usage_legacy 매칭이 끊긴다(머리말).
            if has_title:
                sql = """INSERT INTO public.sources
                       (work_title, episode, episode_source, source_url, origin,
                        registered_by, use_limit, duration_sec, published_ts, title)
                   VALUES (%s,%s,%s,%s,'youtube',%s,%s,%s,to_timestamp(%s),%s)
                   ON CONFLICT (work_title, source_url)
                     WHERE source_url IS NOT NULL DO UPDATE SET
                       duration_sec = COALESCE(sources.duration_sec, EXCLUDED.duration_sec),
                       published_ts = COALESCE(sources.published_ts, EXCLUDED.published_ts),
                       title        = COALESCE(sources.title, EXCLUDED.title),
                       use_limit = CASE WHEN sources.duration_sec IS NULL
                                         AND EXCLUDED.duration_sec IS NOT NULL
                                        THEN EXCLUDED.use_limit ELSE sources.use_limit END
                     WHERE sources.duration_sec IS NULL OR sources.published_ts IS NULL
                        OR sources.title IS NULL
                   RETURNING (xmax = 0) AS inserted"""
                args = (work, r["episode"], r["episode_source"], r["url"],
                        f"register_playlist:{job['id']}", r["use_limit"],
                        r["duration"], r["published_ts"], (r.get("title") or None))
            else:
                sql = """INSERT INTO public.sources
                       (work_title, episode, episode_source, source_url, origin,
                        registered_by, use_limit, duration_sec, published_ts)
                   VALUES (%s,%s,%s,%s,'youtube',%s,%s,%s,to_timestamp(%s))
                   ON CONFLICT (work_title, source_url)
                     WHERE source_url IS NOT NULL DO UPDATE SET
                       duration_sec = COALESCE(sources.duration_sec, EXCLUDED.duration_sec),
                       published_ts = COALESCE(sources.published_ts, EXCLUDED.published_ts),
                       use_limit = CASE WHEN sources.duration_sec IS NULL
                                         AND EXCLUDED.duration_sec IS NOT NULL
                                        THEN EXCLUDED.use_limit ELSE sources.use_limit END
                     WHERE sources.duration_sec IS NULL OR sources.published_ts IS NULL
                   RETURNING (xmax = 0) AS inserted"""
                args = (work, r["episode"], r["episode_source"], r["url"],
                        f"register_playlist:{job['id']}", r["use_limit"],
                        r["duration"], r["published_ts"])
            c.execute(sql, args)
            # 채울 칸이 없으면 위 WHERE 가 갱신을 막아 돌아오는 행이 없다 — 이미 온전한 행을
            # 매 실행마다 다시 쓰지 않는다(정정 건수도 그만큼 정직해진다).
            res = c.fetchone()
            if res and res.get("inserted"):
                inserted += 1
            elif res:
                backfilled += 1

        # 사멸·쇼츠성으로 확인된 기등록 행 정리. rows 가 비면 목록을 제대로 못 읽었다는
        # 뜻이라 아무것도 내리지 않는다 — 한 번의 이상한 응답으로 소스를 쓸어내지 않게.
        dead = unusable_urls(entries, min_duration, exclude, regex, start_ep)
        if rows and dead:
            c.execute("""UPDATE public.sources SET is_active = false
                          WHERE work_title = %s AND origin = 'youtube' AND is_active
                            AND source_url = ANY(%s)""", (work, dead))
            deactivated = c.rowcount
    skipped = len(entries) - len(rows)
    parsed, ordinal, note = summarize_episodes(rows)
    if regex and ordinal:
        # 작품 카드에 정규식이 있는데도 못 읽은 영상 — 정규식이 낡았거나 표기가 바뀐 신호
        print(f"[ALERT] {work}: 지정 정규식으로 회차를 못 읽은 영상 {ordinal}개 — "
              f"작품 카드 title_episode_regex 확인 필요")
    return {"listed": len(entries), "registered_new": inserted,
            "backfilled": backfilled, "deactivated": deactivated,
            "matched": len(rows), "skipped_or_filtered": skipped,
            "episode_parsed": parsed, "episode_ordinal": ordinal, "note": note}
