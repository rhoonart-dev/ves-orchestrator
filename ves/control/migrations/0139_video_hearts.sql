-- 0139 영상 하트 · 닉네임(2026-10-02) — 검수하고 바로 발행하지 않을 때 "괜찮다"고 표시해 두는 하트. 팀이 같이 본다.
-- 검수 · 발행에는 영향 없음(기억용 표시). 누른 사람 · 시각을 남겨 마우스를 올리면 보여 준다.
CREATE TABLE public.tikitaka_video_hearts (
 video_id uuid PRIMARY KEY REFERENCES public.tikitaka_videos(id) ON DELETE CASCADE,
 hearted_by uuid DEFAULT auth.uid(),
 hearted_email text,
 hearted_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.tikitaka_video_hearts IS '작업 화면 영상 하트 — 괜찮다고 표시해 둔 영상(팀 공용)';
ALTER TABLE public.tikitaka_video_hearts ENABLE ROW LEVEL SECURITY;
CREATE POLICY tikitaka_video_hearts_read ON public.tikitaka_video_hearts FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.tikitaka_video_hearts TO authenticated;

CREATE OR REPLACE FUNCTION public.set_video_heart(p_video uuid, p_on boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_email text; r record;
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '검수자 권한이 필요해요'; END IF;
  IF NOT EXISTS (SELECT 1 FROM public.tikitaka_videos WHERE id = p_video) THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF NOT p_on THEN
    DELETE FROM public.tikitaka_video_hearts WHERE video_id = p_video;
    RETURN NULL;
  END IF;
  SELECT email INTO v_email FROM auth.users WHERE id = auth.uid();
  INSERT INTO public.tikitaka_video_hearts(video_id, hearted_by, hearted_email, hearted_at)
  VALUES (p_video, auth.uid(), v_email, now())
  ON CONFLICT (video_id) DO UPDATE SET hearted_by = EXCLUDED.hearted_by, hearted_email = EXCLUDED.hearted_email, hearted_at = now()
  RETURNING * INTO r;
  RETURN jsonb_build_object('hearted_email', r.hearted_email, 'hearted_at', r.hearted_at);
END $$;
REVOKE ALL ON FUNCTION public.set_video_heart(uuid, boolean) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_video_heart(uuid, boolean) TO authenticated;


-- 닉네임(같은 날) — 계정 창에서 정한다. 팀이 같이 보는 표시(하트를 누른 사람 등)에 이메일 대신 쓴다
CREATE TABLE public.user_profiles (
 user_id uuid PRIMARY KEY DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 nickname text CHECK (nickname IS NULL OR length(btrim(nickname)) BETWEEN 1 AND 20),
 updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.user_profiles IS '팀원 닉네임 — 하트 등 팀 공용 표시에 이메일 대신';
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_profiles_read ON public.user_profiles FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
CREATE POLICY user_profiles_write_own ON public.user_profiles FOR ALL TO authenticated
 USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_profiles TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0139','claude (영상 하트 · 닉네임)');
