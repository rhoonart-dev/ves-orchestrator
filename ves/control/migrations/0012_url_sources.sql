-- =====================================================================
-- 0012_url_sources.sql — URL 소스 지원 (구 관제 데이터 이관, 사용자 요청 2026-08-09)
-- laeebly 의 유튜브형 작품(플레이리스트/공식채널)을 sources 로 직접 등록하기 위해
-- 파일(sha) 없이 source_url 만으로도 소스가 성립하게 한다. acquire→generate 의
-- --youtube-url 경로는 스모크3에서 이미 검증된 그 경로다.
-- =====================================================================
ALTER TABLE public.sources ALTER COLUMN sha256 DROP NOT NULL;
ALTER TABLE public.sources ALTER COLUMN object_key DROP NOT NULL;
ALTER TABLE public.sources ADD COLUMN IF NOT EXISTS source_url text;
DO $$ BEGIN
  ALTER TABLE public.sources ADD CONSTRAINT sources_locator_chk
    CHECK (source_url IS NOT NULL OR (sha256 IS NOT NULL AND object_key IS NOT NULL));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
-- URL 소스는 (작품, 회차)당 1행 — register_playlist 잡 재실행 멱등의 근거
CREATE UNIQUE INDEX IF NOT EXISTS sources_url_uniq
  ON public.sources (work_title, (COALESCE(episode, -1))) WHERE source_url IS NOT NULL;
ALTER TABLE public.work_orders ADD COLUMN IF NOT EXISTS source_url text;
INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0012','claude-cloud (0012 URL 소스 — laeebly 유튜브형 이관)')
ON CONFLICT DO NOTHING;
