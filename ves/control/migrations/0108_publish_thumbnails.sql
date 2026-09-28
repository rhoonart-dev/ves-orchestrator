-- 발행 썸네일 — 우리가 올린(또는 예약한) 쇼츠의 썸네일 이미지를 유튜브 영상 ID 기준으로 남긴다.
-- 예약 영상은 공개 전까지 유튜브 공개 썸네일(i.ytimg.com)이 없어서, VES Workspace 발행 일정 달력이 이 기록을 먼저 쓴다.
-- 파일은 ves-outputs 버킷의 publish_thumbs/<content_id>/<sha256>.<ext> (로그인한 사람은 이미 읽을 수 있는 버킷).
-- 쓰기는 서버(service_role)만 — 대시보드 발행 흐름이 썸네일 생성 결과에서 고른 '발행용' 썸네일을 올리고, 그 전까지는 사람이 올린 파일을 둔다.
CREATE TABLE public.publish_thumbnails (
 content_id text PRIMARY KEY CHECK (content_id ~ '^[A-Za-z0-9_-]{6,20}$'),
 object_key text NOT NULL CHECK (object_key LIKE 'publish_thumbs/%'),
 sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
 mime text NOT NULL CHECK (mime IN ('image/png','image/jpeg','image/webp')),
 width integer CHECK (width IS NULL OR width BETWEEN 16 AND 4096),
 height integer CHECK (height IS NULL OR height BETWEEN 16 AND 4096),
 source text NOT NULL CHECK (source IN ('ves_thumbnail','upload')),
 bundle_key text CHECK (bundle_key IS NULL OR length(bundle_key) BETWEEN 1 AND 300),
 pick_rank integer CHECK (pick_rank IS NULL OR pick_rank BETWEEN 1 AND 99),
 created_by uuid REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.publish_thumbnails ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.publish_thumbnails FROM anon, authenticated;
GRANT SELECT ON public.publish_thumbnails TO authenticated;
GRANT ALL ON public.publish_thumbnails TO service_role;
CREATE POLICY publish_thumbnails_read ON public.publish_thumbnails FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('viewer','reviewer','operator','admin')));
