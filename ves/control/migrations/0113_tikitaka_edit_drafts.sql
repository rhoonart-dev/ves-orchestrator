-- 0113 — 맥미니 영상 편집: 초안은 데이터베이스에, 제출은 RPC 로 (2026-09-29)
-- 편집은 대시보드에서, 다시 렌더는 그 편을 만든 맥미니가(0111 tikitaka_apply_edit). 초안이 작업 컴퓨터 캐시에 있으면
-- 다른 컴퓨터·웹에서 이어갈 수 없고 '내 편집 | 모두'도 못 나눈다 — 사람별·편별로 표에 둔다.
-- 제출(request_tikitaka_edit)은 로컬 서버 없이 브라우저에서 부른다(웹사이트 이전 계획 4단계).

CREATE TABLE IF NOT EXISTS public.tikitaka_edit_drafts (
 video_id uuid NOT NULL REFERENCES public.tikitaka_videos(id) ON DELETE CASCADE,
 user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
 email text,
 based_on text NOT NULL,                        -- 이 초안을 연 판(render_fingerprint)
 draft jsonb NOT NULL,                          -- 편집실 초안 그대로(workspace_editor_draft)
 saved_at timestamptz NOT NULL DEFAULT now(),
 submitted_job uuid,                            -- 제출한 뒤엔 그 잡 — '이어서 할 편집'에서 빠지고 실패하면 되살린다
 PRIMARY KEY (video_id, user_id)
);
CREATE INDEX IF NOT EXISTS tikitaka_edit_drafts_saved ON public.tikitaka_edit_drafts (saved_at DESC);
ALTER TABLE public.tikitaka_edit_drafts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tikitaka_edit_drafts FROM anon, authenticated;
GRANT SELECT ON public.tikitaka_edit_drafts TO authenticated;
GRANT ALL ON public.tikitaka_edit_drafts TO service_role;
DROP POLICY IF EXISTS tikitaka_edit_drafts_read ON public.tikitaka_edit_drafts;
CREATE POLICY tikitaka_edit_drafts_read ON public.tikitaka_edit_drafts FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'reviewer'));

-- 초안 저장 — 자기 초안만. 제출했던 초안을 다시 고치면 submitted_job 을 비워 다시 '이어서 할 편집'이 된다
CREATE OR REPLACE FUNCTION public.save_tikitaka_draft(p_video uuid, p_based_on text, p_draft jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_fp text; v_at timestamptz := now();
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '편집하려면 검수자 권한이 필요해요'; END IF;
  IF p_draft IS NULL OR jsonb_typeof(p_draft) <> 'object' THEN RAISE EXCEPTION '초안 형식이 이상해요'; END IF;
  IF octet_length(p_draft::text) > 1500000 THEN RAISE EXCEPTION '초안이 너무 커요'; END IF;
  SELECT render_fingerprint INTO v_fp FROM public.tikitaka_videos WHERE id = p_video;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF v_fp IS DISTINCT FROM p_based_on THEN
    RAISE EXCEPTION '편집실을 연 뒤에 영상이 새로 만들어졌어요. 편집실을 다시 열어 주세요';
  END IF;
  INSERT INTO public.tikitaka_edit_drafts(video_id, user_id, email, based_on, draft, saved_at, submitted_job)
  VALUES (p_video, auth.uid(), (SELECT email FROM auth.users WHERE id = auth.uid()), p_based_on, p_draft, v_at, NULL)
  ON CONFLICT (video_id, user_id) DO UPDATE SET based_on = EXCLUDED.based_on, draft = EXCLUDED.draft,
    email = EXCLUDED.email, saved_at = v_at, submitted_job = NULL;
  RETURN jsonb_build_object('saved_at', v_at);
END $$;
REVOKE ALL ON FUNCTION public.save_tikitaka_draft(uuid, text, jsonb) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.save_tikitaka_draft(uuid, text, jsonb) TO authenticated;

-- 제출 — 그 편을 만든 맥미니에 다시 렌더 잡(tikitaka_apply_edit)을 건다. 규칙은 워크스페이스 로컬 서버의 제출과 같다
CREATE OR REPLACE FUNCTION public.request_tikitaka_edit(p_video uuid, p_overrides jsonb, p_based_on text, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record; v_job uuid; v_email text;
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '편집하려면 검수자 권한이 필요해요'; END IF;
  IF p_overrides IS NULL OR jsonb_typeof(p_overrides) <> 'object' OR p_overrides = '{}'::jsonb THEN RAISE EXCEPTION '고친 내용이 없어요'; END IF;
  SELECT id, work_order_id, suffix, node_id, render_fingerprint INTO v FROM public.tikitaka_videos WHERE id = p_video FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF v.render_fingerprint IS DISTINCT FROM p_based_on THEN
    RAISE EXCEPTION '편집실을 연 뒤에 영상이 새로 만들어졌어요. 편집실을 다시 열어 최신 판에서 고쳐 주세요';
  END IF;
  IF v.node_id IS NULL THEN RAISE EXCEPTION '이 영상을 만든 맥미니를 알 수 없어요'; END IF;
  IF EXISTS (SELECT 1 FROM public.job_queue WHERE kind = 'tikitaka_apply_edit' AND params->>'video_id' = p_video::text
               AND status IN ('pending','running')) THEN
    RAISE EXCEPTION '이 영상을 다시 렌더하는 중이에요. 끝나면 새 판에서 고쳐 주세요';
  END IF;
  SELECT email INTO v_email FROM auth.users WHERE id = auth.uid();
  INSERT INTO public.job_queue (work_order_id, kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
  VALUES (v.work_order_id, 'tikitaka_apply_edit',
          jsonb_build_object('video_id', p_video::text, 'suffix', v.suffix, 'overrides', p_overrides,
                             'based_on', p_based_on, 'by', coalesce(v_email, auth.uid()::text), 'note', left(coalesce(p_note, ''), 500)),
          'tikitaka-edit:' || encode(extensions.digest(p_video::text || '|' || p_based_on || '|' || p_overrides::text, 'sha256'), 'hex'),
          ARRAY['generate', 'node:' || v.node_id], 300, 200)
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING id INTO v_job;
  IF v_job IS NULL THEN RAISE EXCEPTION '같은 수정을 이미 제출했어요'; END IF;
  UPDATE public.tikitaka_edit_drafts SET submitted_job = v_job WHERE video_id = p_video AND user_id = auth.uid();
  PERFORM public._audit('request_tikitaka_edit', 'tikitaka_videos', p_video::text,
          jsonb_build_object('job', v_job, 'node', v.node_id, 'based_on', p_based_on));
  RETURN jsonb_build_object('edit_id', v_job, 'rendering', true, 'node', v.node_id);
END $$;
REVOKE ALL ON FUNCTION public.request_tikitaka_edit(uuid, jsonb, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_tikitaka_edit(uuid, jsonb, text, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0113','claude (맥미니 영상 편집 초안 표 + 제출 RPC)');
