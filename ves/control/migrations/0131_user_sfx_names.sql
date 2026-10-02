-- 0131 편집실 효과음 이름(2026-10-02) — 사람마다 효과음에 붙인 이름. 자기 이름만 보고 고친다(다른 사람에게는 원래 이름).
CREATE TABLE public.user_sfx_names (
 user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 sfx_id text NOT NULL CHECK (sfx_id ~ '^[a-z0-9-]{1,64}$'),
 name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 30),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (user_id, sfx_id)
);
COMMENT ON TABLE public.user_sfx_names IS '편집실 효과음 이름 — 사람마다 따로(ai-video app/assets/sfx 파일 이름 = sfx_id)';
ALTER TABLE public.user_sfx_names ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_sfx_names_own ON public.user_sfx_names FOR ALL TO authenticated
 USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_sfx_names TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0131','claude (편집실 효과음 이름)');
