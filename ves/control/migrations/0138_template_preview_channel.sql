-- 0138 적용 모습 미리보기를 채널마다(2026-10-02) — 미리보기에 어느 채널 값으로 만들었는지(token_slug)를 남긴다.
-- 종전에는 같은 작품이면 가장 최근 미리보기를 모든 채널 화면에 보여 줘서, 채널마다 값이 달라도 마지막에 만든 채널 모양만 보였다.
-- NULL = 모든 채널 기본 값으로 만든 미리보기. 함수 본문은 0135 그대로, 저장할 때 token_slug 만 더한다.
ALTER TABLE public.render_template_previews ADD COLUMN IF NOT EXISTS token_slug text;
COMMENT ON COLUMN public.render_template_previews.token_slug IS '이 채널 값으로 만든 미리보기(NULL = 모든 채널 기본)';
CREATE INDEX IF NOT EXISTS render_template_previews_video_slug ON public.render_template_previews(video_id, token_slug, created_at DESC);

-- 이미 만든 미리보기: 값이 그 채널에 저장한 값과 같으면 그 채널 것으로 본다(로고 id 는 빼고 비교)
UPDATE public.render_template_previews p SET token_slug = d.token_slug
  FROM public.tikitaka_videos v, public.channel_work_designs d
 WHERE p.token_slug IS NULL AND v.id = p.video_id AND d.work_title = v.work_title AND d.token_slug <> ''
   AND (p.design - 'work_asset_id') = d.design;

CREATE OR REPLACE FUNCTION public.request_template_preview(p_design jsonb, p_video uuid, p_work text, p_slug text DEFAULT NULL::text)
 RETURNS uuid
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE v record; v_design jsonb := public._render_template_design(p_design); v_id uuid; job uuid; v_logo uuid;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  SELECT id, work_order_id, suffix, node_id, work_title INTO v FROM public.tikitaka_videos WHERE id = p_video;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF v.node_id IS NULL THEN RAISE EXCEPTION '이 영상을 만든 맥미니를 알 수 없어요'; END IF;
  IF p_work IS NOT NULL AND v.work_title IS DISTINCT FROM p_work THEN
    RAISE EXCEPTION '같은 작품 영상으로 봐야 로고 자리가 맞아요. % 영상을 골라 주세요.', p_work;
  END IF;
  -- 채널을 주면 그 채널 × 작품 로고, 안 주면(모든 채널 기본) 작품 기본 로고
  SELECT id INTO v_logo FROM public.work_asset_for(coalesce(p_slug, ''), coalesce(p_work, v.work_title), 'work_logo') LIMIT 1;
  v_id := gen_random_uuid();
  INSERT INTO public.job_queue(work_order_id, kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
  VALUES (v.work_order_id, 'template_preview',
          jsonb_strip_nulls(jsonb_build_object('preview_id', v_id, 'video_id', v.id, 'work_order_id', v.work_order_id, 'suffix', v.suffix,
                                               'design', v_design, 'work_asset_id', v_logo)),
          'template-preview:' || v_id, ARRAY['generate', 'node:' || v.node_id], 300, 180)
  RETURNING id INTO job;
  INSERT INTO public.render_template_previews(id, design, video_id, state, job_id, token_slug)
  VALUES (v_id, v_design || jsonb_strip_nulls(jsonb_build_object('work_asset_id', v_logo)), p_video, 'running', job, nullif(p_slug, ''));
  RETURN v_id;
END $function$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0138','claude (적용 모습 미리보기를 채널마다)');
