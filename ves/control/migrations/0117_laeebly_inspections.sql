-- 0117 — 권리사 검수를 웹에서 (2026-09-30)
-- 워크스페이스 권리사 검수 탭·홈·검수 정책은 작업 컴퓨터의 로컬 서버(rights_api)가 레이블리를 직접 읽었다.
-- 0116 laeebly_works 와 같은 방식으로 스케줄러 노드가 사본을 맞춘다(laeebly_sync, 2분마다). VES 채널(channels_mirror)의 것만.
--   laeebly_inspections  ← video_inspection (권리사 검수 요청 · 결과)
--   laeebly_applications ← channel_to_video (채널별 작품 사용 신청)
--   laeebly_works.inspection_policy ← licensed_video.inspection_policy (작품 검수 정책)

ALTER TABLE public.laeebly_works ADD COLUMN IF NOT EXISTS inspection_policy text;

CREATE TABLE IF NOT EXISTS public.laeebly_inspections (
 id text PRIMARY KEY,
 channel_id text,                 -- 레이블리 channel.id
 youtube_channel_id text,         -- 유튜브 채널 id(channels_mirror.channel_id 와 같은 값)
 channel_name text, video_title text, company text,
 episode int, episode_part int, round int, status text,
 revision_notes text, remarks text,
 created_at timestamptz, updated_at timestamptz, reviewed_at timestamptz, respond_by timestamptz,
 revision_outcome text, auto_approved_at timestamptz, supersedes_inspection_id text, revision_items jsonb,
 youtube_url text, file_link text, original_file_url text, published_youtube_url text,
 synced_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS laeebly_inspections_created ON public.laeebly_inspections (created_at DESC, id);

CREATE TABLE IF NOT EXISTS public.laeebly_applications (
 id text PRIMARY KEY,
 channel_id text, video_id text, status boolean, rejected_bool boolean, rh_verdict text,
 youtube_channel_id text, channel_title text, work_title text,
 synced_at timestamptz NOT NULL DEFAULT now()
);

DO $$ DECLARE t text; BEGIN
  FOREACH t IN ARRAY ARRAY['laeebly_inspections','laeebly_applications'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t);
    EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
    EXECUTE format('GRANT ALL ON public.%I TO service_role', t);
    EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_read', t);
    EXECUTE format('CREATE POLICY %I ON public.%I FOR SELECT TO authenticated USING (public.has_role((SELECT auth.uid()), ''viewer''))', t || '_read', t);
  END LOOP;
END $$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0117','claude (권리사 검수를 웹에서: 검수·사용 신청 사본 · 작품 검수 정책)');
