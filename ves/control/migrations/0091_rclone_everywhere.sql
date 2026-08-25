-- 0091 — rclone 인증이 모든 노드에 있으면 드라이브 acquire 를 안 묶는다
--
-- 사용자 지시(2026-08-25): "rclone 인증을 모든 노드에서 가지고 있게 해줘."
--
-- 0090 은 인증이 mm-01·mm-02 에만 있다는 실측 위에서 노드를 고정했다. 인증이 전 노드에
-- 깔리면 그 고정이 오히려 해롭다 — 한 노드가 그날의 병목이 되고, 그 노드가 멈추면
-- 드라이브 소재가 통째로 멈춘다.
--
-- 🛑 **순서가 계약이다: 배포가 먼저, 스위치가 나중.**
--    `ops_config.rclone_everywhere='on'` 을 먼저 켜면 인증 없는 노드가 잡을 집어 죽고,
--    재시도해도 같은 자리다. 그래서 이 마이그레이션은 스위치를 **켜지 않는다** —
--    6대 확인이 끝난 뒤 사람이 켠다.

CREATE OR REPLACE FUNCTION public._select_external_short_impl(
    p_video_id text,
    p_route    text DEFAULT NULL,
    p_note     text DEFAULT NULL,
    p_origin   text DEFAULT 'manual'
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
DECLARE
    v_es    public.external_shorts%ROWTYPE;
    v_ch    record;
    v_work  text;
    v_kind  text;
    v_pipe  text;
    v_route text;
    v_wo    uuid;
    v_prev  uuid := NULL;
    v_common jsonb;
    v_gen   jsonb;
    v_step  record;
    v_jobs  int := 0;
    v_acq_caps text[];
BEGIN
    SELECT * INTO v_es FROM public.external_shorts
     WHERE video_id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '아카이브에 없는 영상: %', p_video_id;
    END IF;

    IF v_es.state NOT IN ('discovered','scored') THEN
        RAISE EXCEPTION '이미 진행 중이거나 끝난 영상입니다 (상태=%)', v_es.state;
    END IF;

    IF v_es.block_reason IS NOT NULL AND v_es.allowed_by IS NULL THEN
        RAISE EXCEPTION '차단된 영상입니다: % — 아카이브에서 [후보로 되돌리기] 후 다시 시도',
                        v_es.block_reason;
    END IF;

    v_kind := coalesce(v_es.kind, 'short');
    IF v_kind NOT IN ('short','longform') THEN
        RAISE EXCEPTION '알 수 없는 kind: %', v_kind;
    END IF;
    v_pipe := CASE WHEN v_kind = 'longform' THEN 'shorts_jp_localized'
                   ELSE 'shorts_jp_overlay' END;

    -- route 정본: 명시값 > 행이 아는 값(수집기가 파일 이름을 보고 적었다) > 'B'
    v_route := coalesce(nullif(btrim(coalesce(p_route,'')), ''),
                        v_es.flags->>'route', 'B');
    IF v_kind = 'short' AND v_route NOT IN ('A','B','BJ','C','BC') THEN
        RAISE EXCEPTION '알 수 없는 route: % (A·B·BJ·C·BC)', v_route;
    END IF;

    IF v_pipe = 'shorts_jp_localized'
       AND coalesce((SELECT value FROM public.ops_config WHERE key='jp_pipeline'), '') <> 'on' THEN
        RAISE EXCEPTION '현지화 파이프라인이 꺼져 있습니다 (ops_config.jp_pipeline)';
    END IF;

    SELECT m.token_slug, m.name, m.works, m.gcp_project INTO v_ch
      FROM public.channels_mirror m WHERE m.token_slug = v_es.channel_slug;
    IF NOT FOUND THEN
        RAISE EXCEPTION '없는 채널: %', v_es.channel_slug;
    END IF;
    v_work := coalesce(v_ch.works[1], v_es.channel_slug);

    INSERT INTO public.work_orders
        (service_date, channel_slug, work_title, episode, source_sha256, source_url,
         pipeline, geoblock_required, has_subtitle, origin, external_video_id)
    VALUES ((now() AT TIME ZONE 'Asia/Seoul')::date, v_es.channel_slug, v_work, NULL,
            NULL, v_es.url, v_pipe, false, false, coalesce(p_origin,'manual'), v_es.video_id)
    RETURNING id INTO v_wo;

    -- 드라이브 파일은 rclone 인증이 있는 노드에서만 받는다. 인증이 **모든 노드**에
    -- 깔렸으면(ops_config.rclone_everywhere='on') 핀을 안 붙인다 — 한 노드에 쏠리면
    -- 그 노드가 그날의 병목이 되고, 그 노드가 죽으면 드라이브 소재가 통째로 멈춘다.
    -- ⚠ 순서가 중요하다: **배포가 먼저, 스위치가 나중.** 스위치를 먼저 켜면 인증 없는
    --    노드가 잡을 집어 죽는다(그리고 재시도해도 같은 자리다).
    v_acq_caps := CASE
        WHEN v_es.flags->>'drive_file_id' IS NULL
          OR coalesce((SELECT value FROM public.ops_config
                        WHERE key='rclone_everywhere'), '') = 'on'
          OR coalesce((SELECT value FROM public.ops_config
                        WHERE key='drive_sync_node'), '') = ''
        THEN ARRAY['network']
        ELSE ARRAY['network', 'node:' || (SELECT value FROM public.ops_config
                                           WHERE key='drive_sync_node')] END;

    v_common := jsonb_build_object('work_title', v_work, 'episode', NULL,
                                   'channel_slug', v_es.channel_slug,
                                   'channel_name', v_ch.name);

    v_gen := v_common || jsonb_build_object(
                 'source_sha256', NULL, 'source_url', v_es.url,
                 'max_shorts', 1, 'no_subtitles', true, 'flags', '{}'::jsonb,
                 'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'),
                 'outdir', 'outputs');

    FOR v_step IN
        SELECT * FROM (VALUES
            ('acquire'::text,
             (v_common || jsonb_build_object('source_url', v_es.url,
                                             'external_video_id', v_es.video_id,
                                             'drive_file_id', v_es.flags->>'drive_file_id',
                                             'download', true))::jsonb,
             v_acq_caps, 600::int, 1::int, 'short'::text),
            ('localize',
             (v_common || jsonb_build_object('mode', 'overlay',
                                             'external_video_id', v_es.video_id,
                                             'source_url', v_es.url,
                                             'level', v_route))::jsonb,
             ARRAY['localize'], 3600, 2, 'short'),
            ('upload_artifacts', v_common, ARRAY['analyze'], 120, 3, 'short'),
            ('acquire',
             (v_common || jsonb_build_object('source_url', v_es.url,
                                             'source_sha256', NULL))::jsonb,
             ARRAY['network'], 120, 11, 'longform'),
            ('generate',         v_gen,     ARRAY['generate'], 300, 12, 'longform'),
            ('upload_artifacts', v_common,  ARRAY['analyze'],  120, 13, 'longform'),
            ('ingest',           v_common,  ARRAY['analyze'],  120, 14, 'longform'),
            ('evaluate',         v_common,  ARRAY['analyze'],  120, 15, 'longform'),
            ('localize',
             (v_common || jsonb_build_object('mode', 'scene_rerender'))::jsonb,
             ARRAY['generate'], 300, 16, 'longform')
        ) AS t(kind, params, caps, ttl, ord, for_kind)
        WHERE t.for_kind = v_kind
        ORDER BY t.ord
    LOOP
        INSERT INTO public.job_queue
            (work_order_id, kind, params, idempotency_key, depends_on,
             required_caps, lease_ttl_sec, priority)
        VALUES (v_wo, v_step.kind, v_step.params,
                'archive:' || v_wo::text || ':' || v_step.kind,
                CASE WHEN v_prev IS NULL THEN '{}'::uuid[] ELSE ARRAY[v_prev] END,
                v_step.caps, v_step.ttl, 150)
        RETURNING id INTO v_prev;
        v_jobs := v_jobs + 1;
    END LOOP;

    UPDATE public.external_shorts
       SET state = 'selected', work_order_id = v_wo, updated_at = now(),
           notes = coalesce(nullif(btrim(coalesce(p_note,'')), ''), notes)
     WHERE video_id = p_video_id;

    PERFORM public._audit('select_external_short','external_shorts', p_video_id,
            jsonb_build_object('work_order_id', v_wo, 'channel', v_es.channel_slug,
                               'kind', v_kind, 'pipeline', v_pipe, 'origin', p_origin,
                               'route', CASE WHEN v_kind = 'short' THEN v_route END,
                               'jobs', v_jobs, 'note', p_note));

    RETURN jsonb_build_object('work_order_id', v_wo, 'video_id', p_video_id,
                              'channel', v_ch.name, 'work', v_work, 'kind', v_kind,
                              'pipeline', v_pipe,
                              'route', CASE WHEN v_kind = 'short' THEN v_route END,
                              'jobs', v_jobs, 'origin', coalesce(p_origin,'manual'));
END;
$function$;
