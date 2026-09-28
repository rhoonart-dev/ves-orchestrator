-- 0111 — 새 방식(tikitaka) 영상을 맥미니에서 만든다 (2026-09-28)
-- 한 번 돌리면(회차 1개) 영상이 여러 편 나온다. 종전 흐름(upload_artifacts·ingest·evaluate·검수함)은
-- '1 작업지시 = 1 편'을 전제하므로 쓰지 않고, 편마다 한 줄인 tikitaka_videos 에 남긴다.
-- 체인: acquire → tikitaka_generate(python -m app.tikitaka … --count N) → tikitaka_upload(편별 번들 → ves-outputs).
-- 작업은 사람이 건다(order_tikitaka_run). 매일 자동 계획(planner)에는 아직 붙이지 않는다 — 같은 회차 반복 생산을 막기 위해.
-- 자동 평가(ingest·evaluate)와 검수 카드는 나중에 편 단위로 고쳐서 붙인다.

-- ── 편 단위 결과 ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.tikitaka_videos (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_order_id uuid NOT NULL REFERENCES public.work_orders(id) ON DELETE CASCADE,
 job_id uuid,                                   -- 올린 tikitaka_upload 잡
 node_id text,                                  -- 잡 폴더가 남아 있는 노드(재렌더·썸네일은 여기서)
 suffix text NOT NULL CHECK (suffix ~ '^v[0-9]{1,2}(_[A-Za-z0-9_-]+)?$'),
 version integer,
 tag text,
 channel_slug text,
 work_title text,
 episode text,
 title text,
 status text NOT NULL DEFAULT 'review' CHECK (status IN ('review','approved','rejected','discarded')),
 render_fingerprint text,
 duration_sec numeric,
 review_items integer,
 bundle jsonb NOT NULL DEFAULT '{}'::jsonb,     -- 엔진 video.json(tikitaka_video/v1) 그대로
 publish jsonb,                                 -- publish.json(제목·해시태그·카피)
 files jsonb NOT NULL DEFAULT '{}'::jsonb,      -- {상대경로: {key, bytes, sha256}} — ves-outputs
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (work_order_id, suffix)
);
CREATE INDEX IF NOT EXISTS tikitaka_videos_created ON public.tikitaka_videos (created_at DESC);

ALTER TABLE public.tikitaka_videos ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.tikitaka_videos FROM anon, authenticated;
GRANT SELECT ON public.tikitaka_videos TO authenticated;
GRANT ALL ON public.tikitaka_videos TO service_role;
DROP POLICY IF EXISTS tikitaka_videos_read ON public.tikitaka_videos;
CREATE POLICY tikitaka_videos_read ON public.tikitaka_videos FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));

-- ── 작업 걸기 ──────────────────────────────────────────────────────
-- p_args: 엔진 선택 인자(어댑터가 허용 목록으로 다시 거른다) — design_preset·style_preset·script_flow·voice·speed·
--         copy·copy_pos·logo_width·range·pov·cover_cut_guard·stt. 모르는 키는 여기서 거절한다(오타가 조용히 무시되지 않게).
-- p_node: 이 맥미니에서만 돌린다(시험용). 비우면 아무 노드나 — acquire 가 generate 를, generate 가 upload 를 제 노드로 묶는다.
CREATE OR REPLACE FUNCTION public.order_tikitaka_run(
  p_slug text, p_work text, p_episode integer, p_count integer DEFAULT 3,
  p_args jsonb DEFAULT '{}'::jsonb, p_node text DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  v_ch record; v_src record; v_wo uuid; v_prev uuid := NULL; v_common jsonb; v_gen jsonb;
  v_step record; v_jobs int := 0; v_pin text[] := '{}'; v_bad text;
  c_keys constant text[] := ARRAY['design_preset','style_preset','script_flow','voice','speed','copy',
                                  'copy_pos','logo_width','range','pov','cover_cut_guard','stt'];
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF p_count IS NULL OR p_count < 1 OR p_count > 14 THEN RAISE EXCEPTION '편수는 1~14 사이여야 해요 (받은 값: %)', p_count; END IF;
  IF p_args IS NULL THEN p_args := '{}'::jsonb; END IF;
  IF jsonb_typeof(p_args) <> 'object' THEN RAISE EXCEPTION '엔진 설정은 JSON 객체여야 해요'; END IF;
  SELECT k INTO v_bad FROM jsonb_object_keys(p_args) k WHERE NOT (k = ANY (c_keys)) LIMIT 1;
  IF v_bad IS NOT NULL THEN RAISE EXCEPTION '모르는 엔진 설정: % (쓸 수 있는 것: %)', v_bad, array_to_string(c_keys, ', '); END IF;

  SELECT m.token_slug, m.name, m.gcp_project, coalesce(o.works, m.works) AS works
    INTO v_ch
    FROM public.channels_mirror m
    LEFT JOIN public.channel_works_overrides o ON o.token_slug = m.token_slug
   WHERE m.token_slug = p_slug;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF NOT (p_work = ANY (v_ch.works)) THEN
    RAISE EXCEPTION '이 채널의 작품이 아니에요: % (채널 작품: %)', p_work, array_to_string(v_ch.works, ', ');
  END IF;

  SELECT s.* INTO v_src FROM public.sources s
   WHERE s.work_title = p_work AND s.episode = p_episode AND s.is_active
   ORDER BY s.created_at DESC LIMIT 1;
  IF NOT FOUND THEN RAISE EXCEPTION '% %회차 원본이 없어요 — 소스 창고에 먼저 등록해 주세요', p_work, p_episode; END IF;

  IF p_node IS NOT NULL THEN
    IF NOT EXISTS (SELECT 1 FROM public.node_registry WHERE node_id = p_node) THEN
      RAISE EXCEPTION '없는 맥미니예요: %', p_node;
    END IF;
    v_pin := ARRAY['node:' || p_node];
  END IF;

  INSERT INTO public.work_orders
    (service_date, channel_slug, work_title, episode, source_sha256, source_url, pipeline,
     knob_config, geoblock_required, has_subtitle, origin)
  VALUES ((now() AT TIME ZONE 'Asia/Seoul')::date, p_slug, p_work, p_episode, v_src.sha256, v_src.source_url,
          'tikitaka_grid', jsonb_build_object('count', p_count, 'args', p_args, 'note', p_note),
          false, coalesce(v_src.has_subtitle, false), 'manual')
  RETURNING id INTO v_wo;

  v_common := jsonb_build_object('work_title', p_work, 'episode', p_episode,
                                 'channel_slug', p_slug, 'channel_name', v_ch.name);
  v_gen := v_common || jsonb_build_object(
             'source_sha256', v_src.sha256, 'source_url', v_src.source_url,
             'count', p_count, 'args', p_args,
             'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'));

  FOR v_step IN
    SELECT * FROM (VALUES
      ('acquire'::text, (v_common || jsonb_build_object('source_url', v_src.source_url,
                                                        'source_sha256', v_src.sha256))::jsonb,
       ARRAY['network']::text[], 120::int, 1::int),
      ('tikitaka_generate', v_gen,    ARRAY['generate'], 300, 2),
      ('tikitaka_upload',   v_common, ARRAY['analyze'],  300, 3)
    ) AS t(kind, params, caps, ttl, ord)
    ORDER BY t.ord
  LOOP
    INSERT INTO public.job_queue
      (work_order_id, kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
    VALUES (v_wo, v_step.kind, v_step.params, 'tikitaka:' || v_wo::text || ':' || v_step.kind,
            CASE WHEN v_prev IS NULL THEN '{}'::uuid[] ELSE ARRAY[v_prev] END,
            v_step.caps || v_pin, v_step.ttl, 150)
    RETURNING id INTO v_prev;
    v_jobs := v_jobs + 1;
  END LOOP;

  PERFORM public._audit('order_tikitaka_run', 'work_orders', v_wo::text,
          jsonb_build_object('slug', p_slug, 'work', p_work, 'episode', p_episode, 'count', p_count,
                             'args', p_args, 'node', p_node, 'note', p_note, 'source_id', v_src.id));
  RETURN jsonb_build_object('work_order_id', v_wo, 'channel', v_ch.name, 'work', p_work,
                            'episode', p_episode, 'count', p_count, 'node', p_node, 'jobs', v_jobs);
END $$;
REVOKE ALL ON FUNCTION public.order_tikitaka_run(text, text, integer, integer, jsonb, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.order_tikitaka_run(text, text, integer, integer, jsonb, text, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0111','claude (새 방식 tikitaka 맥미니 실행 — 편 단위 결과 표 + 작업 걸기)');
