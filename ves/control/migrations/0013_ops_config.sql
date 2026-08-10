-- =====================================================================
-- 0013_ops_config.sql — 운영 설정 KV + 드라이브 자동 인입 (사용자 요청 2026-08-10)
-- 외부 작품 폴더(작품명 하위폴더 규약)를 drive_watch 가 매일 07시 KST 감시,
-- laeebly 드라이브형 작품 폴더도 함께 — sync_drive_folder 잡으로 인입.
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.ops_config (
    key        text PRIMARY KEY,
    value      text,
    note       text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.ops_config ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS read_all ON public.ops_config;
CREATE POLICY read_all ON public.ops_config FOR SELECT TO authenticated USING (true);

INSERT INTO public.ops_config(key, value, note)
VALUES ('drive_watch_folder',
        'https://drive.google.com/drive/folders/1nbob1KhTt-x68xKUKb8P8GoHfo2uqKSj',
        '외부 작품 소스 폴더 — 하위폴더명=작품명(laeebly 정본 표기), 매일 07시 감시')
ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value, note=EXCLUDED.note, updated_at=now();

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0013','claude-cloud (0013 ops_config·드라이브 자동 인입)')
ON CONFLICT DO NOTHING;
