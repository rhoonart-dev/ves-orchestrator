-- 0129 맥미니 영상 썸네일(2026-10-02) — 썸네일 엔진(ai-video app.tikitaka.thumbnail)은 그 편을 만든 맥미니의 작업 폴더가 있어야 돈다.
-- 웹에서 '썸네일 생성'을 누르면 그 맥미니에 tikitaka_thumbnails 잡을 걸고, 결과(thumbnails.json · 그림)는 ves-outputs 에 올려 여기 적는다.
-- 작업 컴퓨터 영상은 예전처럼 로컬 서버가 만든다(scripts/local_videos_api run_thumbnails). 쓰기는 아래 RPC 로만(검수자부터).
CREATE TABLE public.tikitaka_thumbnails (
 video_id uuid PRIMARY KEY REFERENCES public.tikitaka_videos(id) ON DELETE CASCADE,
 state text NOT NULL CHECK (state IN ('running','done','failed')),
 action text, error text, job_id uuid,
 doc jsonb, manual jsonb,
 files jsonb NOT NULL DEFAULT '{}'::jsonb,
 publish jsonb,
 version bigint NOT NULL DEFAULT 0,
 requested_by uuid DEFAULT auth.uid(),
 started_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.tikitaka_thumbnails IS '맥미니 영상 썸네일 — doc(thumbnails.json) · manual(사람이 고른 목록) · files{상대경로: ves-outputs 키} · publish(발행용 고른 것)';
ALTER TABLE public.tikitaka_thumbnails ENABLE ROW LEVEL SECURITY;
CREATE POLICY tikitaka_thumbnails_read ON public.tikitaka_thumbnails FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.tikitaka_thumbnails TO authenticated;

-- 만들기 · 고른 목록으로 다시 · 처음 추천으로. 그 편을 만든 맥미니에 잡을 건다(작업 폴더가 거기 있다)
CREATE OR REPLACE FUNCTION public.request_tikitaka_thumbnails(p_video uuid, p_action text DEFAULT 'run', p_manual jsonb DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record; t record; job uuid;
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '썸네일을 만들려면 검수자 또는 관리자 권한이 필요합니다.'; END IF;
  IF p_action NOT IN ('run','manual','reset') THEN RAISE EXCEPTION '알 수 없는 요청이에요.'; END IF;
  IF p_action = 'manual' AND (jsonb_typeof(p_manual) <> 'array' OR jsonb_array_length(p_manual) NOT BETWEEN 1 AND 8) THEN
    RAISE EXCEPTION '썸네일은 1~8장까지 고를 수 있어요.';
  END IF;
  SELECT id, work_order_id, suffix, node_id INTO v FROM public.tikitaka_videos WHERE id = p_video;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF v.node_id IS NULL THEN RAISE EXCEPTION '이 영상을 만든 맥미니를 알 수 없어요'; END IF;
  IF EXISTS (SELECT 1 FROM public.job_queue WHERE kind = 'tikitaka_apply_edit' AND params->>'video_id' = p_video::text AND status IN ('pending','running')) THEN
    RAISE EXCEPTION '이 영상을 다시 렌더하는 중이에요. 끝난 뒤 만들어 주세요.';
  END IF;
  SELECT * INTO t FROM public.tikitaka_thumbnails WHERE video_id = p_video FOR UPDATE;
  IF FOUND AND t.state = 'running' AND EXISTS (SELECT 1 FROM public.job_queue WHERE id = t.job_id AND status IN ('pending','running')) THEN
    RAISE EXCEPTION '이 영상의 썸네일을 만드는 중이에요.';
  END IF;
  INSERT INTO public.job_queue(work_order_id, kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
  VALUES (v.work_order_id, 'tikitaka_thumbnails',
          jsonb_build_object('video_id', v.id, 'work_order_id', v.work_order_id, 'suffix', v.suffix, 'action', p_action, 'manual', p_manual),
          'tikitaka-thumbs:' || v.id || ':' || to_char(clock_timestamp(), 'YYYYMMDDHH24MISSMS'),
          ARRAY['generate', 'node:' || v.node_id], 300, 170)
  RETURNING id INTO job;
  INSERT INTO public.tikitaka_thumbnails(video_id, state, action, error, job_id, requested_by, started_at, updated_at)
  VALUES (p_video, 'running', p_action, NULL, job, auth.uid(), now(), now())
  ON CONFLICT (video_id) DO UPDATE SET state = 'running', action = p_action, error = NULL, job_id = job,
    requested_by = auth.uid(), started_at = now(), updated_at = now(),
    publish = NULL;   -- 다시 만들면 번호의 그림이 바뀐다 — 발행용은 새로 고른다
  PERFORM public._audit('request_tikitaka_thumbnails', 'tikitaka_thumbnails', p_video::text, jsonb_build_object('action', p_action, 'job', job));
  RETURN jsonb_build_object('state', 'running', 'job', job);
END $$;

-- 발행용 고르기(새로 만들지 않음) — rank 비우면 고른 것 취소
CREATE OR REPLACE FUNCTION public.choose_tikitaka_thumbnail(p_video uuid, p_rank integer)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE t record; pick jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '썸네일을 고르려면 검수자 또는 관리자 권한이 필요합니다.'; END IF;
  SELECT * INTO t FROM public.tikitaka_thumbnails WHERE video_id = p_video FOR UPDATE;
  IF NOT FOUND OR t.doc IS NULL THEN RAISE EXCEPTION '썸네일을 먼저 만들어 주세요.'; END IF;
  IF p_rank IS NULL THEN UPDATE public.tikitaka_thumbnails SET publish = NULL, updated_at = now() WHERE video_id = p_video; RETURN; END IF;
  SELECT p INTO pick FROM jsonb_array_elements(t.doc->'picks') p WHERE (p->>'rank')::int = p_rank LIMIT 1;
  IF pick IS NULL OR NOT (t.files ? (pick->>'file')) THEN RAISE EXCEPTION '고른 썸네일을 찾을 수 없어요. 다시 만든 뒤 골라 주세요.'; END IF;
  UPDATE public.tikitaka_thumbnails SET publish = jsonb_build_object('rank', p_rank, 'file', pick->>'file',
      'key', t.files->>(pick->>'file'), 'chosen_by', auth.uid(), 'chosen_at', now()), updated_at = now()
   WHERE video_id = p_video;
  PERFORM public._audit('choose_tikitaka_thumbnail', 'tikitaka_thumbnails', p_video::text, jsonb_build_object('rank', p_rank));
END $$;

REVOKE ALL ON FUNCTION public.request_tikitaka_thumbnails(uuid, text, jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_tikitaka_thumbnails(uuid, text, jsonb) TO authenticated;
REVOKE ALL ON FUNCTION public.choose_tikitaka_thumbnail(uuid, integer) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.choose_tikitaka_thumbnail(uuid, integer) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0129','claude (맥미니 영상 썸네일)');
