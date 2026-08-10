#!/usr/bin/env python3
"""planner — 하루치 work_order 생성 + 잡 DAG 전개 (§8-2, 매일 09:00 KST).

배정 정책(스켈레톤 기본값): 채널 1편/일 — 그 채널 works 중 아직 work_order 가 없는
등록 소스(회차)를 낮은 회차부터 하나. R7(UNIQUE)·R14(소스 필수·작품명 정본) 준수.
★① 지오블락 스탬프: laeebly guide 를 여기서(접근 가능한 쪽) 조회해 work_orders 에 각인.
   조회 실패 시 기본 true = 안전측(공개가 차단될 뿐 잘못 공개되지 않는다).
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib

from ves import config as cfgmod
from ves.adapters.base import idem_key

LONG_LEASE = 300   # generate/localize (§6-2)


# ───────── 순수 (테스트 대상) ─────────
def geoblock_from_guide(guide: str | None) -> bool:
    """laeebly licensed_video.guide 에 '지오블락' 포함 여부 (brain CLAUDE.md §3-1 규칙)."""
    return "지오블락" in (guide or "")


def norm_title(s: str) -> str:
    """작품명 대조용 — 공백 제거 비교(brain 규율: 한 글자 차이가 조회 전체를 깨뜨린다)."""
    return "".join((s or "").split())


def job_chain(wo: dict) -> list:
    """work_order → 잡 목록(kind, params, caps, lease, 의존은 순번). 순수 — 테스트 대상."""
    p_common = {"work_title": wo["work_title"], "episode": wo.get("episode"),
                "channel_slug": wo["channel_slug"], "channel_name": wo["channel_name"]}
    gen = {**p_common, "source_sha256": wo.get("source_sha256"),
           "source_url": wo.get("source_url"), "max_shorts": 1,
           "no_subtitles": not wo.get("has_subtitle", False),
           "flags": wo.get("knob_config") or {},
           "resource": f"gemini:{wo.get('gcp_project') or 'DEFAULT'}",
           "outdir": "outputs"}
    chain = [
        ("acquire",          {**p_common, "source_url": wo.get("source_url")}, ["network"], 120),
        ("generate",         gen,                                              ["generate"], LONG_LEASE),
        ("upload_artifacts", dict(p_common),                                   ["analyze"], 120),
        ("ingest",           dict(p_common),                                   ["analyze"], 120),
        ("evaluate",         dict(p_common),                                   ["analyze"], 120),
    ]
    if wo.get("pipeline") == "shorts_jp_localized":
        chain.append(("localize", dict(p_common), ["localize"], LONG_LEASE))
    return chain


# ───────── 실행부 ─────────
def pipeline_for(ch: dict) -> str:
    """채널 → 파이프라인. JP 채널은 현지화 체인(generate 후 localize). 순수 — 테스트 대상."""
    return "shorts_jp_localized" if ch.get("country") == "JP" else "shorts_kr"


def _jp_enabled(conn) -> bool:
    """JP 가동 스위치(ops_config.jp_pipeline='on') — 기존 현지화 autopilot 과의
    이중 생산을 막는 컷오버 장치(2026-08-10). 켜기 전에 구 autopilot 을 내릴 것."""
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key='jp_pipeline'")
        row = c.fetchone()
    return bool(row and row.get("value") == "on")


def run(conn, cfg):
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    channels = _load_channels(cfg)
    jp_on = _jp_enabled(conn)
    made = 0
    for ch in channels:
        if ch.get("country") == "JP" and not jp_on:
            continue  # 스위치 off — 현지화 autopilot 담당 유지(이중 생산 방지)
        for work in ch.get("works") or []:
            src = _pick_source(conn, work)
            if src is None:
                _note_missing_source(conn, work, ch)   # 지표14의 재료
                continue
            if _create_work_order(conn, cfg, today, ch, work, src):
                made += 1
            break   # 채널당 1편/일
    print(f"[planner] work_order {made}건 생성 ({today})")


def _load_channels(cfg):
    p = pathlib.Path(cfgmod.engine_dir(cfg, "brain")) / "config" / "channels.json"
    if not p.exists():
        print(f"[planner] channels.json 없음: {p}")
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    return data if isinstance(data, list) else data.get("channels") or []


def _pick_source(conn, work, pipeline="shorts_kr"):
    """회차 순환(사용자 결정 2026-08-07): 활성 소스 중 사용횟수(취소·실패 제외)가
    use_limit(기본 3) 미만인 최저 회차. 한도 도달 시 자동으로 다음 회차,
    전 회차 소진이면 None(→ 알림+대기, 관제 소스 섹션에 표시)."""
    with conn.cursor() as c:
        c.execute(
            """SELECT s.* FROM public.sources s
                LEFT JOIN public.work_orders w
                  ON w.work_title = s.work_title
                 AND w.episode IS NOT DISTINCT FROM s.episode
                 AND w.status NOT IN ('cancelled','failed')
                WHERE s.work_title = %s AND s.is_active
                GROUP BY s.id
               HAVING COUNT(w.id) < s.use_limit
                ORDER BY s.episode NULLS LAST LIMIT 1""", (work,))
        return c.fetchone()


def _geoblock_required(cfg, work) -> bool:
    """★① laeebly 조회(가능한 쪽에서 스탬프). 실패 = true(안전측)."""
    if not cfg.laeebly_url:
        return True
    try:
        from ves.db import connect
        lae = connect(cfg.laeebly_url)
        try:
            with lae.cursor() as c:
                c.execute("SELECT guide FROM licensed_video WHERE title=%s LIMIT 1", (work,))
                row = c.fetchone()
        finally:
            lae.close()
        if row is None:
            print(f"[planner] ⚠ laeebly 에 작품 없음: '{work}' — 정본 대조 실패(R14), 안전측 true")
            return True
        return geoblock_from_guide(row["guide"])
    except Exception as e:  # noqa: BLE001
        print(f"[planner] laeebly 조회 실패({e}) — 안전측 true")
        return True


def _create_work_order(conn, cfg, today, ch, work, src) -> bool:
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.work_orders
                   (service_date, channel_slug, work_title, episode, source_sha256,
                    source_url, pipeline, geoblock_required, has_subtitle)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (service_date, channel_slug, work_title, pipeline) DO NOTHING
               RETURNING id""",
            (today, ch["token_slug"], work, src.get("episode"), src.get("sha256"),
             src.get("source_url"),   # 0012: URL 소스(laeebly 유튜브형 이관)
             pipeline_for(ch),
             _geoblock_required(cfg, work), bool(src.get("has_subtitle"))))
        row = c.fetchone()
    if row is None:
        return False   # R7 — 오늘 이미 있음(planner 재실행 멱등)
    wo_id = row["id"]

    wo = {"work_title": work, "episode": src.get("episode"), "channel_slug": ch["token_slug"],
          "channel_name": ch["name"], "source_sha256": src.get("sha256"),
          "source_url": src.get("source_url"),
          "has_subtitle": bool(src.get("has_subtitle")), "gcp_project": ch.get("gcp_project"),
          "pipeline": pipeline_for(ch), "knob_config": {}}
    prev_id = None
    for kind, params, caps, ttl in job_chain(wo):
        with conn.cursor() as c:
            c.execute(
                """INSERT INTO public.job_queue
                       (work_order_id, kind, params, idempotency_key, depends_on,
                        required_caps, lease_ttl_sec)
                   VALUES (%s,%s,%s::jsonb,%s,%s,%s,%s)
                   ON CONFLICT (idempotency_key) DO UPDATE SET updated_at = now()
                   RETURNING id""",
                (wo_id, kind, json.dumps(params, ensure_ascii=False),
                 idem_key(wo_id, kind, params),
                 [prev_id] if prev_id else [], caps, ttl))
            prev_id = c.fetchone()["id"]
    return True


def _note_missing_source(conn, work, ch):
    """미등록과 소진을 구분해 알린다 — 관제 소스 섹션이 시각화(소진=빨간 칩)."""
    with conn.cursor() as c:
        c.execute("SELECT COUNT(*) AS n FROM public.sources WHERE work_title=%s AND is_active",
                  (work,))
        n = (c.fetchone() or {}).get("n", 0)
    why = "전 회차 소진(한도 도달) — 새 회차 보충 필요" if n else "소스 미등록"
    print(f"[ALERT] {why}: {ch['name']} / {work} — deploy/register_source.py 로 등록(지표14)")
