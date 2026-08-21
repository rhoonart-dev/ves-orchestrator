-- =====================================================================
-- 0066_editor_jp_full_chain.sql — 혜미리예채파(SHOTCONE) 카드에 KR 편집실 전체 개방
-- (사용자 8/20: "ai-video 에서 편집을 하고 다시 현지화 프로젝트에서 번역해서
--  재렌더링시키는 방식으로") — 편집 재렌더 체인 꼬리에 localize(scene_rerender)를
-- 달아, 고친 한국어 본으로 재번역·재렌더된 새 localization_qa 카드가 올라온다.
--
-- 델타(0059 전문 기반, 4곳):
--   ① 카드 수용: publish_gate 에 더해 localization_qa(작업지시 있는 카드 = SHOTCONE).
--     잔망루피(LOOPY)는 작업지시가 없어 종전 메시지로 거절 — ai-video 런 자체가 없다.
--   ② 재제출 가드(F-302)의 '새 카드' 판정을 카드 kind 기준으로.
--   ③ JP 작업지시(pipeline=shorts_jp_localized)면 evaluate 뒤에
--     localize(mode=scene_rerender, 같은 노드 핀, 'editrender:<rid>:loc') 추가 —
--     planner 정상 체인과 같은 꼬리라 localize 어댑터가 새 카드를 등록한다(_enqueue_qa).
--     편집 초안 청소(F-302)는 brain 이 JP 를 조기 반환하므로 localize 어댑터가 맡는다.
--   ④ audit·반환에 jp 여부.
-- request_editor_assets 는 변경 없음 — 이미 kind 무관(작업지시 + generate 만 요구).
-- 적용 순서: DB 먼저 무해(구 대시보드는 publish_gate 카드만 보낸다). 대시보드는
-- 머지 즉시 배포라 어댑터(localize 초안 청소) 배포 전 창에서도 카드 등록은 정상 —
-- 청소만 늦는다(다음 어댑터 배포에 소급 무해).
-- =====================================================================

CREATE OR REPLACE FUNCTION public.submit_editor_render(p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_prev jsonb; v_v3 boolean;
    v_ov jsonb; v_step text; v_params jsonb; v_common jsonb; v_acq_params jsonb;
    v_img jsonb;
    v_acq uuid; v_gen_job uuid; v_up uuid; v_in uuid; v_ev uuid; v_loc uuid;
    v_jp boolean := false;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    IF p_overrides IS NULL OR p_overrides = '{}'::jsonb THEN
        RAISE EXCEPTION '고친 내용이 없습니다';
    END IF;
    IF NOT (p_overrides ? 'title' OR p_overrides ? 'subtitles' OR p_overrides ? 'clips'
            OR p_overrides ? 'design' OR p_overrides ? 'tts' OR p_overrides ? 'images') THEN
        RAISE EXCEPTION '편집 항목(title/subtitles/clips/design/tts/images) 이 하나도 없습니다';
    END IF;
    IF p_overrides ? 'tts' AND jsonb_typeof(p_overrides->'tts') <> 'array' THEN
        RAISE EXCEPTION 'tts 는 배열이어야 합니다 (빈 배열 = 내레이션 전부 삭제)';
    END IF;
    -- 이미지 오버레이(F-408, 0057 개방) — 엔진 dc1060f 가 렌더한다. 빈 배열 =
    -- 전부 삭제(tts 규약과 동일 — 키를 생략하면 라운드 승계가 이전 이미지를 되살린다).
    -- file 은 어댑터 산출물이라 여기서도 거절(경로 검증 우회 방지 — PR #28 리뷰 M2).
    IF p_overrides ? 'images' THEN
        IF jsonb_typeof(p_overrides->'images') <> 'array' THEN
            RAISE EXCEPTION 'images 는 배열이어야 합니다 (빈 배열 = 이미지 전부 삭제)';
        END IF;
        IF jsonb_array_length(p_overrides->'images') > 20 THEN
            RAISE EXCEPTION 'images 는 최대 20개입니다 (%개)',
                jsonb_array_length(p_overrides->'images');
        END IF;
        FOR v_img IN SELECT * FROM jsonb_array_elements(p_overrides->'images') LOOP
            IF jsonb_typeof(v_img) <> 'object' THEN
                RAISE EXCEPTION 'images[] 항목은 객체여야 합니다';
            END IF;
            IF v_img ? 'file' THEN
                RAISE EXCEPTION 'images[].file 은 어댑터가 만드는 값입니다 — 화면은 key 만 보냅니다';
            END IF;
            IF coalesce(v_img->>'key','') NOT LIKE 'editor_uploads/%'
               OR (v_img->>'key') LIKE '%..%' THEN
                RAISE EXCEPTION 'images[].key 는 editor_uploads/ 경로여야 합니다(0056): %',
                    v_img->>'key';
            END IF;
            IF lower(v_img->>'key') !~ '\.(png|jpe?g)$' THEN
                RAISE EXCEPTION 'images[].key: 엔진은 png/jpg 만 렌더합니다(webp 불가): %',
                    v_img->>'key';
            END IF;
            -- 타입을 먼저 못박는다 — 숫자-문자열("0.5")이 캐스트로 슬쩍 통과하거나,
            -- 쓰레기 값이 raw 22P02 로 죽는 대신 여기서 사람이 읽을 메시지로 죽는다
            IF jsonb_typeof(v_img->'source_time_sec') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'duration_sec') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'x') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'y') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'w') IS DISTINCT FROM 'number' THEN
                RAISE EXCEPTION 'images[]: source_time_sec·duration_sec·x·y·w 는 숫자여야 합니다';
            END IF;
            IF v_img ? 'layer' AND jsonb_typeof(v_img->'layer') <> 'number' THEN
                RAISE EXCEPTION 'images[].layer 는 정수여야 합니다';
            END IF;
            -- 회전(F-410, 엔진 69e5c06) — 시계방향 양수, -180~180. 렌더에서 죽기 전에
            -- 제출에서 사람이 읽을 메시지로 거른다. 타입 IF 를 분리하는 건 위의
            -- '타입을 먼저 못박는다' 패턴과 동일(단락 평가 의존 금지).
            IF v_img ? 'rotate' AND jsonb_typeof(v_img->'rotate') <> 'number' THEN
                RAISE EXCEPTION 'images[].rotate 는 -180~180 도(숫자)여야 합니다';
            END IF;
            IF v_img ? 'rotate' AND ((v_img->>'rotate')::numeric < -180
               OR (v_img->>'rotate')::numeric > 180) THEN
                RAISE EXCEPTION 'images[].rotate 는 -180~180 도(숫자)여야 합니다';
            END IF;
            IF (v_img->>'source_time_sec')::numeric < 0
               OR (v_img->>'duration_sec')::numeric <= 0 THEN
                RAISE EXCEPTION 'images[]: source_time_sec(>=0)·duration_sec(>0) 이 필요합니다';
            END IF;
            IF (v_img->>'x')::numeric < 0 OR (v_img->>'x')::numeric > 1
               OR (v_img->>'y')::numeric < 0 OR (v_img->>'y')::numeric > 1
               OR (v_img->>'w')::numeric <= 0 OR (v_img->>'w')::numeric > 1 THEN
                RAISE EXCEPTION 'images[]: x·y 는 0~1, w 는 0<w<=1 (캔버스 비율) 이어야 합니다';
            END IF;
        END LOOP;
    END IF;

    -- waiting = 통상 경로 · rejected = 재제출 경로(F-302, 아래 가드)
    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload, rq.status, rq.kind
      INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind IN ('publish_gate','localization_qa')
       AND rq.status IN ('waiting','rejected')
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '편집 재렌더 대상이 아닙니다 — 발행 검수·현지화 검수 카드만 가능합니다';
    END IF;
    IF v_rq.work_order_id IS NULL THEN
        RAISE EXCEPTION '작업지시 없는 카드는 편집실 대상이 아닙니다(잔망루피 등)';
    END IF;
    -- JP 편집 재렌더(0066) = 재번역 포함: ai-video 재렌더 뒤 localize 를 잇는다
    SELECT (w.pipeline = 'shorts_jp_localized') INTO v_jp
      FROM public.work_orders w WHERE w.id = v_rq.work_order_id;
    v_jp := coalesce(v_jp, false);
    IF v_rq.status = 'rejected' THEN
        PERFORM 1 FROM public.review_queue w
         WHERE w.work_order_id = v_rq.work_order_id
           AND w.kind = v_rq.kind AND w.status = 'waiting';
        IF FOUND THEN
            RAISE EXCEPTION '이미 새 검수 카드가 있습니다 — 그 카드에서 고치세요';
        END IF;
        PERFORM 1 FROM public.editor_assets ea
         WHERE ea.review_id = p_review_id AND ea.draft_sent_at IS NOT NULL;
        IF NOT FOUND THEN
            RAISE EXCEPTION '재제출 대상이 아닙니다 — 이 카드로 보낸 초안이 없습니다';
        END IF;
    END IF;

    SELECT id INTO v_busy FROM public.job_queue
     WHERE work_order_id = v_rq.work_order_id
       AND status IN ('pending','running','blocked')
       AND (kind = 'generate' OR idempotency_key LIKE 'editrender:%')
     LIMIT 1;
    IF v_busy IS NOT NULL THEN
        RAISE EXCEPTION '이미 렌더 체인이 대기·진행 중입니다(job %) — 끝난 뒤 다시 시도하세요', v_busy;
    END IF;

    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir,
           j.params AS params
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY j.created_at DESC LIMIT 1;   -- 0055 수정 ③: finished_at 은 재실행에 뒤집힌다
                                           -- (0054 판 그대로 + 이 줄만 교체)
    IF v_gen.run_id IS NULL OR v_gen.run_dir IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/run_dir/node) 없음 — 편집 재렌더 불가';
    END IF;

    -- ── 라운드 승계(0053 → 0059 개정) ────────────────────────────────────
    -- 0054 는 구간만 고친 재제출에서 앵커 없는 승계 자막을 버렸다('옛 시간축의 낡은
    -- 좌표' 전제). V3-b 부터 앵커 없는 줄은 전부 **사람이 의도한 고정 시각**이다 —
    -- 신규 줄, 그리고 타이밍을 손대 시각 고정(pin)한 줄. 엔진이 재매핑한 줄은 항상
    -- 앵커를 달고 돌아오므로, 남는 앵커 없는 줄 = 사람 값. 낡아서가 아니라 사람이
    -- 정한 값이라 버리면 안 된다(전량 교체 규약에서 탈락 = 그 줄 텍스트 소실).
    -- 어긋날 가능성은 화면 경고(anchorless)가 알린다 — 서버는 보존한다.
    v_prev := coalesce(v_gen.params->'edit_overrides', '{}'::jsonb) - 'schema';
    v_ov := v_prev || p_overrides;
    -- 빈 images 는 '전부 삭제' 의사표시 — 병합에서 이전 이미지를 지운 뒤 키를 걷어낸다
    -- (엔진에 빈 배열을 보내지 않고, 다음 라운드 승계에도 이미지가 남지 않는다).
    IF v_ov ? 'images' AND jsonb_array_length(v_ov->'images') = 0 THEN
        v_ov := v_ov - 'images';
        -- 지울 이전 이미지도, 다른 편집도 없으면 = 아무 변화 없는 렌더 체인 — 거절
        IF v_ov = '{}'::jsonb
           AND jsonb_array_length(coalesce(v_prev->'images', '[]'::jsonb)) = 0 THEN
            RAISE EXCEPTION '고친 내용이 없습니다 — 지울 이미지도 없습니다';
        END IF;
    END IF;
    -- 스키마 스탬프(0054) — 병합 결과 기준 내용 기반 3단.
    v_v3 := (v_ov ? 'images')
         OR (jsonb_typeof(v_ov->'subtitles') = 'array' AND EXISTS (
                SELECT 1 FROM jsonb_array_elements(v_ov->'subtitles') s
                 WHERE s ? 'source_time_sec' OR s ? 'style'));
    v_ov := v_ov || jsonb_build_object('schema',
                CASE WHEN v_v3 THEN 'edit_overrides/v3'
                     WHEN v_ov ? 'tts' THEN 'edit_overrides/v2'
                     ELSE 'edit_overrides/v1' END);

    v_step := CASE WHEN v_ov ? 'clips' OR v_ov ? 'tts'
                   THEN 'resources' ELSE 'render' END;

    UPDATE public.review_queue
       SET status = 'rejected',
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(),
           decision_note = '[편집실 재렌더] ' || coalesce(p_note, '')
     WHERE id = p_review_id AND status = 'waiting';

    v_params := coalesce(v_gen.params, '{}'::jsonb) || jsonb_build_object(
                    'resume_run_id', v_gen.run_id, 'from_step', v_step,
                    'edit_overrides', v_ov,
                    'run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                    'review_id', p_review_id);
    v_common := jsonb_build_object(
                    'work_title',   v_gen.params->>'work_title',
                    'episode',      v_gen.params->'episode',
                    'channel_slug', coalesce(v_gen.params->>'channel_slug', v_rq.channel_slug),
                    'channel_name', v_gen.params->>'channel_name',
                    'outdir',       coalesce(v_gen.params->>'outdir', 'outputs'),
                    'run_id',       v_gen.run_id, 'run_dir', v_gen.run_dir);

    v_acq_params := v_common || jsonb_build_object(
                        'source_url',    v_gen.params->>'source_url',
                        'source_sha256', v_gen.params->>'source_sha256');

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('acquire', v_rq.work_order_id, v_acq_params,
            'editrender:' || p_review_id || ':acq',
            ARRAY[]::uuid[], ARRAY['network', 'node:' || v_gen.node_id], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            required_caps=excluded.required_caps,
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_acq;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('generate', v_rq.work_order_id, v_params,
            'editrender:' || p_review_id,
            ARRAY[v_acq], ARRAY['generate', 'node:' || v_gen.node_id], 300, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_gen_job;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('upload_artifacts', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':up',
            ARRAY[v_gen_job], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_up;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('ingest', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':in',
            ARRAY[v_up], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_in;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('evaluate', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':ev',
            ARRAY[v_in], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_ev;

    IF v_jp THEN
        -- planner 정상 체인의 꼬리 그대로(mode=scene_rerender, 같은 노드) — 고친 본으로
        -- 재번역해 다시 그린다. run_id/run_dir 는 resume 라 그대로고(v_common 동봉),
        -- 완료 시 localize 어댑터가 새 localization_qa 카드를 올린다(waiting 중복 방지).
        INSERT INTO public.job_queue
            (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
             lease_ttl_sec, priority)
        VALUES ('localize', v_rq.work_order_id,
                v_common || jsonb_build_object('mode', 'scene_rerender',
                                               'review_id', p_review_id),
                'editrender:' || p_review_id || ':loc',
                ARRAY[v_ev], ARRAY['generate', 'node:' || v_gen.node_id], 3600, 150)
        ON CONFLICT (idempotency_key) DO UPDATE
            SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
                node_id=NULL, lease_expires_at=NULL, run_after=now(),
                depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
        RETURNING id INTO v_loc;
    END IF;

    UPDATE public.editor_assets
       SET status='pending', draft_sent_at=now(), review_id=p_review_id, updated_at=now()
     WHERE run_id = v_gen.run_id;

    PERFORM public._audit('editor_render','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_gen_job,
                               'node', v_gen.node_id, 'from_step', v_step,
                               'note', p_note, 'resubmit', v_rq.status = 'rejected', 'jp', v_jp,
                               'schema', v_ov->>'schema',
                               'keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_overrides) k),
                               'carried', (SELECT jsonb_agg(k) FROM jsonb_object_keys(v_prev) k
                                           WHERE NOT p_overrides ? k),
                               'subs', jsonb_array_length(coalesce(v_ov->'subtitles','[]'::jsonb)),
                               'clips', jsonb_array_length(coalesce(v_ov->'clips','[]'::jsonb)),
                               'tts', jsonb_array_length(coalesce(v_ov->'tts','[]'::jsonb)),
                               'images', jsonb_array_length(coalesce(v_ov->'images','[]'::jsonb))));
    RETURN jsonb_build_object('review_id', p_review_id, 'work_order_id', v_rq.work_order_id,
                              'run_id', v_gen.run_id, 'job_id', v_gen_job,
                              'node', v_gen.node_id, 'from_step', v_step,
                              'jp', v_jp,
                              'chain', CASE WHEN v_jp
                                  THEN jsonb_build_array(v_acq, v_gen_job, v_up, v_in, v_ev, v_loc)
                                  ELSE jsonb_build_array(v_acq, v_gen_job, v_up, v_in, v_ev) END);
END $function$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;


INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0066','claude (0066_editor_jp_full_chain.sql SHOTCONE KR 편집실 전체 개방)')
ON CONFLICT DO NOTHING;
