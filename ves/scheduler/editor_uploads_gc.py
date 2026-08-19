#!/usr/bin/env python3
"""editor_uploads_gc — 편집실 업로드 이미지 고아 수거 (0056 후속, 일 1회 06:00).

editor_uploads/ 는 업로드 불변(0056: INSERT 정책만 — 잘못 올리면 새로 올리고
옛것은 버려진다)이라 고아가 설계상 생기는데, 지우는 코드가 여태 없어 전량
영구 누적됐다. 단, 라운드 승계(0053/0059) 탓에 나이만으로 지우면 살아있는
키를 죽인다: generate 잡 params 의 키는 재시도·재제출·반려 부활 때마다
어댑터가 스토리지에서 **다시 다운로드**한다(localize_edit_images, 404 는
PermanentError '업로드가 지워졌거나 초안이 낡았습니다').

보호 술어(하나라도 참이면 삭제 금지) — 반드시 **한 문장**(단일 스냅샷)으로 평가:
  (A) 어떤 편집 초안(editor_assets.draft.images[].key)이든 참조 — 보낸 적 없는
      초안은 무기한 유효('이어서 하기'가 언제든 복원, del 행도 undo 로 부활)
  (B) generate 잡 params.edit_overrides.images[].key 참조 중
      · 비성공 상태 전부 — pending/running/blocked/failed/dead 에 **cancelled**
        포함(retry_editor_chain·reject_review 가 params 그대로 pending 으로
        되살린다: 0050/0055)
      · 또는 작업지시별 최신(created_at DESC — 0055 규약) succeeded —
        prev_images 시드(0057)와 다음 라운드 승계(0059 v_prev)의 원천
  ※ 두 갈래를 시각차 있는 쿼리 둘로 나누면 reject_review 의 succeeded→pending
    플립과 경합해 양쪽 다 놓친다 — 한 문장이어야 하는 이유.

삭제는 2회 스캔 규칙: 미참조 키를 editor_upload_orphans(0061)에 기록만 하고,
GRACE_DAYS 뒤에도 여전히 미참조면 그때 지운다. 초안 자동저장이 실패하면
'키 발급→첫 영속 참조' 공백이 무제한이라(대시보드 저장 실패 시 재시도 타이머
없음) 1회 판정은 금물이고, 다시 참조된 키는 기록을 걷어 사면한다.
스토리지 목록이 진실이라 전체가 멱등 — 어느 단계가 실패해도 다음 주기가 보충.
0056 경고대로 키의 run_id 세그먼트는 신뢰하지 않는다(위조 가능) — 술어는
정확한 키 대조뿐, 세그먼트→run 역산은 어디에도 없다.
"""
from __future__ import annotations

import datetime as dt

from ves.storage.supabase_storage import Store

BUCKET = "ves-outputs"
PREFIX = "editor_uploads/"
GRACE_DAYS = 14         # 미참조 첫 목격 → 삭제까지. 이미지 수십 KB~수 MB 라 후하게.
DELETE_BATCH = 100      # storage_gc 와 같은 분할 폭

# 보호 키 전량 — 단일 문장(단일 스냅샷)이어야 한다(모듈 머리말 ※).
# jsonb_array_elements 는 배열이 아니면 에러라 CASE 로 무장한다(초안엔 images 가
# 없거나 obj 인 과도기 값이 있을 수 있다 — 방어가 곧 계약).
PROTECTED_SQL = """
WITH gen AS (
  SELECT j.id, j.work_order_id, j.status, j.created_at,
         CASE WHEN jsonb_typeof(j.params->'edit_overrides'->'images') = 'array'
              THEN j.params->'edit_overrides'->'images' ELSE '[]'::jsonb END AS imgs
    FROM public.job_queue j
   WHERE j.kind = 'generate'
), latest_ok AS (
  SELECT DISTINCT ON (work_order_id) id
    FROM gen WHERE status = 'succeeded'
   ORDER BY work_order_id, created_at DESC
)
SELECT DISTINCT im->>'key' AS k
  FROM gen, jsonb_array_elements(gen.imgs) im
 WHERE (gen.status <> 'succeeded' OR gen.id IN (SELECT id FROM latest_ok))
   AND im->>'key' LIKE 'editor_uploads/%'
UNION
SELECT DISTINCT im->>'key' AS k
  FROM public.editor_assets ea,
       jsonb_array_elements(
         CASE WHEN jsonb_typeof(ea.draft->'images') = 'array'
              THEN ea.draft->'images' ELSE '[]'::jsonb END) im
 WHERE im->>'key' LIKE 'editor_uploads/%'
"""


def plan(keys, protected, marked, now, grace):
    """순수 판정 — 테스트 대상. keys = 스토리지 실물(진실), protected = 보호 술어
    통과 키, marked = {key: first_seen}. 반환 (pardon, mark, due):
      pardon = 대장에서 걷을 키 — 다시 참조됐거나 실물이 이미 사라진 기록,
      mark   = 처음 미참조로 목격된 키(기록만 — 이번 주기엔 안 지운다),
      due    = 유예 내내 미참조가 확인돼 지울 키."""
    keys, protected = set(keys), set(protected)
    orphans = keys - protected
    pardon = sorted(k for k in marked if k in protected or k not in keys)
    mark = sorted(orphans - set(marked))
    due = sorted(k for k in orphans if k in marked and now - marked[k] >= grace)
    return pardon, mark, due


def run(conn, cfg):
    store = Store(cfg.supabase_url, cfg.supabase_service_key)
    keys = store.list_keys(BUCKET, PREFIX)
    with conn.cursor() as c:
        c.execute(PROTECTED_SQL)
        protected = [r["k"] for r in c.fetchall()]
        c.execute("SELECT key, first_seen FROM public.editor_upload_orphans")
        marked = {r["key"]: r["first_seen"] for r in c.fetchall()}
    now = dt.datetime.now(dt.timezone.utc)
    pardon, mark, due = plan(keys, protected, marked, now,
                             dt.timedelta(days=GRACE_DAYS))
    if due:
        # 삭제 직전 재평가 — 첫 스냅샷과 삭제 사이(목록·plan 수 초)에 초안 저장이나
        # 제출이 키를 되살릴 수 있다. 창을 완전히 없애진 못해도 수 초로 좁힌다.
        with conn.cursor() as c:
            c.execute(PROTECTED_SQL)
            alive = {r["k"] for r in c.fetchall()}
        due = [k for k in due if k not in alive]
    # 삭제 먼저, 대장 정리는 성공분만(storage_gc 규율 — 실패분은 다음 주기 재시도)
    deleted: list = []
    for n in range(0, len(due), DELETE_BATCH):
        batch = due[n:n + DELETE_BATCH]
        try:
            store.delete(BUCKET, batch)
            deleted += batch
        except Exception as e:  # noqa: BLE001
            print(f"[editor_uploads_gc] 삭제 실패(다음 주기 재시도): {e}")
            break
    with conn.cursor() as c:
        gone = pardon + deleted
        if gone:
            c.execute("DELETE FROM public.editor_upload_orphans WHERE key = ANY(%s)",
                      (gone,))
        if mark:
            c.execute("INSERT INTO public.editor_upload_orphans(key) "
                      "SELECT unnest(%s::text[]) ON CONFLICT (key) DO NOTHING",
                      (mark,))
    print(f"[editor_uploads_gc] 실물 {len(keys)} · 보호 {len(protected)} · "
          f"신규기록 {len(mark)} · 사면 {len(pardon)} · 삭제 {len(deleted)}")
