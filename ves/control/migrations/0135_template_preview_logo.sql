-- 0135 실제 모양 보기에 채널 × 작품 로고(2026-10-02) — 고른 영상의 원래 로고 대신, 그 채널에서 그 작품에 고른 작품 로고(작품 관리 에셋)로 그린다.
-- 로고 크기가 다르면 엔진의 안전 구역 맞추기가 영상 칸 · 로고 크기를 다시 정하므로, 미리보기 영상은 같은 작품 영상만 받는다.
DROP FUNCTION IF EXISTS public.request_template_preview(jsonb, uuid, uuid);
CREATE OR REPLACE FUNCTION public.request_template_preview(p_design jsonb, p_video uuid, p_work text, p_slug text DEFAULT NULL)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
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
  INSERT INTO public.render_template_previews(id, design, video_id, state, job_id)
  VALUES (v_id, v_design || jsonb_strip_nulls(jsonb_build_object('work_asset_id', v_logo)), p_video, 'running', job);
  RETURN v_id;
END $$;
REVOKE ALL ON FUNCTION public.request_template_preview(jsonb, uuid, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_template_preview(jsonb, uuid, text, text) TO authenticated;

-- 권리사 로고도 작품 관리에 올린 로고(platform_logo 에셋)를 고를 수 있게 — platform_asset_id. 엔진이 렌더 직전에 받아 온다
CREATE OR REPLACE FUNCTION public._render_template_design(p jsonb) RETURNS jsonb LANGUAGE plpgsql STABLE AS $$
DECLARE k text; v text;
  c_fonts constant text[] := ARRAY['JalnanGothic','Jalnan','NotoSansCJKkr-Black','mulmaru','Griun'];
  c_colors constant text[] := ARRAY['title_color','title_color2','subtitle_color','tts_color','work_caption_color','platform_color'];
  c_logos constant text[] := ARRAY['tving_logo','coupangplay_icon','coupangplay_logo'];
  out jsonb := '{}'::jsonb;
BEGIN
  p := coalesce(p, '{}'::jsonb);
  IF jsonb_typeof(p) <> 'object' THEN RAISE EXCEPTION '템플릿 값이 이상해요'; END IF;
  FOR k, v IN SELECT key, value #>> '{}' FROM jsonb_each(p) LOOP
    v := nullif(btrim(coalesce(v, '')), '');
    CONTINUE WHEN v IS NULL;
    IF k IN ('title_font','subtitle_font','tts_font') THEN
      IF NOT v = ANY (c_fonts) THEN RAISE EXCEPTION '없는 폰트예요: %', v; END IF;
    ELSIF k = ANY (c_colors) THEN
      IF v !~ '^#[0-9A-Fa-f]{6}$' THEN RAISE EXCEPTION '색은 #RRGGBB 형식이어야 해요: %', v; END IF;
      v := upper(v);
    ELSIF k = 'platform_image' THEN
      IF NOT v = ANY (c_logos) THEN RAISE EXCEPTION '없는 권리사 로고예요: %', v; END IF;
    ELSIF k = 'platform_asset_id' THEN
      IF v !~ '^[0-9a-fA-F-]{36}$' OR NOT EXISTS (SELECT 1 FROM public.work_asset_versions WHERE id = v::uuid AND role = 'platform_logo') THEN
        RAISE EXCEPTION '작품 관리에 없는 권리사 로고예요';
      END IF;
    ELSIF k IN ('work_caption','platform_text') THEN
      IF length(v) > 60 THEN RAISE EXCEPTION '문구는 60자까지 쓸 수 있어요'; END IF;
    ELSE
      RAISE EXCEPTION '템플릿에서 다루지 않는 값이에요: %', k;
    END IF;
    out := out || jsonb_build_object(k, v);
  END LOOP;
  IF out ? 'platform_asset_id' THEN out := out - 'platform_image'; END IF;   -- 올린 로고가 이긴다
  RETURN out;
END $$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0135','claude (실제 모양 보기 로고)');
