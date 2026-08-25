-- 0086 — 아카이브에서 고른 쇼츠에 작업지시를 세운다 (L-P5-2)
--
-- 발주서: docs/LOCALIZE_UNIFY.md §6-1·§6-2.
--
-- 잔망루피가 홈에서 안 보이고 편집실이 안 열리던 이유는 하나다: **work_order 가 없다.**
-- 옛 경로(zanmang_autopilot)는 vlp 원장에 직접 쓰고 VES 작업지시를 만들지 않는다.
-- 이 함수가 그 다리다 — 사람이 아카이브에서 한 편을 고르면 다른 채널과 **같은 모양의**
-- 작업지시 + 잡 체인이 선다.
--
-- ⚠ 자동이 아니다(§0 사용자 결정 2 — 자동 선별·승인은 폐기). 선별기는 점수만 매기고,
--   거는 것은 사람이다. 이 함수는 그 사람 손을 받는 자리다.

ALTER TABLE public.work_orders
    ADD COLUMN IF NOT EXISTS external_video_id text;

COMMENT ON COLUMN public.work_orders.external_video_id IS
  '외부 아카이브(external_shorts)에서 고른 원본 영상 id — shorts_jp_overlay 전용. '
  '어댑터가 이 값으로 소스를 찾는다.';

CREATE INDEX IF NOT EXISTS idx_wo_external_video
    ON public.work_orders(external_video_id)
    WHERE external_video_id IS NOT NULL;

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
    v_wo    uuid;
    v_prev  uuid := NULL;
    v_common jsonb;
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

    -- 롱폼은 갈래가 다르다(§5-3 · P7) — 여기서 막지 않으면 쇼츠 체인이 롱폼을 집는다.
    IF coalesce(v_es.kind,'short') <> 'short' THEN
        RAISE EXCEPTION '쇼츠가 아닙니다 (kind=%) — 롱폼 갈래는 아직 없습니다', v_es.kind;
    END IF;

    -- 게이트에서 걸린 편은 **사람이 뒤집었을 때만** 통과한다(allowed_by).
    IF v_es.block_reason IS NOT NULL AND v_es.allowed_by IS NULL THEN
        RAISE EXCEPTION '차단된 영상입니다: % — 아카이브에서 [후보로 되돌리기] 후 다시 시도',
                        v_es.block_reason;
    END IF;

    IF p_route IS NULL OR p_route NOT IN ('A','B','BJ','C','BC') THEN
        RAISE EXCEPTION '알 수 없는 route: % (A·B·BJ·C·BC)', p_route;
    END IF;

    SELECT m.token_slug, m.name, m.works INTO v_ch
      FROM public.channels_mirror m WHERE m.token_slug = v_es.channel_slug;
    IF NOT FOUND THEN
        RAISE EXCEPTION '없는 채널: %', v_es.channel_slug;
    END IF;
    v_work := coalesce(v_ch.works[1], v_es.channel_slug);

    INSERT INTO public.work_orders
        (service_date, channel_slug, work_title, episode, source_sha256, source_url,
         pipeline, geoblock_required, has_subtitle, origin, external_video_id)
    VALUES ((now() AT TIME ZONE 'Asia/Seoul')::date, v_es.channel_slug, v_work, NULL,
            NULL, v_es.url, 'shorts_jp_overlay', false, false, 'manual', v_es.video_id)
    RETURNING id INTO v_wo;

    -- ⚠ 체인은 planner.job_chain 의 shorts_jp_overlay 분기와 **같아야 한다**
    --   (kind·caps·params). 갈리면 사람이 건 편만 다른 노드로 가거나 소스를 못 찾는다.
    --   tests/test_pure.py 가 두 곳을 묶는다.
    v_common := jsonb_build_object('work_title', v_work, 'episode', NULL,
                                   'channel_slug', v_es.channel_slug,
                                   'channel_name', v_ch.name);

    FOR v_step IN
        SELECT * FROM (VALUES
            ('acquire'::text,
             (v_common || jsonb_build_object('source_url', v_es.url,
                                             'external_video_id', v_es.video_id,
                                             'download', true))::jsonb,
             ARRAY['network']::text[], 600::int, 1::int),
            ('localize',
             (v_common || jsonb_build_object('mode', 'overlay',
                                             'external_video_id', v_es.video_id,
                                             'source_url', v_es.url,
                                             'level', p_route))::jsonb,
             ARRAY['localize'], 3600, 2),
            ('upload_artifacts', v_common, ARRAY['analyze'], 120, 3)
        ) AS t(kind, params, caps, ttl, ord)
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
                               'route', p_route, 'jobs', v_jobs, 'note', p_note));

    RETURN jsonb_build_object('work_order_id', v_wo, 'video_id', p_video_id,
                              'channel', v_ch.name, 'work', v_work,
                              'route', p_route, 'jobs', v_jobs);
END;
$function$;

REVOKE ALL ON FUNCTION public.select_external_short(text, text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.select_external_short(text, text, text) TO authenticated;
