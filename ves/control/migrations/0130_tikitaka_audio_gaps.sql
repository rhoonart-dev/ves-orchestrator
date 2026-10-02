-- 0130 원본 소리가 빈 자리(2026-10-02) — 완성본에서 원음이 나와야 하는 구간인데 소리가 완전히 빈 곳(-60dB · 0.25초 넘게).
-- 맥미니 tikitaka_upload 가 편을 올릴 때마다 적는다(편집실 다시 렌더 뒤에도). 검수 카드 · 편집실이 "원본 소리가 비어 있어요" 경고로 보인다.
ALTER TABLE public.tikitaka_videos ADD COLUMN audio_gaps jsonb;
COMMENT ON COLUMN public.tikitaka_videos.audio_gaps IS '원본 소리가 빈 자리 [{start, end}](완성본 초) — 없으면 [] · 아직 안 봤으면 null';

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0130','claude (원본 소리가 빈 자리)');
