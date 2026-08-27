#!/usr/bin/env python3
"""trend_report — 일일 트렌드·성과 리포트 생성기 (T-P2, 2026-08-27).

발주서: docs/TREND_REPORT.md §4·§5.

**facts 와 narrative 를 분리한다.** facts 는 SQL 집계(검증 가능한 숫자 전부)이고,
Gemini 는 그것을 설명만 한다 — 프롬프트가 "facts 밖의 숫자 금지"를 명시한다.
Gemini 가 죽어도 facts 만으로 리포트가 성립한다(narrative NULL, 화면은 안 죽는다).

판정 임계값은 ops_config.algo_constants 한 곳에서만 온다(§5). 길이는 독립 판정이
아니라 '이탈'의 처방 힌트다 — 8/26 실측에서 독립 길이 규칙이 최고 성과 7편을 전부
'길이 경고'로 찍는 걸 보고 뺐다.

날짜의 정직함: 원천(laeebly youtube_studio)이 며칠 지연되므로 리포트는 "가장 최근
데이터가 있는 날"(ref_date)을 기준으로 쓰고 data_lag_days 를 함께 싣는다 — 어제가
비었는데 어제라고 말하지 않는다.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import statistics

CONFIG_KEY = "trend_report"
DEFAULTS = {"enabled": False, "model": "gemini-3.6-flash", "narrative": True}
DEFAULT_K = {"sweet_spot_sec": [30, 45],
             "retention_min": {"lt30": 65.0, "30to60": 50.0},
             "impression_floor": 100, "ctr_floor": 2.0}

_NORM = re.compile(r"[^0-9a-z가-힣]")
_PAREN = re.compile(r"\([^)]*\)")
_KST = dt.timezone(dt.timedelta(hours=9))


# ───────── 순수 (테스트 대상) ─────────

def merge_config(raw) -> dict:
    """ops_config 값 → 설정. 깨졌으면 기본값(생성이 안 될 뿐 관제를 막지 않는다). 순수."""
    conf = dict(DEFAULTS)
    try:
        if raw:
            got = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(got, dict):
                conf.update({k: v for k, v in got.items() if k in DEFAULTS})
    except ValueError:
        pass
    return conf


def merge_constants(raw) -> dict:
    """algo_constants 병합 — retention_min 은 **키 단위로** 겹친다. 사람이 고치는 값이라
    부분만 써넣는 실수(lt30 만 남김)가 나오고, 얕은 병합이면 judge() 가 KeyError 로
    그날 리포트를 통째로 못 만든다(리뷰 지적). 순수 — 테스트 대상."""
    k = dict(DEFAULT_K)
    k["retention_min"] = dict(DEFAULT_K["retention_min"])
    try:
        got = json.loads(raw) if isinstance(raw, str) else (raw or {})
        if isinstance(got, dict):
            for kk, vv in got.items():
                if kk == "retention_min" and isinstance(vv, dict):
                    k["retention_min"].update(
                        {sk: sv for sk, sv in vv.items() if sk in k["retention_min"]})
                elif kk in DEFAULT_K:
                    k[kk] = vv
    except ValueError:
        pass
    return k


def judge(v: dict, k: dict) -> dict:
    """영상 1편의 깔때기 판정(§5) — 먼저 걸리는 데서 멈춘다. 순수.

    v: {impr, ctr, view_pct, len} (생애 합산·가중 평균). k: algo_constants."""
    impr = v.get("impr") or 0
    if impr < k["impression_floor"]:
        return {"verdict": "배포 안 됨",
                "hint": "채널·계정 문제 — 썸네일/훅 손대지 말 것"}
    ctr = v.get("ctr")
    if ctr is not None and ctr < k["ctr_floor"]:
        return {"verdict": "안 눌림", "hint": "제목·썸네일 재작업"}
    ln = v.get("len")
    if ln is None:
        return {"verdict": "정상", "hint": None}       # 길이 미상 — 깔때기 1·2단만 판정
    vp = v.get("view_pct")
    if vp is None:
        return {"verdict": "판정 보류", "hint": "완주율 데이터 없음"}
    thr = k["retention_min"]["lt30"] if ln < 30 else k["retention_min"]["30to60"]
    if vp < thr:
        hint = "훅 3초 재작업" + (" + 45초 초과 — 재단부터" if ln > 45 else "")
        return {"verdict": "이탈", "hint": hint}
    return {"verdict": "정상", "hint": None}


def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(statistics.median(vals), 2) if vals else None


def success_axes(vids: list) -> dict:
    """상위 10%(최소 1편) vs 나머지 — 축별 중앙값 대조(§5 성공 요인). 순수.

    표본 5 미만이면 빈 dict — 적은 표본의 대조는 노이즈다. 회귀·모델은 안 쓴다(과적합)."""
    vids = [v for v in vids if (v.get("views") or 0) > 0]
    if len(vids) < 5:
        return {}
    vids = sorted(vids, key=lambda v: v["views"], reverse=True)
    top_n = max(1, len(vids) // 10)
    top, rest = vids[:top_n], vids[top_n:]

    def axis(fn):
        return {"top": _median(fn(v) for v in top), "rest": _median(fn(v) for v in rest)}

    return {
        "top_n": top_n, "top_views_min": top[-1]["views"],
        "axes": {
            "len": axis(lambda v: v.get("len")),
            "publish_hour": axis(lambda v: v.get("publish_hour")),
            "shares_per_1k": axis(lambda v: round((v.get("shares") or 0) * 1000
                                                  / v["views"], 2)),
            "title_len": axis(lambda v: len(v.get("title") or "") or None),
        },
        "top_videos": [{"title": v.get("title"), "work": v.get("work"),
                        "views": v["views"], "len": v.get("len")} for v in top[:5]],
    }


def _norm(s: str) -> str:
    return _NORM.sub("", _PAREN.sub("", (s or "").lower()))


def cap_regions(trends: list, per_source: int = 10) -> dict:
    """지역별 트렌드 목록 — **소스별로** 상한을 건다. 순수 — 테스트 대상.

    리뷰 지적: 지역당 [:15] 일괄 절단은 정렬(google_trends < youtube_chart 사전순)과
    상호작용해 15칸이 검색 트렌드로 먼저 차고 **유튜브 차트가 통째로 잘려 나갔다** —
    수집은 됐는데 리포트가 주 소스를 매일 조용히 누락하는 버그."""
    regions: dict = {}
    used: dict = {}
    for t in trends:
        key = (t.get("region"), t.get("source"))
        if used.get(key, 0) >= per_source:
            continue
        used[key] = used.get(key, 0) + 1
        regions.setdefault(t.get("region"), []).append(
            {"rank": t.get("rank"), "source": t.get("source"), "title": t.get("title"),
             "category_id": t.get("category_id")})
    return regions


def match_overlaps(trends: list, works: list) -> list:
    """작품명 ↔ 트렌드 제목 정규화 부분일치(§6 — 문자열 매칭으로 시작한다). 순수."""
    hits = []
    for w in works:
        nw = _norm(w)
        if len(nw) < 2:
            continue
        for t in trends:
            if nw in _norm(t.get("title") or ""):
                hits.append({"work": w, "trend": t["title"], "region": t.get("region")})
    return hits


def parse_narrative(text):
    """Gemini 응답에서 JSON 오브젝트만 건진다 — 코드펜스·앞뒤 잡담 무시. 실패 시 None
    (리포트는 facts 만으로 성립한다). 순수."""
    if not text:
        return None
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        got = json.loads(text[a:b + 1])
    except ValueError:
        return None
    return got if isinstance(got, dict) else None


def build_prompt(facts: dict) -> str:
    """해설 프롬프트. facts 밖의 숫자를 금지한다 — 지어낸 수치는 대조로 잡힌다. 순수."""
    return (
        "너는 유튜브 쇼츠 다채널 운영팀의 일일 리포트 해설가다. 아래 facts(JSON)는 "
        "SQL 집계 결과이고 유일한 진실이다.\n\n"
        "규칙:\n"
        "· facts 에 없는 숫자를 절대 쓰지 마라. 수치를 인용할 땐 facts 값 그대로.\n"
        "· 판정(verdict)을 뒤집지 마라 — 이유를 풀어 설명만 한다.\n"
        "· 한국어로, 각 항목 2~4문장. 과장 없이.\n\n"
        "다음 키를 가진 JSON 하나만 출력하라(코드펜스 없이):\n"
        '{"summary": "오늘 한 줄 총평", "outside": "밖(트렌드) 해설", '
        '"inside": "안(작품 성과) 해설", "diagnosis": "진단 해설", '
        '"success": "성공 요인 해설", "actions": ["할 일 1", "할 일 2"]}\n\n'
        f"facts:\n{json.dumps(facts, ensure_ascii=False, default=str)}"
    )


def derive_actions(work_diag: list, overlaps: list) -> list:
    """§5 진단 → 기계적 액션 후보. Gemini 가 아니라 규칙이 만든다(재현 가능). 순수."""
    acts = []
    for w in work_diag:
        n = w.get("n_videos") or 0
        if n >= 3 and (w.get("n_blocked") or 0) >= n * 0.7:
            acts.append({"pri": 1, "text": f"「{w['work']}」 {w['n_blocked']}/{n}편 배포 안 됨"
                                           " — 채널·계정 점검. 콘텐츠 수정 금지"})
        elif n >= 3 and (w.get("n_exit") or 0) >= n * 0.5:
            acts.append({"pri": 2, "text": f"「{w['work']}」 {w['n_exit']}/{n}편 이탈"
                                           " — 훅 3초 재작업"})
    for h in overlaps[:5]:
        acts.append({"pri": 2, "text": f"「{h['work']}」 이 {h['region']} 트렌드에 등장"
                                       f" (\"{h['trend']}\") — 오늘 발행 우선 배정 검토"})
    return sorted(acts, key=lambda a: a["pri"])[:8]


# ───────── facts 조립 (SQL) ─────────

def _constants(conn) -> dict:
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key='algo_constants'")
        row = c.fetchone()
    return merge_constants((row or {}).get("value"))


def _rows(conn, sql, args=()):
    with conn.cursor() as c:
        c.execute(sql, args)
        return c.fetchall()


def build_facts(conn, today: dt.date) -> dict:
    """리포트 facts 전부 — 숫자는 여기서만 태어난다."""
    k = _constants(conn)

    ref = _rows(conn, "SELECT max(stat_date) AS d FROM public.perf_studio_daily")[0]["d"]
    lag = (today - ref).days if ref else None

    # §안 — 영상별 생애 깔때기(가중 평균) → 작품 롤업·진단·성공 요인의 공통 재료
    vids = _rows(conn, """
        SELECT d.content_id, max(d.work_title) AS work, max(d.video_title) AS title,
               max(d.channel_id) AS channel_id, max(d.video_length) AS len,
               max(d.publish_time) AS publish_time,
               sum(d.impressions)::bigint AS impr, sum(d.views)::bigint AS views,
               sum(d.impressions*d.ctr)/nullif(sum(d.impressions),0) AS ctr,
               sum(d.views*d.view_pct)/nullif(sum(d.views),0) AS view_pct,
               sum(d.shares)::bigint AS shares, sum(d.subscribers)::bigint AS subs
          FROM public.perf_studio_daily d GROUP BY d.content_id""")
    slug = {r["channel_id"]: r["token_slug"] for r in _rows(
        conn, "SELECT channel_id, token_slug FROM public.channels_mirror")}
    for v in vids:
        v["channel"] = slug.get(v["channel_id"], v["channel_id"])
        pt = v.get("publish_time")
        # 세션 TZ 가 UTC 라 .hour 를 그대로 쓰면 KST 발행 시각과 9시간 어긋난다(리뷰 지적)
        v["publish_hour"] = (pt.astimezone(_KST).hour if pt.tzinfo else pt.hour) if pt else None
        v["len"] = float(v["len"]) if v.get("len") is not None else None
        v["ctr"] = round(float(v["ctr"]), 2) if v.get("ctr") is not None else None
        v["view_pct"] = round(float(v["view_pct"]), 1) if v.get("view_pct") is not None else None
        v.update(judge(v, k))

    works: dict = {}
    for v in vids:
        w = works.setdefault(v["work"] or "(미매핑)", {
            "work": v["work"] or "(미매핑)", "n_videos": 0, "impr": 0, "views": 0,
            "_ctr_n": 0.0, "_vp_n": 0.0, "_vp_d": 0,
            "n_blocked": 0, "n_exit": 0, "n_noclick": 0, "n_hold": 0, "channels": set()})
        w["n_videos"] += 1
        w["impr"] += v["impr"] or 0
        w["views"] += v["views"] or 0
        w["_ctr_n"] += (v["ctr"] or 0) * (v["impr"] or 0)
        w["_vp_n"] += (v["view_pct"] or 0) * (v["views"] or 0)
        w["_vp_d"] += (v["views"] or 0) if v["view_pct"] is not None else 0
        w["channels"].add(v["channel"])
        w["n_blocked"] += v["verdict"] == "배포 안 됨"
        w["n_exit"] += v["verdict"] == "이탈"
        w["n_noclick"] += v["verdict"] == "안 눌림"
        w["n_hold"] += v["verdict"] == "판정 보류"
    work_rows = []
    for w in sorted(works.values(), key=lambda x: x["views"], reverse=True):
        work_rows.append({
            "work": w["work"], "n_videos": w["n_videos"], "impressions": w["impr"],
            "views": w["views"],
            "ctr": round(w["_ctr_n"] / w["impr"], 2) if w["impr"] else None,
            "view_pct": round(w["_vp_n"] / w["_vp_d"], 1) if w["_vp_d"] else None,
            "channels": sorted(w["channels"]),
            "n_blocked": w["n_blocked"], "n_exit": w["n_exit"],
            "n_noclick": w["n_noclick"], "n_hold": w["n_hold"]})

    # §밖 — 최신 수집일의 트렌드
    tdate_row = _rows(conn, "SELECT max(collected_date) AS d FROM public.trend_snapshot")
    tdate = tdate_row[0]["d"]
    trends = _rows(conn, """
        SELECT region, source, rank, title, category_id, view_count
          FROM public.trend_snapshot WHERE collected_date=%s
         ORDER BY region, source, rank""", (tdate,)) if tdate else []
    outside = {"collected_date": tdate, "regions": cap_regions(trends)}
    catmix: dict = {}
    for t in trends:
        if t["source"] == "youtube_chart" and t["category_id"]:
            catmix[t["category_id"]] = catmix.get(t["category_id"], 0) + 1
    outside["category_mix"] = catmix
    overlaps = match_overlaps(trends, [w["work"] for w in work_rows])
    outside["overlaps"] = overlaps

    # LOOPY — laeebly 밖(JP 오토파일럿)이라 원장 미러에서 따로 싣는다(출처 표시)
    loopy = _rows(conn, """
        SELECT count(*) FILTER (WHERE youtube_id IS NOT NULL) AS published,
               count(*) AS total FROM public.loopy_ledger""")
    loopy_recent = _rows(conn, """
        SELECT title, view_count, publish_at FROM public.loopy_ledger
         WHERE youtube_id IS NOT NULL ORDER BY publish_at DESC NULLS LAST LIMIT 5""")

    diag_vids = sorted([v for v in vids if v["verdict"] != "정상"],
                       key=lambda v: (v["verdict"] != "배포 안 됨", -(v["impr"] or 0)))
    return {
        "version": 1, "report_date": today, "ref_date": ref, "data_lag_days": lag,
        "constants": k,
        "outside": outside,
        "inside": {"works": work_rows},
        "diagnosis": {
            "counts": {v: sum(1 for x in vids if x["verdict"] == v)
                       for v in ("정상", "배포 안 됨", "안 눌림", "이탈", "판정 보류")},
            "videos": [{"content_id": v["content_id"], "title": v["title"],
                        "work": v["work"], "channel": v["channel"],
                        "impr": v["impr"], "ctr": v["ctr"], "view_pct": v["view_pct"],
                        "len": v["len"], "verdict": v["verdict"], "hint": v["hint"]}
                       for v in diag_vids[:60]]},
        "success": success_axes(vids),
        "actions": derive_actions(work_rows, overlaps),
        "zanmang": {"source": "loopy_ledger(JP·잔망루피)",
                  "published": loopy[0]["published"], "total": loopy[0]["total"],
                  "recent": loopy_recent},
    }


# ───────── 부수효과 ─────────

def _cfg(conn) -> dict:
    with conn.cursor() as c:
        c.execute("SELECT value FROM public.ops_config WHERE key=%s", (CONFIG_KEY,))
        row = c.fetchone()
    return merge_config((row or {}).get("value"))


def run(conn, cfg):
    conf = _cfg(conn)
    if not conf.get("enabled"):
        return          # 스위치 off — 켜고 끄는 것은 사람이다(ops_config.trend_report)
    kst = dt.timezone(dt.timedelta(hours=9))
    today = dt.datetime.now(kst).date()
    facts = build_facts(conn, today)

    narrative, status, model = None, "facts_only", conf["model"]
    prompt = build_prompt(facts)
    if conf.get("narrative"):
        from ves.scheduler import gemini_call
        key = gemini_call.resolve_key(conn, cfg)
        if not key:
            status = "no_gemini_key"
        else:
            try:
                narrative = parse_narrative(
                    gemini_call.generate(model, prompt, key))
                status = "ok" if narrative else "narrative_unparsable"
            except gemini_call.GeminiExhausted as e:
                # 소진 — 6대 공통 폴백에 합류시키고 이번 리포트는 facts 로 성립
                status = "gemini_exhausted"
                try:
                    from ves.agent import gemini_key
                    gemini_key.failover(conn, cfg, str(e))
                except Exception as fe:                     # noqa: BLE001
                    print(f"[trend_report] failover 실패(무시): {fe}")
            except Exception as e:                          # noqa: BLE001
                # 타입명만 남기면 원격에서 진단 불가(8/27: RuntimeError 만 보였다) — 상세를 싣는다
                status = f"gemini_error:{type(e).__name__}:{str(e)[:200]}"
                print(f"[trend_report] 해설 생성 실패(무시 — facts 로 성립): {e}")

    with conn.cursor() as c:
        c.execute(
            """INSERT INTO public.trend_report
                   (report_date, facts, narrative, model, prompt_sha, status, generated_at)
               VALUES (%s, %s, %s, %s, %s, %s, now())
               ON CONFLICT (report_date) DO UPDATE SET
                   facts=EXCLUDED.facts, narrative=EXCLUDED.narrative,
                   model=EXCLUDED.model, prompt_sha=EXCLUDED.prompt_sha,
                   status=EXCLUDED.status, generated_at=now()""",
            (today, json.dumps(facts, ensure_ascii=False, default=str),
             json.dumps(narrative, ensure_ascii=False) if narrative else None,
             model, hashlib.sha256(prompt.encode()).hexdigest()[:16], status))
    print(f"[trend_report] {today} 생성 — {status} "
          f"(작품 {len(facts['inside']['works'])} · 진단 {facts['diagnosis']['counts']})")
