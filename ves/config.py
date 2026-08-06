#!/usr/bin/env python3
"""노드/스케줄러 공통 설정 — env 파일 로드.

로드 순서(먼저 있는 값 우선): os.environ → /etc/ves/node.env → $VES_HOME/secrets/ves.env
시크릿은 env 파일에만 둔다(코드/DB 금지). 근거: ARCHITECTURE §5·§11.
"""
from __future__ import annotations

import os
import pathlib
from dataclasses import dataclass

DEFAULT_HOME = "/opt/ves"
NODE_ENV = "/etc/ves/node.env"

# engine 논리명 → engines/ 하위 디렉토리명 (deployments.engine 과 일치해야 함)
ENGINE_DIRS = {
    "ai_video": "ai-video",
    "localization": "video-localization-project",
    "brain": "ai-improvement-edit-video",
    "orchestrator": None,  # $VES_HOME/orchestrator (자기 자신)
}


def _load_env_file(path):
    """KEY=VALUE 단순 파서(따옴표 허용). brain scripts/envload.py 와 같은 계약."""
    p = pathlib.Path(path)
    if not p.exists():
        return {}
    out = {}
    for ln in p.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_env():
    home = os.environ.get("VES_HOME", DEFAULT_HOME)
    for path in (NODE_ENV, f"{home}/secrets/ves.env"):
        for k, v in _load_env_file(path).items():
            os.environ.setdefault(k, v)


@dataclass
class Config:
    home: str
    node_id: str
    capabilities: list
    max_concurrency: int
    db_url: str
    laeebly_url: str | None
    supabase_url: str | None
    supabase_service_key: str | None
    poll_sec: float = 180.0      # 유휴 폴링 간격(초). 일감 있는 동안은 연속 — sleep은 빈 큐에서만
    poll_max_sec: float = 180.0  # 유휴 백오프 상한


def get_config() -> Config:
    load_env()
    home = os.environ.get("VES_HOME", DEFAULT_HOME)
    return Config(
        home=home,
        node_id=os.environ.get("VES_NODE_ID", "dev-local"),
        capabilities=[c.strip() for c in os.environ.get("VES_CAPABILITIES", "").split(",") if c.strip()],
        max_concurrency=int(os.environ.get("VES_MAX_CONCURRENCY", "1")),
        db_url=os.environ.get("PIPELINE_DB_URL", ""),
        laeebly_url=os.environ.get("LAEEBLY_DB_URL"),
        supabase_url=os.environ.get("SUPABASE_URL"),
        supabase_service_key=os.environ.get("SUPABASE_SERVICE_KEY"),
        poll_sec=float(os.environ.get("VES_POLL_SEC", "180")),
        poll_max_sec=float(os.environ.get("VES_POLL_MAX_SEC", "180")),
    )


def engine_dir(cfg: Config, engine: str) -> str:
    sub = ENGINE_DIRS.get(engine)
    return f"{cfg.home}/orchestrator" if sub is None else f"{cfg.home}/engines/{sub}"


def engine_py(cfg: Config, engine: str) -> str:
    """엔진별 venv 파이썬 (★④ 공용 venv 폐지 — ARCHITECTURE §11-2)."""
    return f"{engine_dir(cfg, engine)}/.venv/bin/python"


def source_cache_path(cfg: Config, sha256: str) -> str:
    """content-addressed 마스터 캐시 — sha 만으로 경로가 결정된다(잡 간 데이터 전달 불필요)."""
    return f"{cfg.home}/cache/sources/{sha256}"
