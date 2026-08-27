#!/usr/bin/env python3
"""gemini_call — 스케줄러가 Gemini 를 직접 부를 때의 얇은 공용층 (T-P2, 2026-08-27).

엔진(ai-video·brain)은 서브프로세스로 Gemini 를 부르지만, 스케줄러의 저빈도 호출
(일일 리포트 해설 1회·주간 알고리즘 조사 1회)에 엔진을 태우는 건 과하다 — 여기서
urllib 로 직접 부른다(스케줄러 HTTP 관례: loopy_scout._api_get 과 같은 stdlib).

키는 **기존 폴백 체계에 합류**한다(ves/agent/gemini_key.py, 0025):
  · 키 값은 env 파일에만 있다 — DB·로그 금지 (ARCHITECTURE §5·§11)
  · 어느 슬롯(primary/fallback)을 쓸지는 ops_config.gemini_key 가 정한다
  · 429 소진 문구를 만나면 failover 로 6대 공통 전환에 합류 — 되돌리기는 사람이

동시성: 워커 세마포어(resources.acquire) 밖이지만 일 1회 수준이라 상한과 무관하다.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiExhausted(RuntimeError):
    """선불 크레딧/쿼터 소진 — 호출자가 failover 를 태울 수 있게 구분한다."""


def extract_text(payload) -> str:
    """generateContent 응답 → 텍스트. 후보·parts 가 비어도 죽지 않는다(빈 문자열). 순수."""
    if not isinstance(payload, dict):
        return ""
    cands = payload.get("candidates") or [{}]
    parts = ((cands[0] or {}).get("content") or {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def resolve_key(conn, cfg) -> str | None:
    """지금 활성 슬롯의 키. 호출 시점에 env 파일을 다시 읽는다(yt_public.api_key 관례
    — 기동 후 사람이 키를 넣어도 재기동 없이 보이게)."""
    import os

    from ves import config as cfgmod
    from ves.agent import gemini_key
    env = dict(os.environ)
    try:
        for k, v in cfgmod.file_env().items():
            env.setdefault(k, v)
    except Exception:                                      # noqa: BLE001
        pass
    try:
        slot = gemini_key.active(conn)
    except Exception:                                      # noqa: BLE001
        slot = "primary"
    env = gemini_key.apply(env, slot, base=env)   # 예비 키도 재독한 env 에서 찾는다
    key = (env.get("GEMINI_API_KEY") or "").strip()
    return key or None


def generate(model: str, prompt: str, api_key: str,
             search_grounding: bool = False, timeout: int = 90) -> str:
    """generateContent 1회. 텍스트를 돌려준다. 소진이면 GeminiExhausted.

    재시도 없음 — 스케줄러 태스크가 멱등이라 다음 날 재실행이 재시도다(관례)."""
    body: dict = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    if search_grounding:
        body["tools"] = [{"google_search": {}}]
    req = urllib.request.Request(
        f"{API_BASE}/{model}:generateContent?key={api_key}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 — 고정 도메인
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:                                  # noqa: BLE001
            pass
        from ves.agent import gemini_key
        if e.code == 429 and gemini_key.is_account_exhausted(detail):
            raise GeminiExhausted(detail[:400]) from e
        raise RuntimeError(f"Gemini HTTP {e.code}: {detail[:200]}") from e
    return extract_text(payload)
