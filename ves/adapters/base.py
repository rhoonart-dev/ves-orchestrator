#!/usr/bin/env python3
"""어댑터 계약 + 공용 순수 헬퍼. (ARCHITECTURE §6-6 · docs/CONTRACTS.md)

어댑터 = kind 1개를 처리하는 모듈. 두 스타일 중 하나:
  subprocess형: build_argv / resume_argv / parse_result / classify_error (+cwd, env)
  네이티브형:   run(cfg, conn, job) -> result dict
공통(선택): is_already_done(cfg, job)  · resource(cfg, job) -> 'gemini:VES01' | None
           · post_success(cfg, conn, job, result)
계약 원칙: 전부 순수(부수효과는 run/post_success 만) — 단위테스트 대상.
"""
from __future__ import annotations

import hashlib
import json


# ───────── 에러 클래스 (§6-5) — executor 가 error_class 로 사상 ─────────
class QuotaError(Exception):
    """쿼터 소진. until(재시도 가능 시각, ISO 문자열)을 줄 수 있다. attempt 미차감."""
    def __init__(self, msg, until=None):
        super().__init__(msg)
        self.until = until


class PermanentError(Exception):
    """재시도 무의미(소스 없음·설정 오류). 즉시 failed."""


class HumanRequired(Exception):
    """사람 개입 필요. blocked + (필요 시 review_queue 는 어댑터가 등록)."""


# ───────── 순수 헬퍼 ─────────
def canonical(obj) -> str:
    """params 정규화 — 키 순서·공백 무관 동일 문자열."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def idem_key(work_order_id, kind, params) -> str:
    """잡 생성 멱등키(§6-6): sha256(work_order_id | kind | canonical(params))."""
    raw = f"{work_order_id}|{kind}|{canonical(params or {})}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def backoff_minutes(attempt: int) -> int:
    """transient 지수 백오프: 1 → 3 → 9분 (§6-5)."""
    return 3 ** max(int(attempt) - 1, 0)


def classify_by_patterns(stderr: str, stdout: str = "") -> str:
    """공통 에러 분류 폴백 — 어댑터별 classify_error 가 먼저, 못 정하면 이걸로."""
    blob = f"{stderr}\n{stdout}".lower()
    if any(s in blob for s in ("429", "resource_exhausted", "quota", "rate limit")):
        return "quota"
    if any(s in blob for s in ("no such file", "filenotfound", "unrecognized arguments",
                               "invalid choice", "credential", "unauthorized")):
        return "permanent"
    return "transient"


_REGISTRY: dict = {}


def register(kind: str, module) -> None:
    _REGISTRY[kind] = module


def get(kind: str):
    if not _REGISTRY:
        _load_all()
    return _REGISTRY.get(kind)


def _load_all():
    """어댑터 지연 로드 — import 순환·무거운 의존 회피."""
    from ves.adapters import acquire, aivideo, brain, localize, upload_artifacts
    register("acquire", acquire)
    register("generate", aivideo)
    register("upload_artifacts", upload_artifacts)
    register("ingest", brain.Ingest)
    register("evaluate", brain.Evaluate)
    register("publish", brain.Publish)
    register("localize", localize)
