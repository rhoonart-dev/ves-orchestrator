-- =====================================================================
-- 0061_editor_upload_orphans.sql — 편집실 업로드 GC 대장 (0056 후속)
-- 적용 순서: DB 먼저 무해 — 새 테이블 추가뿐, 읽고 쓰는 건 스케줄러
-- (editor_uploads_gc, service key)뿐이라 구 코드에 영향 없음.
--
-- editor_uploads/ 는 업로드 불변(0056: INSERT 정책만)이라 잘못 올리거나 빼버린
-- 이미지가 설계상 고아로 남는데, 지우는 코드가 여태 없어 전량 영구 누적된다.
-- 그런데 라운드 승계(0053/0059) 탓에 나이(TTL)만으로 지우면 살아있는 키를 죽인다
-- — generate 잡 params 에 실린 키는 재시도·재제출·반려 부활 때마다 어댑터가
-- 다시 다운로드한다(404 = PermanentError). 그래서 2회 스캔 규칙:
--   1차 스캔에서 미참조로 목격된 키를 여기 기록만 하고(first_seen),
--   유예(GRACE_DAYS) 뒤에도 여전히 미참조인 키만 지운다. 그 사이 다시
--   참조되면(초안 저장 지연·재제출) 기록을 걷어 사면한다.
-- 초안 자동저장이 실패하면 '키 발급→첫 영속 참조' 공백이 무제한이라
-- (dashboard 저장 실패 시 재시도 타이머 없음) 1회 판정은 금물이다.
-- 판정·삭제 주체는 ves/scheduler/editor_uploads_gc.py (일 1회 06:00).
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.editor_upload_orphans (
    key         text PRIMARY KEY,
    first_seen  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.editor_upload_orphans ENABLE ROW LEVEL SECURITY;
-- 정책 없음(의도) — 대시보드(authenticated)에 보일 이유가 없고,
-- 스케줄러는 service key(postgres 롤)라 RLS 를 우회한다.

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0061','claude (0061_editor_upload_orphans.sql 업로드 GC 대장)')
ON CONFLICT DO NOTHING;
