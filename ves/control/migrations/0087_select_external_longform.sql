-- 0087 — 아카이브 롱폼도 고를 수 있게 (L-P5-2b, 사용자 지시 2026-08-25)
--
-- > "숏폼은 남의 영상 그대로 가져와서 현지화하면 되는데, 롱폼의 경우에는 generate 가
-- >  가능해야돼. 플러스로 현지화까지."
--
-- 0086 은 롱폼을 거절했다("롱폼 갈래는 아직 없습니다"). 그런데 롱폼은 **새 갈래가
-- 필요 없다** — 이미 있는 `shorts_jp_localized`(생성 + 재렌더 현지화)가 그대로 맞는다.
-- 다른 점은 소재가 우리 `sources` 가 아니라 **아카이브의 유튜브 URL** 이라는 것뿐이고,
-- generate 는 URL 소스를 이미 받는다(`--youtube-url`, 어댑터 aivideo.py:343).
--
--     kind=short     → shorts_jp_overlay    : 완성본에 일본어를 입힌다 (generate 없음)
--     kind=longform  → shorts_jp_localized  : 롱폼에서 쇼츠를 만들고(generate) 현지화한다
--
-- ⚠ route(p_route)는 **쇼츠 전용**이다. 롱폼은 우리가 만든 쇼츠라 화면에 한글을 애초에
--   안 그리고, 현지화는 체크포인트 재렌더(scene_rerender)라 인페인팅이 없다.

CREATE OR REPLACE FUNCTION public.select_external_short(
    p_video_id text,
    p_route    text DEFAULT 'B',
    p_note     text DEFAULT NULL
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
    v_wo    uuid;
    v_prev  uuid := NULL;
    v_common jsonb;
    v_gen   jsonb;
    v_step  record;
    v_jobs  int := 0;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;

    -- 잠그고 읽는다 — 두 사람이 같은 편을 동시에 걸면 작업지시가 둘 선다.
    SELECT * INTO v_es FROM public.external_shorts
     WHERE video_id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '아카이브에 없는 영상: %', p_video_id;
    END IF;

    -- 이미 걸렸거나 끝난 편을 다시 걸면 같은 영상이 두 번 올라간다(R10).
    IF v_es.state NOT IN ('discovered','scored') THEN
        RAISE EXCEPTION '이미 진행 중이거나 끝난 영상입니다 (상태=%)', v_es.state;
    END IF;

    -- 게이트에서 걸린 편은 **사람이 뒤집었을 때만** 통과한다(allowed_by).
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

    IF v_kind = 'short' AND (p_route IS NULL OR p_route NOT IN ('A','B','BJ','C','BC')) THEN
        RAISE EXCEPTION '알 수 없는 route: % (A·B·BJ·C·BC)', p_route;
    END IF;

    -- 현지화 체인은 전역 스위치 뒤에 있다(run_channel_now 과 같은 가드).
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
            NULL, v_es.url, v_pipe, false, false, 'manual', v_es.video_id)
    RETURNING id INTO v_wo;

    -- ⚠ 체인은 planner.job_chain 의 같은 pipeline 분기와 **같아야 한다**(kind·caps·params).
    --   갈리면 사람이 건 편만 다른 노드로 가거나 소스를 못 찾는다. 테스트가 두 곳을 묶는다.
    v_common := jsonb_build_object('work_title', v_work, 'episode', NULL,
                                   'channel_slug', v_es.channel_slug,
                                   'channel_name', v_ch.name);

    -- 롱폼: 유튜브 URL 을 그대로 generate 에 넘긴다(어댑터가 --youtube-url 로 받는다).
    v_gen := v_common || jsonb_build_object(
                 'source_sha256', NULL, 'source_url', v_es.url,
                 'max_shorts', 1, 'no_subtitles', true, 'flags', '{}'::jsonb,
                 'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'),
                 'outdir', 'outputs');

    FOR v_step IN
        SELECT * FROM (VALUES
            -- 쇼츠 갈래 (kind=short · shorts_jp_overlay)
            ('acquire'::text,
             (v_common || jsonb_build_object('source_url', v_es.url,
                                             'external_video_id', v_es.video_id,
                                             'download', true))::jsonb,
             ARRAY['network']::text[], 600::int, 1::int, 'short'::text),
            ('localize',
             (v_common || jsonb_build_object('mode', 'overlay',
                                             'external_video_id', v_es.video_id,
                                             'source_url', v_es.url,
                                             'level', p_route))::jsonb,
             ARRAY['localize'], 3600, 2, 'short'),
            ('upload_artifacts', v_common, ARRAY['analyze'], 120, 3, 'short'),
            -- 롱폼 갈래 (kind=longform · shorts_jp_localized) — planner 와 같은 순서
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
                               'kind', v_kind, 'pipeline', v_pipe,
                               'route', CASE WHEN v_kind = 'short' THEN p_route END,
                               'jobs', v_jobs, 'note', p_note));

    RETURN jsonb_build_object('work_order_id', v_wo, 'video_id', p_video_id,
                              'channel', v_ch.name, 'work', v_work, 'kind', v_kind,
                              'pipeline', v_pipe,
                              'route', CASE WHEN v_kind = 'short' THEN p_route END,
                              'jobs', v_jobs);
END;
$function$;

REVOKE ALL ON FUNCTION public.select_external_short(text, text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.select_external_short(text, text, text) TO authenticated;
