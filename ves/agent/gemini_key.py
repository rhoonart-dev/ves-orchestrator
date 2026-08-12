#!/usr/bin/env python3
"""Gemini 키 슬롯 — 주 키가 막히면 6대가 함께 예비 키로 넘어간다 (2026-08-12 사용자 요청).

## 왜 '예비 키'가 아니라 '예비 **계정**'인가

8/12 저녁 429 의 원문은 분당 rate limit 이 아니었다:

    429 RESOURCE_EXHAUSTED — "Your billing account has exceeded its monthly
    spending cap. Please go to AI Studio at https://ai.studio/billing"

상한은 **키가 아니라 결제 계정**에 걸린다. 같은 계정에서 새 키를 발급해도 똑같이 429 다.
그래서 GEMINI_API_KEY_FALLBACK 에는 **다른 결제 계정**의 키를 넣어야 의미가 있다.
(가장 빠른 해제는 ai.studio/billing 에서 상한을 올리는 것이다 — 이 모듈은 그때까지 버티는 장치다.)

## 설계

  · **키 값은 종전대로 env 파일에만.** 코드·DB 금지(ARCHITECTURE §5·§11, config.py 머리말).
    ves.env 에 `GEMINI_API_KEY`(주) 와 `GEMINI_API_KEY_FALLBACK`(예비)을 함께 둔다.
  · **어느 쪽을 쓸지만 DB 가 정한다** — `ops_config.gemini_key` = primary | fallback.
    값이 아니라 선택이라 DB 에 둬도 시크릿이 새지 않는다. 6대가 **다음 잡부터** 함께 바뀐다
    (잡마다 읽으므로 워커 재시작 불필요 — §5 '돌고 있는 프로세스는 나중 .env 를 안 읽는다' 회피).
  · **엔진은 손대지 않는다.** ai-video·brain 둘 다 GEMINI_API_KEY 하나만 안다.
    executor 가 서브프로세스 env 를 만들 때 그 이름에 활성 슬롯 값을 넣어준다.
  · **되돌리기는 사람이.** 자동 복귀는 플래핑을 만든다 — 관제 [주 키로 되돌리기] 또는 SQL 한 줄.
"""
from __future__ import annotations

import os

from ves.obs import notify

SWITCH = "gemini_key"
PRIMARY = "primary"
FALLBACK = "fallback"
ENV_BY_SLOT = {PRIMARY: "GEMINI_API_KEY", FALLBACK: "GEMINI_API_KEY_FALLBACK"}

# 계정이 통째로 막힌 신호 — 기다려도 안 풀린다(예비 키로 넘어갈 사유).
_EXHAUSTED = (
    "spending cap",            # 유료: 월 지출 상한 (8/12 실측 원문)
    "billing account",         # 〃
    "exceeded your current quota",   # 무료 티어 소진
    "check your plan and billing",   # 〃 (같은 메시지의 뒷부분)
)


# ───────── 순수 (테스트 대상) ─────────
def is_account_exhausted(msg) -> bool:
    """지출 상한·계정 소진인가 — 분당 rate limit 과 구분한다.

    분당 초과(RPM)는 기다리면 풀린다. 그때 예비 키로 넘기면 백업 계정을 공짜로 태우는 셈이라,
    **계정 소진이라는 적극적 신호가 있을 때만** True 다. 애매하면 False(보수적).
    """
    b = (msg or "").lower()
    if "429" not in b and "resource_exhausted" not in b:
        return False
    return any(s in b for s in _EXHAUSTED)


def available_slots(env=None) -> list:
    """이 맥에 실제로 값이 들어 있는 슬롯. 6대 배포가 어디까지 됐는지 보는 재료
    (heartbeat 가 node_registry.meta 로 올리고 관제 '맥·배포'가 보여준다)."""
    e = os.environ if env is None else env
    return [s for s in (PRIMARY, FALLBACK) if (e.get(ENV_BY_SLOT[s]) or "").strip()]


def apply(env, slot: str, base=None):
    """활성 슬롯의 키를 GEMINI_API_KEY 로 세워 돌려준다. 순수 — 테스트 대상.

    · primary 이거나 이 맥에 예비 키가 없으면 env 를 **그대로** 돌려준다(None 포함).
      평상시 동작을 한 글자도 바꾸지 않기 위해서다.
    · GOOGLE_API_KEY 는 **이미 있을 때만** 같이 갈아끼운다. google-genai 는 두 이름을 다 보는데,
      없던 이름을 새로 만들면 엔진 쪽 설정과 어긋날 수 있다.
    """
    src = os.environ if base is None else base
    if slot != FALLBACK:
        return env
    val = (src.get(ENV_BY_SLOT[FALLBACK]) or "").strip()
    if not val:
        return env                      # 예비 키 미배포 맥 — 종전대로 주 키로 돈다
    out = dict(src if env is None else env)
    out["GEMINI_API_KEY"] = val
    if (out.get("GOOGLE_API_KEY") or "").strip():
        out["GOOGLE_API_KEY"] = val
    return out


# ───────── DB ─────────
def active(conn) -> str:
    """지금 6대가 쓰는 슬롯. 값이 없거나 이상하면 primary(안전측)."""
    try:
        with conn.cursor() as c:
            c.execute("SELECT value FROM public.ops_config WHERE key=%s", (SWITCH,))
            row = c.fetchone()
    except Exception as e:  # noqa: BLE001 — 0025 이전 DB·조회 실패는 종전 동작으로 강등
        print(f"[gemini_key] 슬롯 조회 실패(주 키로 진행): {e}")
        return PRIMARY
    v = (row or {}).get("value")
    return v if v in ENV_BY_SLOT else PRIMARY


def switch(conn, slot: str, why: str) -> None:
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.ops_config(key, value, note)
               VALUES (%s,%s,%s)
               ON CONFLICT (key) DO UPDATE
                 SET value=EXCLUDED.value, note=EXCLUDED.note, updated_at=now()""",
            (SWITCH, slot, why))


def requeue_quota_waiters(conn) -> int:
    """쿼터로 한 시간 뒤에 세워둔 잡들을 지금 다시 세운다.

    quota 실패는 run_after 를 now()+1h 로 민다(lease.fail). 키를 갈아끼웠는데 그대로 두면
    전환 효과가 최대 한 시간 뒤에야 나타난다. 시각은 DB now() 로만 계산한다(노드 시계 불신).
    """
    with conn.cursor() as c:
        c.execute("""UPDATE public.job_queue
                        SET run_after = now(), updated_at = now()
                      WHERE status = 'pending' AND error_class = 'quota'
                        AND run_after > now()""")
        return c.rowcount or 0


def failover(conn, cfg, msg) -> bool:
    """지출 상한이면 예비 키로 넘긴다. 실제로 넘겼으면 True.

    넘기지 않는 세 경우 — 각각 다른 알림을 낸다:
      · 계정 소진 신호가 아님(분당 rate limit 등)  → 조용히 False
      · 이미 예비 키인데 또 터짐                    → 두 계정 다 막힘, 사람이 상한을 올려야 한다
      · 이 맥에 예비 키가 없음                      → 배포 누락, 넘겨도 이 맥은 못 쓴다
    """
    if not is_account_exhausted(msg):
        return False
    node = getattr(cfg, "node_id", "?")
    if active(conn) == FALLBACK:
        notify.alert("Gemini 예비 키까지 지출 상한 초과 — 두 계정 모두 막혔습니다. "
                     "ai.studio/billing 에서 상한을 올려야 회전이 재개됩니다")
        return False
    if FALLBACK not in available_slots():
        notify.alert(f"Gemini 주 키 지출 상한 초과 — 그런데 {node} 에 예비 키가 없습니다. "
                     f"ves.env 에 GEMINI_API_KEY_FALLBACK 을 넣고 워커를 재시작하세요")
        return False
    switch(conn, FALLBACK, f"{node} 자동 전환 — 주 키 지출 상한 초과")
    n = requeue_quota_waiters(conn)
    notify.alert(f"Gemini 예비 키로 자동 전환했습니다(6대 공통, 다음 잡부터). "
                 f"대기 중이던 잡 {n}건을 즉시 재시도로 돌렸습니다. "
                 f"주 키 상한을 올린 뒤 관제에서 [주 키로 되돌리기] 하세요")
    return True
