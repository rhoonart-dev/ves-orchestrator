#!/usr/bin/env python3
"""algo_watch — 알고리즘 상수 주간 조사기 (T-C3, 2026-08-27).

발주서: docs/TREND_REPORT.md §3-C3.

리포트 판정 임계값(ops_config.algo_constants — 쇼츠 스윗스팟·완주율 하한 등)은
유튜브가 공표하지 않는 역추론 값이다. 주 1회 Gemini + 검색 grounding 으로 다시
조사해 **제안값**(algo_constants_proposed)에만 기록한다.

**자동 반영하지 않는다** — 현행과 다르면 리포트 화면이 배지로 띄우고, 바꾸는 것은
사람이다(0080 규율의 상수판). 우리 실측이 쌓이면 외부 역추론보다 실측을 믿는다.
"""
from __future__ import annotations

import datetime as dt
import json

CONFIG_KEY = "algo_watch"
PROPOSED_KEY = "algo_constants_proposed"
DEFAULTS = {"enabled": False, "model": "gemini-2.5-flash", "interval_days": 7}

PROMPT = (
    "웹 검색으로 지금(오늘 기준) YouTube Shorts 추천 알고리즘의 임계값 통설을 조사하라. "
    "크리에이터 매체·Creator Insider 발언·최근 알고리즘 변경 소식을 근거로:\n"
    "1) 도달에 유리한 길이 구간(초)\n"
    "2) 더 넓은 배포를 받는 완주율 하한 — 30초 미만 / 30~60초 각각(%)\n"
    "3) 유의미한 판정에 필요한 최소 노출 수\n"
    "4) 정상으로 볼 CTR 하한(%)\n"
    "5) 최근 90일 내 중요한 알고리즘 변경(있으면)\n\n"
    "다음 형태의 JSON 하나만 출력하라(코드펜스 없이). 확실치 않으면 그 필드는 현행값을 "
    "유지하고 confidence 를 낮춰라. 모든 값은 역추론임을 잊지 마라:\n"
    '{"sweet_spot_sec": [30,45], "retention_min": {"lt30": 65.0, "30to60": 50.0}, '
    '"impression_floor": 100, "ctr_floor": 2.0, "confidence": "역추론", '
    '"changes": "최근 변경 요약 1~2문장", "sources": ["출처 URL", "..."]}'
)


# ───────── 순수 (테스트 대상) ─────────

def merge_config(raw) -> dict:
    conf = dict(DEFAULTS)
    try:
        if raw:
            got = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(got, dict):
                conf.update({k: v for k, v in got.items() if k in DEFAULTS})
    except ValueError:
        pass
    return conf


def weekly_due(checked_at_iso, now: dt.datetime, interval_days: int = 7) -> bool:
    """주 1회 게이트. 값이 없거나 깨졌으면 실행(fail-open — 조사 한 번이 싸다). 순수."""
    if not checked_at_iso:
        return True
    try:
        last = dt.datetime.fromisoformat(str(checked_at_iso))
        if last.tzinfo is None:
            last = last.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return True
    return (now - last) >= dt.timedelta(days=interval_days)


def sanitize_proposal(raw_text, current: dict, now_iso: str):
    """Gemini 응답 → 제안 행. 스키마 밖 키 제거·타입 강제. 못 읽으면 None. 순수."""
    from ves.scheduler.trend_report import parse_narrative
    got = parse_narrative(raw_text)
    if not got:
        return None
    out = dict(current)                       # 못 준 필드는 현행 유지
    try:
        if isinstance(got.get("sweet_spot_sec"), list) and len(got["sweet_spot_sec"]) == 2:
            out["sweet_spot_sec"] = [int(got["sweet_spot_sec"][0]),
                                     int(got["sweet_spot_sec"][1])]
        rm = got.get("retention_min")
        if isinstance(rm, dict):
            out["retention_min"] = {
                "lt30": float(rm.get("lt30", current["retention_min"]["lt30"])),
                "30to60": float(rm.get("30to60", current["retention_min"]["30to60"]))}
        if got.get("impression_floor") is not None:
            out["impression_floor"] = int(got["impression_floor"])
        if got.get("ctr_floor") is not None:
            out["ctr_floor"] = float(got["ctr_floor"])
    except (TypeError, ValueError):
        return None
    out["confidence"] = str(got.get("confidence") or "역추론")
    out["changes"] = str(got.get("changes") or "")[:500]
    out["sources"] = [str(s)[:200] for s in (got.get("sources") or [])[:8]]
    out["checked_at"] = now_iso
    out["differs"] = any(out.get(k) != current.get(k) for k in
                         ("sweet_spot_sec", "retention_min", "impression_floor", "ctr_floor"))
    return out


# ───────── 부수효과 ─────────

def run(conn, cfg):
    with conn.cursor() as c:
        c.execute("SELECT key, value FROM public.ops_config WHERE key = ANY(%s)",
                  ([CONFIG_KEY, PROPOSED_KEY, "algo_constants"],))
        rows = {r["key"]: r["value"] for r in c.fetchall()}
    conf = merge_config(rows.get(CONFIG_KEY))
    if not conf.get("enabled"):
        return
    now = dt.datetime.now(dt.timezone.utc)
    try:
        prev = json.loads(rows.get(PROPOSED_KEY) or "{}")
    except ValueError:
        prev = {}
    if not weekly_due(prev.get("checked_at"), now, int(conf["interval_days"])):
        return

    from ves.scheduler.trend_report import merge_constants
    current = merge_constants(rows.get("algo_constants"))

    from ves.scheduler import gemini_call
    key = gemini_call.resolve_key(conn, cfg)
    if not key:
        print("[algo_watch] GEMINI_API_KEY 없음 — 조사 건너뜀")
        return
    try:
        text = gemini_call.generate(conf["model"], PROMPT, key,
                                    search_grounding=True, timeout=120)
    except gemini_call.GeminiExhausted as e:
        try:
            from ves.agent import gemini_key
            gemini_key.failover(conn, cfg, str(e))
        except Exception as fe:                             # noqa: BLE001
            print(f"[algo_watch] failover 실패(무시): {fe}")
        print("[algo_watch] Gemini 소진 — 이번 주는 보류")
        return
    except Exception as e:                                  # noqa: BLE001
        print(f"[algo_watch] 조사 실패(무시 — 다음 주 재시도): {type(e).__name__} {e}")
        return

    proposal = sanitize_proposal(text, current, now.isoformat(timespec="seconds"))
    if not proposal:
        print("[algo_watch] 응답을 제안으로 파싱 못 함 — 이번 주는 보류")
        return
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.ops_config(key, value, note)
               VALUES (%s, %s, %s)
               ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()""",
            (PROPOSED_KEY, json.dumps(proposal, ensure_ascii=False),
             "알고리즘 상수 주간 조사 제안(T-C3, 코드가 씀) — 자동 반영 안 함. "
             "differs=true 면 리포트 화면이 배지로 띄운다. 반영은 사람이 algo_constants 를 고친다"))
    print(f"[algo_watch] 제안 기록 — differs={proposal['differs']} "
          f"confidence={proposal['confidence']}")
