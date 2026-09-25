-- Immutable work assets. Current selection is the newest version per work/role.
CREATE TABLE public.work_asset_versions (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_id text NOT NULL,
 work_title text NOT NULL CHECK (length(work_title) BETWEEN 1 AND 300),
 role text NOT NULL CHECK (role IN ('work_logo','platform_logo','reference')),
 object_key text NOT NULL UNIQUE CHECK (object_key LIKE 'works/%' AND object_key NOT LIKE '%..%'),
 sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
 filename text NOT NULL,
 mime text NOT NULL CHECK (mime IN ('image/png','image/jpeg','image/webp','application/pdf')),
 bytes integer NOT NULL CHECK (bytes BETWEEN 1 AND 6291456),
 width integer, height integer,
 render_width integer NOT NULL DEFAULT 620 CHECK (render_width BETWEEN 16 AND 1080),
 render_height integer NOT NULL DEFAULT 300 CHECK (render_height BETWEEN 16 AND 1920),
 created_by uuid NOT NULL REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX work_asset_versions_lookup ON public.work_asset_versions(work_title,role,created_at DESC,id DESC);
ALTER TABLE public.work_asset_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.work_asset_versions FROM anon, authenticated;
GRANT SELECT ON public.work_asset_versions TO authenticated;
CREATE POLICY work_assets_read ON public.work_asset_versions FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('viewer','reviewer','operator','admin')));
GRANT ALL ON public.work_asset_versions TO service_role;
-- Pins include an empty list: retries must never pick up newly uploaded assets.
CREATE TABLE public.work_asset_pins (
 job_id uuid PRIMARY KEY REFERENCES public.job_queue(id),
 work_title text NOT NULL,
 manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest)='array'),
 created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.work_asset_pins ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.work_asset_pins FROM anon,authenticated;
GRANT ALL ON public.work_asset_pins TO service_role;
