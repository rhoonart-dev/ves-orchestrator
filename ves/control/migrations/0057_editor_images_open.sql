-- =====================================================================
-- 0057_editor_images_open.sql — images 개방(F-408 완성) + 이전 라운드 이미지 노출
-- 적용 순서: **엔진(ai-video dc1060f) 전 노드 배포 확인 → DB 적용 → editor_images 플래그 on**.
-- 이 마이그레이션 자체는 언제 적용해도 안전하다 — 대시보드가 editor_images 플래그로
-- images 전송을 게이트하므로, 플래그를 켜는 순간이 실제 개방이다(0054 v3 전환과 같은 구도).
--
-- ① submit_editor_render (0055 전문 기반, 델타 4):
--    · images 조기 거절 제거 → 검증으로 대체: 배열 · 항목 객체 · file 거절(어댑터
--      산출물 — PR #28 리뷰 M2 의 서버측 방어) · key prefix(editor_uploads/, 0056)
--      · 확장자 png/jpg(엔진 dc1060f 실측 — webp 는 렌더 불가) · 시각/좌표 범위.
--    · 편집 항목 목록에 images 추가(이미지만 고친 제출도 유효).
--    · **빈 배열 = 전부 삭제**(tts 규약과 동일): 병합 후 빈 images 키를 걷어내
--      엔진에도 다음 라운드 승계에도 남지 않는다. 키 생략 = 승계(이전 이미지 유지).
--    · audit 에 images 건수.
-- ② request_editor_assets (0051 전문 기반, 델타 1): 반환에 prev_images —
--    이 run 의 최신 generate params.edit_overrides.images (key 그대로. 어댑터의
--    file 치환은 노드 메모리에서만 일어나 DB 에는 key 가 남는다). 화면이 이전 라운드
--    이미지를 보여줘야 '지우기'가 가능하다(키 생략=승계라, 안 보이면 영영 못 지운다).
-- =====================================================================

CREATE OR REPLACE FUNCTION public.submit_editor_render(p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_prev jsonb; v_subs jsonb; v_v3 boolean;
    v_ov jsonb; v_step text; v_params jsonb; v_common jsonb; v_acq_params jsonb;
    v_img jsonb;
    v_acq uuid; v_gen_job uuid; v_up uuid; v_in uuid; v_ev uuid;
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
    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload, rq.status INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind = 'publish_gate'
       AND rq.status IN ('waiting','rejected')
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '편집 재렌더 대상이 아닙니다 — 발행 검수 카드만 가능합니다';
    END IF;
    IF v_rq.status = 'rejected' THEN
        PERFORM 1 FROM public.review_queue w
         WHERE w.work_order_id = v_rq.work_order_id
           AND w.kind = 'publish_gate' AND w.status = 'waiting';
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

    -- ── 라운드 승계(0053) — 머리말 참고 ─────────────────────────────────
    v_prev := coalesce(v_gen.params->'edit_overrides', '{}'::jsonb) - 'schema';
    IF p_overrides ? 'clips' AND NOT p_overrides ? 'subtitles' THEN
        -- 구간이 바뀌면 옛 자막 좌표(편집본 시간축)는 무효 — 단 v3 앵커(source_time_sec)
        -- 있는 줄은 원본 좌표라 살아남는다(0054). 앵커 없는 줄만 버린다.
        IF jsonb_typeof(v_prev->'subtitles') = 'array' THEN
            SELECT coalesce(jsonb_agg(s), '[]'::jsonb) INTO v_subs
              FROM jsonb_array_elements(v_prev->'subtitles') s
             WHERE s ? 'source_time_sec';
            IF jsonb_array_length(v_subs) > 0 THEN
                v_prev := jsonb_set(v_prev, '{subtitles}', v_subs);
            ELSE
                v_prev := v_prev - 'subtitles';
            END IF;
        ELSE
            v_prev := v_prev - 'subtitles';
        END IF;
    END IF;
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

    UPDATE public.editor_assets
       SET status='pending', draft_sent_at=now(), review_id=p_review_id, updated_at=now()
     WHERE run_id = v_gen.run_id;

    PERFORM public._audit('editor_render','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_gen_job,
                               'node', v_gen.node_id, 'from_step', v_step,
                               'note', p_note, 'resubmit', v_rq.status = 'rejected',
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
                              'chain', jsonb_build_array(v_acq, v_gen_job, v_up, v_in, v_ev));
END $function$;

CREATE OR REPLACE FUNCTION public.request_editor_assets(p_review_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_ex record; v_job uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq WHERE rq.id = p_review_id;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 검수 항목입니다'; END IF;
    IF v_rq.work_order_id IS NULL THEN
        RAISE EXCEPTION '작업지시 없는 카드는 편집실 대상이 아닙니다(잔망루피 등)';
    END IF;

    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir,
           coalesce(j.params->'edit_overrides'->'images', '[]'::jsonb) AS prev_images
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY j.created_at DESC LIMIT 1;   -- 0055 정본: finished_at 은 재실행에 뒤집힌다.
                                           -- submit(0057 위쪽)과 **같은 행**을 골라야
                                           -- 화면의 prev_images 와 제출의 승계 기준이
                                           -- 같은 라운드를 가리킨다(리뷰 H1).
    IF v_gen.run_id IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/node) 없음 — 편집실을 열 수 없습니다';
    END IF;

    -- 캐시 재사용 조건(0045 + 0048 + 0049 + 0051): ready · 만료 전 · 편집용 영상까지
    -- 갖춤(또는 신 세대가 상한 초과로 **시도했음** — scan_skip) · 신 세대 내레이션 오디오.
    SELECT status, expires_at,
           (sprites->'assets'->'media'->>'scan') AS scan_key,
           coalesce((sprites->'assets'->'media'->>'scan_bytes')::bigint, 0) AS scan_bytes,
           coalesce((sprites->'assets'->'media'->>'scan_gen')::int, 1) AS scan_gen,
           (sprites->'assets'->'media'->>'scan_skip') AS scan_skip,
           coalesce((sprites->'assets'->>'tts_gen')::int, 0) AS tts_gen
      INTO v_ex FROM public.editor_assets WHERE run_id = v_gen.run_id;
    IF FOUND AND v_ex.status = 'ready' AND v_ex.expires_at > now() + interval '1 day'
       AND ( (v_ex.scan_key IS NOT NULL AND v_ex.scan_bytes <= 400 * 1024 * 1024
              AND v_ex.scan_gen >= 2)
          OR v_ex.scan_skip IS NOT NULL )
       AND v_ex.tts_gen >= 1 THEN
        RETURN jsonb_build_object('run_id', v_gen.run_id, 'status', 'ready', 'cached', true,
                                  'prev_images', v_gen.prev_images);
    END IF;

    INSERT INTO public.editor_assets (run_id, work_order_id, review_id, status, updated_at)
    VALUES (v_gen.run_id, v_rq.work_order_id, p_review_id, 'pending', now())
    ON CONFLICT (run_id) DO UPDATE SET status='pending', review_id=excluded.review_id,
        error=NULL, updated_at=now();

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('editor_assets', v_rq.work_order_id,
            jsonb_build_object('run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                               'review_id', p_review_id,
                               'channel_slug', v_rq.channel_slug),
            'editor_assets:' || v_gen.run_id,
            ARRAY[]::uuid[], ARRAY['generate', 'node:' || v_gen.node_id], 1800, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
    RETURNING id INTO v_job;

    PERFORM public._audit('editor_open','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_job, 'node', v_gen.node_id));
    RETURN jsonb_build_object('run_id', v_gen.run_id, 'status', 'pending',
                              'job_id', v_job, 'node', v_gen.node_id,
                              'prev_images', v_gen.prev_images);
END $$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;
REVOKE ALL     ON FUNCTION public.request_editor_assets(uuid) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.request_editor_assets(uuid) TO authenticated;

-- ③ 0056 업로드 정책 개정 — 엔진 실측(dc1060f)상 webp 는 렌더 불가(png/jpg/jpeg 만).
--    업로드 단계부터 막아 '올라가는데 보낼 수 없는' 파일을 없앤다. 이미 올라간 webp 는
--    참조가 없으면 무해(제출 검증도 거절한다).
DROP POLICY IF EXISTS ves_reviewer_upload_editor_images ON storage.objects;
CREATE POLICY ves_reviewer_upload_editor_images ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'ves-outputs'
    AND public.has_role(auth.uid(), 'reviewer')
    AND name LIKE 'editor_uploads/%'
    AND lower(name) ~ '\.(png|jpg|jpeg)$'
  );

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0057','claude (0057_editor_images_open.sql images 개방 + prev_images)')
ON CONFLICT DO NOTHING;
