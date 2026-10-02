-- 0132 다시 만든 영상 '봤음'(2026-10-02) — 편집을 반영해 다시 렌더된 영상은 작업 화면 카드에 초록 점이 뜨고, 그 사람이 열어 보면 사라진다.
-- 사람마다 따로. seen_job = 마지막으로 본 다시 렌더 잡(job_queue tikitaka_apply_edit id) — 또 고쳐서 새로 렌더되면 다시 뜬다.
CREATE TABLE public.user_seen_renders (
 user_id uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id) ON DELETE CASCADE,
 video_id uuid NOT NULL REFERENCES public.tikitaka_videos(id) ON DELETE CASCADE,
 seen_job uuid NOT NULL,
 seen_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (user_id, video_id)
);
COMMENT ON TABLE public.user_seen_renders IS '작업 화면: 다시 렌더된 영상을 그 사람이 열어 봤는지(초록 점)';
ALTER TABLE public.user_seen_renders ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_seen_renders_own ON public.user_seen_renders FOR ALL TO authenticated
 USING (user_id = (SELECT auth.uid())) WITH CHECK (user_id = (SELECT auth.uid()));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_seen_renders TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0132','claude (다시 만든 영상 봤음)');
