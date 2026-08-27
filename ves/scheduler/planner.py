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
    # scene_rerender 컷오버(8/13): JP 채널도 generate 는 기본(완전) 렌더 — 재렌더가
    # 체크포인트에서 일본어판을 새로 그리므로 '내용만 생성' 플래그가 필요 없다.
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
    if wo.get("pipeline") == "shorts_jp_overlay":
        # L-P5: 잔망루피 쇼츠 — **우리가 만들지 않은 완성본**이 입력이다. generate 가
        # 없으므로 체인이 짧고, 소스는 아카이브(external_shorts)가 고른 유튜브 영상이다.
        # 체인은 acquire → localize(overlay) **둘뿐**이다. 검수 카드(localization_qa)와
        # 산출 업로드는 localize 어댑터가 직접 한다(ves-localized · preview_key).
        # ⚠ 계획 §6-1 은 뒤에 upload_artifacts 를 뒀는데 **실물에서 죽는다**(0093):
        #   그 어댑터는 generate 런의 run_dir 에서 올리는데 overlay 에는 generate 가
        #   없다 — 실측 오류가 그대로 "generate 결과(run_id/run_dir) 없음" 이다.
        # ⚠ 캡은 "localize" 다 — overlay 는 OCR·인페인팅 스택이 있는 노드에서만 돈다
        #   (지금 mm-06 하나). generate 캡을 쓰면 스택 없는 노드가 집어 실패한다.
        return [
            ("acquire",          {**p_common, "source_url": wo.get("source_url"),
                                  "external_video_id": wo.get("external_video_id"),
                                  "download": True},                    ["network"], 600),
            ("localize",         {**p_common, "mode": "overlay",
                                  "external_video_id": wo.get("external_video_id"),
                                  "source_url": wo.get("source_url")},  ["localize"], LOCALIZE_LEASE),
        ]

    if wo.get("pipeline") == "shorts_jp_localized":
        # scene_rerender 컷오버(2026-08-13 사용자 결정): ai-video 생성분은 mm-06 GPU
        # 후처리(level B)도, mm-06 convert_short(등급 J)도 아니라 **생성 노드에서**
        # job 디렉토리를 재렌더한다 — 체크포인트의 텍스트를 일본어로 갈아끼우고 클린 렌더.
        # 캡 "generate"(+generate 완료 시 node:* 핀) — job 디렉토리·원본 소스가 그 노드에만 있다.
        # "localize" 캡(mm-06)은 zanmang_daily 등 완성-mp4 파이프라인 전용으로 남는다.
        # (등급 J convert_short 경로는 어댑터에 남아 있다 — run_channel_now 수동 체인이
        #  0030 으로 갱신될 때까지의 과도기 + 롤백 대비.)
        chain.append(("localize", {**p_common, "mode": "scene_rerender"},
                      ["generate"], LONG_LEASE))
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


def localize_level_for(slug: str, levels, default: str = "B") -> str:
    """채널 → 현지화 등급. 순수 — 테스트 대상. 알 수 없는 값은 기본값(안전측).

    A=자막 트랙만 · B=번인 제거+일본어 재합성 · C=B+더빙 · BC=번인제거+더빙(먹방류)
    · BJ=번인 유지 + 일본어 병기(겹치지 않게) — 인페인트·더빙 없음, ショトコン 용(8/12).
    설정이 비었거나 이상하면 종전 동작(B)을 유지한다 — 조용히 더빙으로 올라가지 않게."""
    v = str(((levels or {}).get(slug) or default)).upper()
    return v if v in ("A", "B", "BJ", "C", "BC", "J") else default


def _load_localize_cfg(conn, key: str) -> dict:
    """ops_config 의 채널별 현지화 설정({슬러그: 값} JSON). 없거나 깨졌으면 빈 dict.
      localize_levels   — 등급 A|B|BJ|C|BC
      localize_backends — 인페인트 백엔드(opencv|lama|sttn|propainter)
      localize_voices   — 더빙 ElevenLabs voice_id"""
    try:
        with conn.cursor() as c:
            c.execute("SELECT value FROM public.ops_config WHERE key=%s", (key,))
            row = c.fetchone()
        return json.loads((row or {}).get("value") or "{}")
    except Exception as e:  # noqa: BLE001 — 설정 오류가 계획을 막지 않는다
        print(f"[planner] {key} 조회 실패(기본값 진행): {e}")
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
    loc_lv = _load_localize_cfg(conn, "localize_levels")     # 채널별 현지화 등급(8/12)
    loc_bk = _load_localize_cfg(conn, "localize_backends")   # 인페인트 백엔드(8/13)
    loc_vo = _load_localize_cfg(conn, "localize_voices")     # 더빙 목소리(8/13)
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
            if _create_work_order(conn, cfg, today, ch, work, src,
                                  localize_level_for(slug, loc_lv),
                                  loc_bk.get(slug), loc_vo.get(slug)):
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


def pick_from_rows(rows, legacy=None):
    """정렬된 소스 행들 + 레거시 사용량 → 첫 사용 가능 행. 순수 — 테스트 대상.

    행(=영상) 단위 소진(0027): used_wo 는 그 행(sha/url)에 물린 WO 수다. 레거시
    (source_usage_legacy)는 회차 단위 기록이라 원래 행에 못 물렸다 — 그 회차의 앞선
    행부터 남는 한도만큼 차감해 물린다(회차에 행이 하나면 종전과 동일하게 동작).

    ★0039: 장부에 source_url 이 있으면 **그 영상에 정확히 물린다**. '앞선 행부터'는
      순서에 기대는 규칙이라, 정렬 기준이 바뀌면(published_ts 백필) 소진이 엉뚱한
      영상으로 옮겨간다 — 이미 쓴 영상이 풀려 같은 소재를 또 만들고, 안 쓴 영상은
      잠긴다. 아는 것은 못박고, 모르는 것만 종전 규칙으로 흘린다."""
    pinned, spread = {}, {}
    for r in (legacy or []):
        url = (r.get("source_url") or "").strip()
        if url:
            pinned[url] = pinned.get(url, 0) + int(r["used"])
        else:
            ep = r.get("episode")
            spread[ep] = spread.get(ep, 0) + int(r["used"])
    for row in rows or []:
        limit = int(row["use_limit"])
        tries = int(row["used_wo"])                       # 시도 — 반려·취소도 한 번
        # 0064: 한도는 발행분만 센다. used_pub 이 없는 호출(옛 테스트·구 DB)은 종전대로
        # 시도를 한도에 세던 동작으로 흘린다 — 조용히 한도를 풀어주지 않는다.
        used = int(row["used_pub"]) if row.get("used_pub") is not None else tries
        slack = int(row.get("retry_slack") if row.get("retry_slack") is not None else 3)
        ep, url = row.get("episode"), (row.get("source_url") or "").strip()
        free = max(limit - used, 0)
        take = min(free, pinned.pop(url, 0)) if url else 0   # ① 못박힌 몫 먼저
        if free - take > 0:                                  # ② 남는 여유에 회차 몫
            more = min(free - take, spread.get(ep, 0))
            if more:
                spread[ep] -= more
                take += more
        # 발행이 한도에 못 미쳐도, 시도가 상한(한도+여유)에 닿았으면 더 안 돈다 —
        # 반려가 반복될 때 같은 원본으로 생성이 무한정 돌아 비용이 새는 것을 막는다.
        if used + take < limit and tries + take < limit + slack:
            return row
    return None


def episode_order(prefer_latest: bool) -> str:
    """소스 정렬(0101). 순수 — 테스트 대상.

    기본은 회차 오름차순('오래된 것 = 낮은 번호' 규약 그대로). 작품 카드
    prefer_latest 는 내림차순 — 성과 검증 3차: 시즌8 은 3/28 방영인데 8월에 1~5화를
    올리고 있었고(4~5개월 지연), 같은 작품 1위는 당일 최신 회차로 편당 39.5만 회.
    방영 중 작품은 최신 회차부터 파는 게 맞다. 켜고 끄는 것은 사람이다(set_work_publish_policy)."""
    if prefer_latest:
        return "s.episode DESC NULLS LAST, COALESCE(s.published_ts, s.created_at) DESC, s.id"
    return "s.episode NULLS LAST, COALESCE(s.published_ts, s.created_at), s.id"


def _prefer_latest(conn, work) -> bool:
    """작품 카드의 최신 우선 스위치 — 0101 이전 DB(컬럼 없음)면 종전 동작(False)."""
    try:
        with conn.cursor() as c:
            c.execute("SELECT prefer_latest FROM public.work_cards WHERE work_title=%s", (work,))
            row = c.fetchone()
        return bool(row and row.get("prefer_latest"))
    except Exception as e:                                  # noqa: BLE001
        print(f"[planner] prefer_latest 조회 실패(종전 정렬): {e}")
        try:
            conn.rollback()
        except Exception:                                   # noqa: BLE001
            pass
        return False


def _pick_source(conn, work, pipeline="shorts_kr", episode=None, channel_slug=None):
    """소스 순환: 활성 소스 중 그 **채널이** 아직 use_limit 만큼 안 쓴 첫 행.

    ★소진은 채널별로 센다(사용자 결정 2026-08-12). SNL 시즌8을 몰입도둑과 킥킥극장이
      함께 쓰는데 종전엔 슬롯 3개를 나눠 썼다 — 한 채널이 다 쓰면 다른 채널이 굶었다.
      이제 채널마다 자기 3개를 갖는다.
    ★집계는 소스 **행(=영상) 단위**다(0027). 같은 회차에 영상이 여러 개라도 각자
      한도를 갖는다 — WO 가 sha(드라이브)/URL(유튜브)로 행에 고정돼 있어 그걸로 센다.
      (종전 (작품, 회차) 집계는 회차를 공유하는 영상들의 한도를 서로 잡아먹었다)
    ★레거시 루프가 이미 쓴 몫(source_usage_legacy)도 더해서 센다 — 구 시스템에서 공개까지
      마친 회차를 오케스트레이터가 처음부터 다시 돌지 않게 한다(차감 규칙은 pick_from_rows).
    ★0064: 한도(use_limit)는 **발행된 편수**로 센다. 반려·취소로 끝난 시도는 한도를
      깎지 않되, 시도 자체는 **한도 + 시도 여유**(작품 카드, 기본 3)에서 멈춘다.
    ★정렬: 기본 회차 오름차순 — 단 작품 카드 prefer_latest(0101)면 내림차순(최신 회차 먼저)
      (published_ts, 없으면 등록시각).
    episode 지정(0016) 시 그 회차만 — 소진이면 None(사람 결정을 조용히 바꾸지 않는다)."""
    with conn.cursor() as c:
        c.execute(
            """SELECT s.*,
                      (SELECT count(*) FROM public.work_orders w
                        WHERE w.status NOT IN ('cancelled','failed')
                          AND (%(ch)s::text IS NULL OR w.channel_slug = %(ch)s::text)
                          -- 매칭 정본은 DB 함수 하나다(0027) — 세는 곳이 여섯이라
                          -- 규칙을 복사하면 반드시 한 곳이 어긋난다.
                          AND public.wo_matches_source(
                                w.work_title, w.source_sha256, w.source_url,
                                s.work_title, s.sha256, s.source_url)) AS used_wo,
                      -- 0064: 한도는 '발행' 으로, 시도 상한은 위 used_wo 로 판정한다.
                      (SELECT count(*) FROM public.work_orders w
                        WHERE w.status NOT IN ('cancelled','failed')
                          AND (%(ch)s::text IS NULL OR w.channel_slug = %(ch)s::text)
                          AND public.wo_matches_source(
                                w.work_title, w.source_sha256, w.source_url,
                                s.work_title, s.sha256, s.source_url)
                          AND public.wo_published(w.id))                AS used_pub,
                      public.source_retry_slack(s.work_title)           AS retry_slack
                 FROM public.sources s
                WHERE s.work_title = %(work)s AND s.is_active
                  -- 하한 이하 소스는 쓰지 않는다(8/12 사용자 결정). 등록 때 걸러지지만,
                  -- 사람이 실수로 활성화해도 여기서 한 번 더 막는다. 길이 미상은 종전대로 사용.
                  -- 하한은 작품 카드값(0031) — 정본은 public.source_min_duration 하나다.
                  AND (s.duration_sec IS NULL
                       OR s.duration_sec > public.source_min_duration(s.work_title))
                  AND (%(ep)s::int IS NULL OR s.episode = %(ep)s::int)
                ORDER BY {order}""".format(order=episode_order(_prefer_latest(conn, work))),
            {"work": work, "ep": episode, "ch": channel_slug})
        rows = c.fetchall()
        legacy = []
        if channel_slug is not None:
            # source_url(0039)이 있으면 그 영상에 정확히 물린다. 컬럼이 아직 없는 DB
            # (코드가 마이그레이션보다 먼저 도는 창)에서는 종전 질의로 돌아간다.
            try:
                c.execute("""SELECT episode, used, source_url
                               FROM public.source_usage_legacy
                              WHERE work_title = %s AND channel_slug = %s""",
                          (work, channel_slug))
                legacy = c.fetchall()
            except Exception as e:  # noqa: BLE001 — 0039 이전 DB
                print(f"[planner] 장부 source_url 컬럼 없음 — 회차 단위로 진행: {e}")
                conn.rollback()
                with conn.cursor() as c2:
                    c2.execute("""SELECT episode, used FROM public.source_usage_legacy
                                   WHERE work_title = %s AND channel_slug = %s""",
                               (work, channel_slug))
                    legacy = c2.fetchall()
    return pick_from_rows(rows, legacy)


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


def _create_work_order(conn, cfg, today, ch, work, src, loc_level="B",
                       loc_backend=None, loc_voice=None) -> bool:
    # R7(하루 채널당 1건) 은 그대로다. 다만 0024 부터 유일 제약이 origin='planner' 행에만 걸린다 —
    # 관제 '작업 실행'(origin='manual')이 같은 날 한 편 더 넣을 수 있어야 하기 때문이다.
    # 부분 유니크 인덱스는 ON CONFLICT (4컬럼) 으로 추론되지 않으므로 존재 검사로 바꾼다.
    # 경합은 여전히 인덱스가 막는다(스케줄러는 advisory lock 으로 한 대만 도니 실사용상 단독).
    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.work_orders
                   (service_date, channel_slug, work_title, episode, source_sha256,
                    source_url, pipeline, geoblock_required, has_subtitle, origin)
               SELECT %(day)s,%(slug)s,%(work)s,%(ep)s,%(sha)s,%(url)s,%(pipe)s,%(geo)s,%(sub)s,
                      'planner'
                WHERE NOT EXISTS (SELECT 1 FROM public.work_orders w
                                   WHERE w.service_date  = %(day)s
                                     AND w.channel_slug  = %(slug)s
                                     AND w.work_title    = %(work)s
                                     AND w.pipeline      = %(pipe)s
                                     AND w.origin        = 'planner')
               RETURNING id""",
            {"day": today, "slug": ch["token_slug"], "work": work,
             "ep": src.get("episode"), "sha": src.get("sha256"),
             "url": src.get("source_url"),   # 0012: URL 소스(laeebly 유튜브형 이관)
             "pipe": pipeline_for(ch),
             "geo": _geoblock_required(cfg, work),
             "sub": bool(src.get("has_subtitle"))})
        row = c.fetchone()
    if row is None:
        return False   # R7 — 오늘 이미 있음(planner 재실행 멱등)
    wo_id = row["id"]

    wo = {"work_title": work, "episode": src.get("episode"), "channel_slug": ch["token_slug"],
          "channel_name": ch["name"], "source_sha256": src.get("sha256"),
          "source_url": src.get("source_url"),
          "has_subtitle": bool(src.get("has_subtitle")), "gcp_project": ch.get("gcp_project"),
          "pipeline": pipeline_for(ch), "knob_config": {},
          "localize_level": loc_level, "localize_backend": loc_backend,
          "localize_voice": loc_voice}
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
