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

LONG_LEASE = 300     # generate — 갱신 스레드가 TTL/4(75초)마다 연장한다(§6-2)
# localize 는 프레임마다 LaMa 인페인팅을 돌려 수십 분이 걸린다. 300초로는 갱신이 한두 번만
# 미끄러져도 reaper 가 산 잡을 회수해 '처음부터 다시'가 무한 반복된다 —
# 8/12 실측: ショトコン 5화가 [lease expired] 로 두 시간 동안 같은 자리를 맴돌았다.
LOCALIZE_LEASE = 3600


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
        ("acquire",          {**p_common, "source_url": wo.get("source_url"),
                              "source_sha256": wo.get("source_sha256")},      ["network"], 120),
        ("generate",         gen,                                              ["generate"], LONG_LEASE),
        ("upload_artifacts", dict(p_common),                                   ["analyze"], 120),
        ("ingest",           dict(p_common),                                   ["analyze"], 120),
        ("evaluate",         dict(p_common),                                   ["analyze"], 120),
    ]
    if wo.get("pipeline") == "shorts_jp_localized":
        chain.append(("localize", dict(p_common), ["localize"], LOCALIZE_LEASE))
    return chain


# ───────── 실행부 ─────────
def pipeline_for(ch: dict) -> str:
    """채널 → 파이프라인. JP 채널은 현지화 체인(generate 후 localize). 순수 — 테스트 대상."""
    return "shorts_jp_localized" if ch.get("country") == "JP" else "shorts_kr"


def plan_for_channel(works, ovr) -> tuple:
    """(시도할 작품 목록, 고정 회차 | None). 오버라이드(0016)가 정본 작품 안에 있을 때만
    적용 — 정본 밖이면 무시(자동 유지)하고 실행부가 경고를 찍는다. 순수 — 테스트 대상."""
    works = list(works or [])
    if not ovr or not ovr.get("work_title"):
        return works, None
    w = ovr["work_title"]
    if w not in works:
        return works, None
    return [w], ovr.get("episode")


def _load_plan_overrides(conn) -> dict:
    try:
        with conn.cursor() as c:
            c.execute("SELECT token_slug, work_title, episode FROM public.channel_plan_overrides")
            return {r["token_slug"]: r for r in c.fetchall()}
    except Exception as e:  # noqa: BLE001 — 0016 이전 DB 호환(테이블 없음 → 자동)
        print(f"[planner] plan_overrides 조회 실패(자동 진행): {e}")
        return {}


def _load_works_overrides(conn) -> dict:
    """0017: 채널 작품 배정 관제 수정본 — 있으면 channels.json works 대신 이것이 유효."""
    try:
        with conn.cursor() as c:
            c.execute("SELECT token_slug, works FROM public.channel_works_overrides")
            return {r["token_slug"]: list(r["works"] or []) for r in c.fetchall()}
    except Exception as e:  # noqa: BLE001
        print(f"[planner] works_overrides 조회 실패(파일 정본 진행): {e}")
        return {}


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
    plan_ovr = _load_plan_overrides(conn)    # 0016: 채널별 작품·회차 지정
    works_ovr = _load_works_overrides(conn)  # 0017: 채널 작품 배정 수정본
    made = 0
    for ch in channels:
        if ch.get("pipeline") == "zanmang_autopilot":
            continue  # 전용 파이프라인(§10-①) — zanmang_daily(매일 10시, mm-06)가 담당
        if ch.get("country") == "JP" and not jp_on:
            continue  # 스위치 off — 현지화 autopilot 담당 유지(이중 생산 방지)
        slug = ch.get("token_slug")
        eff_works = works_ovr.get(slug, ch.get("works"))
        ovr = plan_ovr.get(slug)
        works_try, pin_ep = plan_for_channel(eff_works, ovr)
        if ovr and ovr.get("work_title") and works_try != [ovr["work_title"]]:
            print(f"[planner] ⚠ {ch['name']}: 지정 작품 '{ovr['work_title']}' 이 "
                  f"채널 정본(works)에 없음 — 자동으로 진행(R14)")
        for work in works_try:
            src = _pick_source(conn, work, episode=pin_ep, channel_slug=slug)
            if src is None:
                if pin_ep is not None:
                    print(f"[ALERT] 지정 회차 사용 불가: {ch['name']} / {work} {pin_ep}회차 — "
                          f"소진·비활성·미등록. 관제에서 지정 해제 또는 회차 변경 필요")
                else:
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


def _pick_source(conn, work, pipeline="shorts_kr", episode=None, channel_slug=None):
    """회차 순환: 활성 소스 중 그 **채널이** 아직 use_limit 만큼 안 쓴 최저(=가장 오래된) 회차.

    ★소진은 채널별로 센다(사용자 결정 2026-08-12). SNL 시즌8을 몰입도둑과 킥킥극장이
      함께 쓰는데 종전엔 슬롯 3개를 나눠 썼다 — 한 채널이 다 쓰면 다른 채널이 굶었다.
      이제 채널마다 자기 3개를 갖는다.
    ★레거시 루프가 이미 쓴 몫(source_usage_legacy)도 더해서 센다 — 구 시스템에서 공개까지
      마친 회차를 오케스트레이터가 처음부터 다시 돌지 않게 한다.
    ★회차 번호는 '오래된 것 = 낮은 번호' 규약이다(register_playlist 가 그렇게 매긴다).
      그래서 최저 회차부터 = 오래된 것부터.
    episode 지정(0016) 시 그 회차만 — 소진이면 None(사람 결정을 조용히 바꾸지 않는다)."""
    with conn.cursor() as c:
        c.execute(
            """SELECT s.*,
                      (SELECT count(*) FROM public.work_orders w
                        WHERE w.work_title = s.work_title
                          AND w.episode IS NOT DISTINCT FROM s.episode
                          AND w.status NOT IN ('cancelled','failed')
                          AND (%(ch)s::text IS NULL OR w.channel_slug = %(ch)s::text)) AS used_wo,
                      coalesce((SELECT l.used FROM public.source_usage_legacy l
                                 WHERE l.work_title = s.work_title
                                   AND l.episode IS NOT DISTINCT FROM s.episode
                                   AND l.channel_slug = %(ch)s::text), 0) AS used_legacy
                 FROM public.sources s
                WHERE s.work_title = %(work)s AND s.is_active
                  -- 3분 이하 소스는 쓰지 않는다(8/12 사용자 결정). 등록 때 비활성으로 걸러지지만,
                  -- 사람이 실수로 활성화해도 여기서 한 번 더 막는다. 길이 미상은 종전대로 사용.
                  AND (s.duration_sec IS NULL OR s.duration_sec > 180)
                  AND (%(ep)s::int IS NULL OR s.episode = %(ep)s::int)
                ORDER BY s.episode NULLS LAST, s.created_at, s.id""",
            {"work": work, "ep": episode, "ch": channel_slug})
        for row in c.fetchall():
            if int(row["used_wo"]) + int(row["used_legacy"]) < int(row["use_limit"]):
                return row
    return None


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
