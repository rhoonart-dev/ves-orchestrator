#!/usr/bin/env python3
"""loopy_picker — 소재 선별기 (L-P3b, 2026-08-23).

발주서: docs/LOCALIZE_UNIFY.md §5-6. 사용자 지시(8/23): "전량 아카이브에서 문제 소지가
없는 영상들 중 지금 올리기에 적당한 영상을 선택해서 올리게. 이전에 올렸던 것은 제외."

아카이브가 1,100편이면 목록만으로는 못 고른다. **거르고 → 순위를 매기고 → 사람이
승인**하는 세 층이다. 새로 만드는 것은 게이트 1 뿐이고, 나머지는 옮겨 온 것이다
(vlp `src/jp_score.py` 의 신호 결합·정규화를 그대로 쓴다).

    게이트 0  제외(자동·되돌릴 수 없음)  이미 발행 · 내용 중복 · 진행 중 · 규격 밖
    게이트 1  문제 소지(사람이 뒤집을 수 있음)  차단 목록 > LLM 플래그 > 실측
    게이트 2  순위(지금 올리기 적당한)  성과 4신호 + 시의성 · 다양성 · 피드백

🛑 **발행은 어느 수준에서도 사람이다.** 폐기한 auto_approve 는 발행 승인 자동화였고,
여기서 되살아나는 것은 선별뿐이다(§5-6 자동화 수준 표).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re

CONFIG_KEY = "loopy_picker"
DENYLIST_KEY = "loopy_denylist"

# 게이트 0 — 이 상태면 후보가 아니다. uploaded 는 종착(0078 트리거가 한 번 더 막는다).
BUSY_STATES = ("processing", "pending_approval", "approved", "selected")
TERMINAL_STATES = ("uploaded",)

# 게이트 1 — LLM 심사 플래그별 기본 처분(§5-6 표). True = 차단.
BLOCKING_FLAGS = {
    "collab": True,      # 타 브랜드·IP 콜라보 — 일본 재배포 권리가 원작 계약 밖일 수 있다
    "sponsored": True,   # 유료 광고·PPL — 광고주 권리는 한국 한정
    "music": True,       # 특정 음원 의존 — 음원 권리는 지역별로 따로다
    "event": True,       # 종료된 이벤트·굿즈 홍보 — 지금 올리면 거짓 정보가 된다
    "topical": False,    # 한국 시사·유행 밈 — 경고(감점)
    "wordplay": False,   # 한국어 말장난 — 경고(감점). 잔망루피는 `~뤂` 어미가 잦다
}
SEASON_WINDOW_DAYS = 21          # 계절 소재는 ±3주 창 안이면 가산, 밖이면 차단
WARN_PENALTY = 0.10              # topical·wordplay 한 건당 감점

DEFAULT_WEIGHTS = {"views": 0.25, "like_ratio": 0.15, "jp_comments": 0.15,
                   "llm_jp_fit": 0.20, "timing": 0.10, "diversity": 0.10,
                   "kpi_feedback": 0.05}
DEFAULTS = {"enabled": False, "channel_slug": "LOOPY", "per_day": 1, "top_n": 5,
            "automation": "auto",          # manual | assist | auto (§5-6)
            "route": "B"}                  # auto 로 걸 때의 쇼츠 route (롱폼은 안 쓴다)

_SEASONS = {
    "newyear": (1, 1), "valentine": (2, 14), "spring": (4, 5), "summer": (8, 1),
    "chuseok": (9, 17), "halloween": (10, 31), "christmas": (12, 25),
}


# ───────── 신호 정규화 (vlp jp_score 이식 — 값까지 그대로) ─────────

def log_norm(value, max_value) -> float:
    """조회수처럼 롱테일 분포 값의 log 정규화(0~1)."""
    if not max_value or max_value <= 0 or not value or value <= 0:
        return 0.0
    return min(1.0, math.log1p(value) / math.log1p(max_value))


def like_norm(likes, views, good_ratio: float = 0.05) -> float:
    """좋아요율 정규화 — 5%(쇼츠 기준 매우 좋음)를 1.0 상한으로."""
    if not views or views <= 0 or not likes or likes <= 0:
        return 0.0
    return min(1.0, (likes / views) / good_ratio)


def combine_scores(signals: dict, weights: dict) -> float:
    """신호 가중합. **None 신호는 제외하고 남은 가중치로 재정규화**한다(합=1 유지).

    없는 신호를 0 으로 치면 '신호가 없다'가 '나쁘다'가 된다 — 댓글이 꺼진 영상이
    조용히 밀린다."""
    avail = {k: v for k, v in signals.items() if v is not None}
    if not avail:
        return 0.0
    wsum = sum(weights.get(k, 0.0) for k in avail)
    if wsum <= 0:
        return 0.0
    return round(sum(weights.get(k, 0.0) * v for k, v in avail.items()) / wsum, 6)


# ───────── 게이트 0 · 1 (순수) ─────────

def normalize_rule(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).lower()


def denylist_hit(title: str, rules) -> str | None:
    """사람이 관리하는 차단 목록. 맞으면 그 규칙을 돌려준다. 순수 — 테스트 대상.

    가장 신뢰도가 높고 감사 가능하다 — **사람이 막은 것은 LLM 이 못 푼다.**"""
    hay = normalize_rule(title)
    for rule in rules or []:
        r = normalize_rule(str(rule))
        if r and r in hay:
            return str(rule)
    return None


def season_ok(season, today: dt.date, window_days: int = SEASON_WINDOW_DAYS) -> bool:
    """계절 소재가 지금 철인가. 순수 — 테스트 대상.

    연말·연시처럼 해를 넘는 창도 맞아야 하므로 전년·당해·익년 세 벌로 잰다."""
    if not season or season not in _SEASONS:
        return True                       # 계절 태그가 없으면 판정 대상이 아니다
    mo, day = _SEASONS[season]
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            target = dt.date(year, mo, day)
        except ValueError:                # 2/29 같은 값 방어
            continue
        if abs((today - target).days) <= window_days:
            return True
    return False


def gate_block(row: dict, *, denylist=None, today: dt.date | None = None,
               min_sec: float = 3.0, max_sec: float = 61.0) -> str | None:
    """게이트 0·1 — 막을 사유(없으면 None). 순수 — 테스트 대상.

    ⚠ 사람이 `allowed_by` 로 뒤집었으면 **게이트 1 은 건너뛴다**(게이트 0 은 못 뒤집는다 —
    이미 올린 것을 또 올릴 수는 없다)."""
    today = today or dt.date.today()

    # ── 게이트 0: 되돌릴 수 없는 제외 ─────────────────────────────────
    state = str(row.get("state") or "discovered")
    if state in TERMINAL_STATES:
        return "이미 발행됨"
    if row.get("youtube_id"):
        return "이미 발행됨(발행 이력 있음)"
    if row.get("dup_of"):
        return f"내용 중복 — {row['dup_of']} 와 같은 내용으로 보임"
    if state in BUSY_STATES:
        return f"진행 중({state})"
    if state in ("failed", "skipped"):
        return f"제외됨({state})"
    dur = row.get("duration_sec")
    if dur is None or not (min_sec <= float(dur) <= max_sec):
        return f"규격 밖(길이 {dur})"

    # ── 게이트 1: 문제 소지 (사람이 뒤집을 수 있다) ───────────────────
    if row.get("allowed_by"):
        return None
    hit = denylist_hit(row.get("title") or "", denylist)
    if hit:
        return f"차단 목록: {hit}"
    flags = row.get("flags") or {}
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except ValueError:
            flags = {}
    for name, blocking in BLOCKING_FLAGS.items():
        if blocking and flags.get(name):
            return f"권리·시의성 플래그: {name}"
    if flags.get("seasonal") and not season_ok(flags.get("season"), today):
        return f"철 지난 계절 소재({flags.get('season')})"
    return None


# ───────── 게이트 2 — 순위 (순수) ─────────

def timing_signal(flags, today: dt.date) -> float:
    """시의성 — 지금이 그 소재의 철인가. 계절 태그가 없으면 중립(0.5)."""
    flags = flags or {}
    if not flags.get("seasonal"):
        return 0.5
    return 1.0 if season_ok(flags.get("season"), today) else 0.0


def diversity_signal(published_at, recent_published, span_days: int = 180) -> float:
    """최근 발행분과 원본 시기가 겹치면 감점. 순수 — 테스트 대상.

    ⚠ **'옛날 것부터'를 지키는 장치다.** 성과 신호만으로 정렬하면 최신 100편만 돌다
    끝나고 1,000편이 영영 안 나온다(§5-6). 최근에 안 쓴 시기일수록 1.0 에 가깝다."""
    if not published_at:
        return 0.5
    if not recent_published:
        return 1.0
    gaps = [abs((published_at - r).days) for r in recent_published if r]
    if not gaps:
        return 1.0
    return round(min(1.0, min(gaps) / span_days), 6)


def warn_penalty(flags) -> float:
    """경고 플래그(topical·wordplay) 감점 — 차단은 아니지만 뒤로 민다."""
    flags = flags or {}
    n = sum(1 for name, blocking in BLOCKING_FLAGS.items()
            if not blocking and flags.get(name))
    return n * WARN_PENALTY


def score_row(row: dict, *, max_views: float, recent_published=None,
              today: dt.date | None = None, weights=None) -> tuple[float, dict]:
    """한 편의 점수와 신호 분해. 순수 — 테스트 대상.

    분해를 함께 돌려주는 이유: 점수만 보여 주면 사람이 승인할 근거가 없다(§5-6 추천 카드)."""
    today = today or dt.date.today()
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)
    flags = row.get("flags") or {}
    signals = {
        "views": log_norm(row.get("view_count") or 0, max_views),
        "like_ratio": like_norm(row.get("like_count") or 0, row.get("view_count") or 0),
        "jp_comments": row.get("jp_comment_ratio"),          # 없으면 None → 재정규화
        "llm_jp_fit": row.get("llm_fit"),
        "timing": timing_signal(flags, today),
        "diversity": diversity_signal(row.get("published_at"), recent_published),
        "kpi_feedback": row.get("kpi_similarity"),
    }
    base = combine_scores(signals, w)
    final = round(max(0.0, base - warn_penalty(flags)), 6)
    return final, {k: v for k, v in signals.items() if v is not None}


def rank(rows, *, denylist=None, today: dt.date | None = None,
         recent_published=None, weights=None, top_n: int = 5):
    """후보 전체 → (추천 목록, 제외 목록). 순수 — 테스트 대상.

    제외 목록도 돌려준다 — '왜 이 편은 안 뜨지'가 답변 가능해야 한다(§5-6)."""
    today = today or dt.date.today()
    picked, blocked = [], []
    max_views = max((r.get("view_count") or 0) for r in rows) if rows else 0
    for r in rows:
        reason = gate_block(r, denylist=denylist, today=today)
        if reason:
            blocked.append({**r, "block_reason": reason})
            continue
        score, parts = score_row(r, max_views=max_views, recent_published=recent_published,
                                 today=today, weights=weights)
        picked.append({**r, "score": score, "scores": parts})
    picked.sort(key=lambda x: (-x["score"], x.get("video_id") or ""))
    return picked[:top_n], blocked


# ───────── DB 연결 (여기부터는 순수하지 않다) ─────────

def _cfg(conn, key: str, default):
    """ops_config 한 줄. 잡마다 다시 읽는다 — 워커 재시작 없이 사람이 켜고 끈다."""
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key = %s", (key,))
        got = c.fetchone()
    raw = got.get("value") if got else None
    if key == CONFIG_KEY:
        return merge_config(raw)
    try:
        return json.loads(raw) if raw else default
    except ValueError:
        return default


def merge_config(raw) -> dict:
    """ops_config 값 → 설정. 깨졌으면 기본값(선별이 안 돌 뿐 관제를 막지 않는다). 순수."""
    cfg = dict(DEFAULTS)
    try:
        if raw:
            got = json.loads(raw)
            if isinstance(got, dict):
                cfg.update({k: v for k, v in got.items() if k in DEFAULTS})
    except ValueError:
        pass
    return cfg


def load_candidates(conn, slug: str) -> list:
    """게이트 0 을 SQL 로 한 번 거른 뒤의 후보. 진행 중·발행 완료는 아예 안 읽는다.

    ⚠ `dup_of` 는 여기서 안 거른다 — gate_block 이 사유 문자열까지 만들어야
    '왜 이 편은 안 뜨지'에 답할 수 있다(§5-6)."""
    with conn.cursor() as c:
        c.execute("""
            SELECT video_id, title, url, thumbnail_url, duration_sec,
                   view_count, like_count, comment_count, published_at,
                   state, flags, dup_of, youtube_id, allowed_by, kind
              FROM public.external_shorts
             WHERE channel_slug = %s AND kind = 'short'
               AND NOT (state = ANY(%s))
        """, (slug, list(TERMINAL_STATES + BUSY_STATES)))
        return [dict(r) for r in c.fetchall()]


def recent_published_dates(conn, slug: str, limit: int = 30) -> list:
    """최근 발행한 편들의 **원본 공개일** — 다양성 신호의 재료.

    사용자 지시의 '옛날 것부터'가 사는 자리다: 최근 올린 것과 원본 시기가 몰리면 감점."""
    with conn.cursor() as c:
        c.execute("""
            SELECT published_at FROM public.external_shorts
             WHERE channel_slug = %s AND (state = 'uploaded' OR youtube_id IS NOT NULL)
               AND published_at IS NOT NULL
             ORDER BY publish_at DESC NULLS LAST, updated_at DESC
             LIMIT %s
        """, (slug, limit))
        return [r["published_at"] for r in c.fetchall()]


def write_results(conn, scored: list, blocked: list, top_n: int = 5) -> None:
    """판정을 아카이브에 기록. **상태는 scored 까지만** 올린다.

    🛑 selected 이상으로 올리지 않는다 — 작업을 거는 것은 발행 경로(사람 승인)의
    몫이고, 선별기가 상태를 밀면 승인 전에 체인이 돈다(§5-6 자동화 수준 표).

    ⚠ 점수는 **막히지 않은 편 전부**에 쓰고, 상태를 scored 로 올리는 것은 상위
    top_n 뿐이다. 상위만 점수를 가지면 대시보드 '점수순'이 top_n 개짜리 목록이 되어
    아카이브를 훑는 쓸모가 없어진다(추천 = state, 점수 = 정렬 재료로 나눈다)."""
    with conn.cursor() as c:
        for i, r in enumerate(scored):
            promote = i < top_n
            c.execute("""
                UPDATE public.external_shorts
                   SET score = %s, scores = %s, block_reason = NULL,
                       state = CASE WHEN %s AND state = 'discovered' THEN 'scored'
                                    WHEN NOT %s AND state = 'scored' THEN 'discovered'
                                    ELSE state END
                 WHERE video_id = %s AND state IN ('discovered','scored')
            """, (r["score"], json.dumps(r["scores"], ensure_ascii=False),
                  promote, promote, r["video_id"]))
        for r in blocked:
            # 사람이 이미 뒤집은 편(allowed_by)은 사유만 남기고 상태를 안 건드린다.
            c.execute("""
                UPDATE public.external_shorts
                   SET block_reason = %s, score = NULL
                 WHERE video_id = %s AND state IN ('discovered','scored')
            """, (r["block_reason"], r["video_id"]))


def run(conn, cfg):
    conf = _cfg(conn, CONFIG_KEY, DEFAULTS)
    if not conf.get("enabled"):
        return          # 스위치 off — 사람이 켠다(ops_config.loopy_picker)
    slug = conf["channel_slug"]
    denylist = _cfg(conn, DENYLIST_KEY, [])
    rows = load_candidates(conn, slug)
    if not rows:
        print(f"[loopy_picker] {slug} 후보 없음 — 아카이브가 비었거나 전부 진행 중")
        return

    top_n = int(conf.get("top_n") or 5)
    # top_n=len(rows) 로 부른다 — 점수는 전부 받아 쓰고(정렬 재료), 추천 표시는 상위만.
    scored, blocked = rank(rows, denylist=denylist,
                           recent_published=recent_published_dates(conn, slug),
                           top_n=len(rows))
    write_results(conn, scored, blocked, top_n)

    top = ", ".join(f"{r.get('title') or r['video_id']}({r['score']:.3f})"
                    for r in scored[:3])
    print(f"[loopy_picker] {slug} 후보 {len(rows)}편 → 점수 {len(scored)}"
          f"(추천 {min(top_n, len(scored))}) · 제외 {len(blocked)}"
          f"{' · 상위 ' + top if top else ''}")
    if conf.get("automation") != "auto":
        return          # manual·assist 는 추천을 세우는 데서 끝난다(사람이 카드에서 건다)

    # ── 자동 선택 (사용자 지시 2026-08-25: "영상 선택은 이전처럼 알아서") ──────────
    # ⚠ 계획 §0 결정 2("자동 선별 폐기")의 번복이다. **발행은 여전히 사람**이다 —
    #   자동이 되는 것은 '오늘 무엇을 작업할지'까지고, 그 뒤 검수함·승인은 그대로다.
    n = auto_select(conn, conf, scored)
    if n:
        print(f"[loopy_picker] 자동 선택 {n}편 — 작업지시를 세웠다(발행은 사람 승인)")


def todays_auto_count(conn, slug: str) -> int:
    """오늘 자동으로 건 편수. 사람이 손으로 건 것(origin='manual')은 안 센다 —
    사람 결정이 자동 몫을 잡아먹으면 '왜 오늘은 자동이 안 돌지'가 된다."""
    with conn.cursor() as c:
        c.execute("""SELECT count(*) AS n FROM public.work_orders
                      WHERE channel_slug = %s AND origin = 'auto'
                        AND service_date = (now() AT TIME ZONE 'Asia/Seoul')::date
                        AND status <> 'cancelled'""", (slug,))
        return int((c.fetchone() or {}).get("n") or 0)


def auto_select(conn, conf: dict, scored: list) -> int:
    """상위부터 per_day 만큼 작업지시를 세운다. 반환: 실제로 건 편수.

    ⚠ 거는 일은 `_select_external_short_impl` 한 곳이 한다 — 사람 손(RPC)이 쓰는 것과
      **같은 함수**다. 두 벌로 나뉘면 자동 경로만 가드(중복·차단·롱폼 게이트)가 빠진다."""
    slug = conf["channel_slug"]
    per_day = int(conf.get("per_day") or 0)
    if per_day <= 0:
        return 0
    quota = per_day - todays_auto_count(conn, slug)
    if quota <= 0:
        return 0
    route = str(conf.get("route") or "B").upper()
    done = 0
    for r in scored:
        if done >= quota:
            break
        try:
            with conn.cursor() as c:
                c.execute("SELECT public._select_external_short_impl(%s,%s,%s,%s) AS r",
                          (r["video_id"], route, "loopy_picker 자동 선택", "auto"))
                got = (c.fetchone() or {}).get("r") or {}
            print(f"  [auto] {r.get('title') or r['video_id']} → "
                  f"{got.get('pipeline')} 잡 {got.get('jobs')}개")
            done += 1
        except Exception as e:                              # noqa: BLE001
            # 한 편이 거절돼도(이미 걸림·차단·스위치 off) 다음 후보로 간다 — 자동이
            # 한 편 때문에 통째로 멈추면 '오늘은 왜 아무것도 안 돌았지'가 된다.
            print(f"  [auto] 건너뜀 {r.get('video_id')}: {type(e).__name__} {e}")
            conn.rollback()
    return done
