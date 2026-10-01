"""유튜브 원천 확인(0121) — 하루 한 번, 작품별 유튜브 원천(work_youtube_sources)마다 register_playlist 를 건다.

원천이 둘 이상인 작품은 그 뒤에 youtube_overlap 을 이어 건다 — 아래 순위 채널 클립이 위 채널 클립과 같은 장면을
담았는지 소리로 맞춰 보고 sources.overlap 에 적는다(합본 만들기 창이 그 결과로 잘라낼 구간을 미리 보여 준다).
여기서는 잡만 건다. 만들기(합본 · 쇼츠)는 사람이 소스 창고에서 누른다.
"""
from __future__ import annotations

import datetime as dt
import json

KST = dt.timezone(dt.timedelta(hours=9))


def plan(sources: list, today: str) -> list:
    """원천 목록 → 걸 잡 [(kind, params, idempotency_key, depends_on_keys)]. 순수 — 테스트 대상.
    같은 날 다시 불려도 멱등키가 같아 두 번 걸리지 않는다."""
    out, by_work = [], {}
    for s in sources:
        if not s.get("is_active"):
            continue
        key = f"ytwatch:{s['id']}:{today}"
        out.append(("register_playlist",
                    {"yt_source_id": str(s["id"]), "work_title": s["work_title"], "playlist_url": s["url"]},
                    key, []))
        by_work.setdefault(s["work_title"], []).append(key)
    for work, keys in sorted(by_work.items()):
        if len(keys) >= 2:
            out.append(("youtube_overlap", {"work_title": work}, f"ytoverlap:{work}:{today}", keys))
    return out


def enqueue(conn, jobs: list) -> int:
    made = 0
    ids: dict = {}
    with conn.cursor() as c:
        for kind, params, key, deps in jobs:
            dep_ids = [ids[k] for k in deps if k in ids]
            c.execute(
                """INSERT INTO public.job_queue(kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
                   VALUES (%s, %s::jsonb, %s, %s::uuid[], ARRAY['network'], %s, 90)
                   ON CONFLICT (idempotency_key) DO NOTHING RETURNING id""",
                (kind, json.dumps(params, ensure_ascii=False), key, dep_ids,
                 900 if kind == "youtube_overlap" else 300))
            row = c.fetchone()
            if row:
                made += 1
                ids[key] = row["id"]
            else:
                c.execute("SELECT id FROM public.job_queue WHERE idempotency_key=%s", (key,))
                ids[key] = c.fetchone()["id"]
    conn.commit()
    return made


def run(conn, cfg) -> int:
    with conn.cursor() as c:
        try:
            c.execute("SELECT id, work_title, url, is_active FROM public.work_youtube_sources ORDER BY work_title, rank")
        except Exception as e:  # noqa: BLE001 — 0121 이전 DB
            conn.rollback()
            print(f"[youtube_watch] 원천 표 없음(0121 미적용) — 건너뜀: {e}")
            return 0
        rows = c.fetchall()
    today = dt.datetime.now(KST).date().isoformat()
    made = enqueue(conn, plan(rows, today))
    print(f"[youtube_watch] 원천 {len(rows)}개 · 새 잡 {made}개")
    return made
