-- 0020: 채널 아이콘 자동 갱신 (2026-08-11 사용자 결정)
-- 목업은 유튜브 og:image 20개를 코드에 하드코딩했다 — 채널이 아이콘을 바꾸면 낡는다.
-- channels_sync(매일 08시)가 YouTube channels.list 로 갱신하고 관제는 이 값을 읽는다.
ALTER TABLE public.channels_mirror ADD COLUMN IF NOT EXISTS avatar_url text;
ALTER TABLE public.channels_mirror ADD COLUMN IF NOT EXISTS avatar_synced_at timestamptz;
