-- 0125 잡 진행 단계(2026-10-01) — 맥미니가 엔진을 돌리는 동안 어디까지 했는지(받아쓰기 · 장면 분석 · 대본 · 렌더 3/14)를 적는다.
-- 실행기가 30초마다 어댑터의 progress() 를 불러 바뀌었을 때만 쓴다. 작업 목록 · 작업 이력 · 홈이 읽는다.
ALTER TABLE public.job_queue ADD COLUMN progress jsonb, ADD COLUMN progress_at timestamptz;
COMMENT ON COLUMN public.job_queue.progress IS '진행 단계 {stage, label, done:[...], rendered, total, sec_per_video, steps:{단계: 시각}} — 어댑터 progress() 가 채운다';

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0125','claude (잡 진행 단계)');
