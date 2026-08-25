-- 0089 — route 는 그 영상이 정한다 (드라이브 클린 마스터 → A)
--
-- 드라이브발 소재는 파일 자체가 어떻게 다뤄야 하는지를 알고 있다: 이름에 「클린」이
-- 붙은 것은 **화면에 한글 글자가 없는 마스터**라(사용자 확인 2026-08-25) 인페인팅이
-- 필요 없다 → route A(자막 트랙만). 가장 비싸고 위험한 단계를 통째로 건너뛴다.
--
-- 그래서 route 를 **부르는 쪽 기본값**이 아니라 **행이 들고 있는 값**에서 푼다:
--
--     p_route 를 명시하면 그것(사람이 화면에서 고른 값)
--     아니면 external_shorts.flags->>'route' (수집기가 파일 이름을 보고 적어 둔 값)
--     그것도 없으면 'B' (유튜브발 종전 기본)
--
-- ⚠ 자동 선택(loopy_picker)은 p_route 를 **주지 않는다** — 편마다 다른 것을 한 값으로
--   덮으면 클린 마스터에도 인페인팅이 돈다.

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
             ARRAY['network']::text[], 600::int, 1::int, 'short'::text),
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

-- 사람 손 — p_route 를 안 주면(NULL) 행이 아는 값으로 간다.
CREATE OR REPLACE FUNCTION public.select_external_short(
    p_video_id text,
    p_route    text DEFAULT NULL,
    p_note     text DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $function$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    RETURN public._select_external_short_impl(p_video_id, p_route, p_note, 'manual');
END;
$function$;

REVOKE ALL ON FUNCTION public._select_external_short_impl(text, text, text, text) FROM public, anon, authenticated;
REVOKE ALL ON FUNCTION public.select_external_short(text, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.select_external_short(text, text, text) TO authenticated;

-- 드라이브 폴더 설정(사용자 제공 2026-08-25). enabled=true — 목록만 만드는 일이라
-- 파일을 받지 않는다(고른 편만 acquire 가 받는다).
INSERT INTO public.ops_config (key, value) VALUES
  ('loopy_drive_scout',
   '{"enabled": true, "channel_slug": "LOOPY", "folder_id": "1ufTS6JI6PIG-SvyrCjz5U22Tt5OS0QDn", "year": null}')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
