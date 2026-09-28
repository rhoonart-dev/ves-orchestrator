-- 0109 — 원본 유튜브 채널 목록 + 작품 공개 일정의 공개 종류·소스 위치 (VES Workspace 발행 일정, 2026-09-28)
-- 티빙 작품이어도 우리 쇼츠 원본은 티빙 공식 유튜브에서 받는 식이라, 공개 플랫폼과 소스 위치를 따로 둔다.
-- source_channels: 자주 쓰는 원본 채널(이름·주소·아이콘). 일정에서 고르고, 고른 채널을 작품 카드(work_cards.playlist_url)로도 저장할 수 있다.
CREATE TABLE public.source_channels (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 name text NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
 url text NOT NULL UNIQUE CHECK (url ~ '^https://(www\.)?youtube\.com/'),
 handle text CHECK (handle IS NULL OR length(handle) BETWEEN 1 AND 100),
 avatar_url text CHECK (avatar_url IS NULL OR avatar_url ~ '^https://'),
 created_by uuid DEFAULT auth.uid() REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.source_channels IS '원본 유튜브 채널 목록 — 작품 원본을 받는 공식 채널(티빙·tvN Joy 등). 발행 일정의 소스 위치에서 고른다';
ALTER TABLE public.source_channels ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.source_channels FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.source_channels TO authenticated;
GRANT ALL ON public.source_channels TO service_role;
CREATE POLICY source_channels_read ON public.source_channels FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('viewer','reviewer','operator','admin')));
CREATE POLICY source_channels_insert ON public.source_channels FOR INSERT TO authenticated
 WITH CHECK (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')));
CREATE POLICY source_channels_update ON public.source_channels FOR UPDATE TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')))
 WITH CHECK (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')));
CREATE POLICY source_channels_delete ON public.source_channels FOR DELETE TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')));

ALTER TABLE public.work_release_schedule
 ADD COLUMN release_kind text NOT NULL DEFAULT 'main' CHECK (release_kind IN ('main','preview','recap','trailer','other')),
 ADD COLUMN source_location text CHECK (source_location IS NULL OR source_location IN ('drive','youtube','other')),
 ADD COLUMN source_channel_id uuid REFERENCES public.source_channels(id) ON DELETE SET NULL;
COMMENT ON COLUMN public.work_release_schedule.release_kind IS '공개 종류 — main 본편 · preview 선공개 · recap 몰아보기 · trailer 예고편 · other 기타';
COMMENT ON COLUMN public.work_release_schedule.source_location IS '우리 쇼츠 원본을 받는 곳 — drive · youtube · other (공개 플랫폼과 따로)';

INSERT INTO public.source_channels(name,url,handle,avatar_url,created_by) VALUES
 ('TVING 티빙','https://www.youtube.com/@TVING_official','@TVING_official','https://yt3.googleusercontent.com/sBxnItKjolnANWriklnCVUuUJyY9sjZMEv5UJ842-vLXiT2tQvWiU6Qvgi-ncl_eWuGjNtBm=s88-c-k-c0x00ffffff-no-rj',NULL),
 ('tvN Joy','https://www.youtube.com/@tvNJoy_official','@tvNJoy_official','https://yt3.googleusercontent.com/bpSGI1weZmTuMvzXz0k9vwRDugXHTCDPc9qlih808OH88OKUHxhK6uzBGxbjzzQ5czMav9zVOQ=s88-c-k-c0x00ffffff-no-rj',NULL),
 ('커리어데이','https://www.youtube.com/@careerday_official','@careerday_official','https://yt3.googleusercontent.com/DvZHyF4wbPCikmn5cSMAaU_zgicwWCiCdjyjsgWfSDhB7QLuDTry-6QsY_WmTEKnLZ-3NBbOdQ=s88-c-k-c0x00ffffff-no-rj',NULL),
 ('B급 스튜디오','https://www.youtube.com/@B급studio','@B급studio','https://yt3.googleusercontent.com/kI247OuyP1-LneKOIhlpBRv7Lbq4ND5dcWfSLysajmd1IS3zKwJv5PtHehM4tsfjKzjm1PWqfg=s88-c-k-c0x00ffffff-no-rj',NULL);
