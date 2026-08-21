-- =====================================================================
-- 0071_editor_texts.sql — 편집실 '텍스트' 레이어(F-411, ai-video texts[]) 오케스트레이터 파트
-- 계약: p_overrides.texts = [{text, source_time_sec, duration_sec, x, y, size?, color?,
-- stroke?, fx?, rotate?, font?}] — 대사가 아닌 글자(의성어·강조·보조설명)의 자유 오브젝트.
-- 좌표는 images 와 같은 원본 앵커(source_time_sec + duration_sec), x·y 는 글자 중심 비율.
-- 검증 정본은 엔진(edit_overrides.py TEXT_KEYS, 즉시 실패) — 여기서는 형태 오류를 렌더에
-- 태우기 전에 사람이 읽을 메시지로 거른다. 대시보드 개방은 ops_config 'editor_texts' 플래그.
--
-- ① submit_editor_render (0067 전문 기반, 델타 4):
--    · 편집 항목 목록에 texts 추가
--    · texts[] 기본 검증(배열·최대 20·text·숫자 타입·범위·열거값)
--    · 빈 배열 = '텍스트 전부 삭제'(images 규약과 동일) — images·texts 둘을 걷어낸 **뒤**
--      한 번만 '고친 내용 없음' 판정(키가 둘이라 블록을 복붙하면 첫 strip 이 둘째를 가린다)
--    · v3 스탬프 조건에 texts 추가 — 엔진이 v1·v2 스탬프의 texts 를 즉시 거절한다
--    · 감사 로그에 texts 건수
-- ② request_editor_assets (0067 전문 기반, 델타 1): 반환에 prev_texts — 라운드 승계가
--    키를 통째 교체하므로 이전 텍스트가 화면에 보여야 삭제·보존이 된다(prev_images·
--    prev_title_segments 와 같은 이유 — 캐시·신규 두 반환 경로 모두).
-- ③ ops_config 'editor_texts' = off 시드 — 엔진 전 노드 배포 확인 후 운영자가 on.
-- 적용 순서: DB 먼저 무해(구 대시보드는 texts 를 안 보낸다). 어댑터는 수정 없음(통과).
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
            OR p_overrides ? 'design' OR p_overrides ? 'tts' OR p_overrides ? 'images'
            OR p_overrides ? 'texts') THEN
        RAISE EXCEPTION '편집 항목(title/subtitles/clips/design/tts/images/texts) 이 하나도 없습니다';
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

    -- 자유 텍스트(F-411) — 엔진 TEXT_KEYS 와 같은 형태 검증. 빈 배열 = 전부 삭제(images 규약).
    IF p_overrides ? 'texts' THEN
        IF jsonb_typeof(p_overrides->'texts') <> 'array' THEN
            RAISE EXCEPTION 'texts 는 배열이어야 합니다 (빈 배열 = 텍스트 전부 삭제)';
        END IF;
        IF jsonb_array_length(p_overrides->'texts') > 20 THEN
            RAISE EXCEPTION 'texts 는 최대 20개입니다 (%개)',
                jsonb_array_length(p_overrides->'texts');
        END IF;
        FOR v_img IN SELECT * FROM jsonb_array_elements(p_overrides->'texts') LOOP
            IF jsonb_typeof(v_img) <> 'object'
               OR coalesce(btrim(v_img->>'text'), '') = '' THEN
                RAISE EXCEPTION 'texts[] 항목은 text 가 있는 객체여야 합니다';
            END IF;
            IF length(v_img->>'text') > 60 THEN
                RAISE EXCEPTION 'texts[].text 는 60자 이하여야 합니다 (%자)', length(v_img->>'text');
            END IF;
            -- 타입을 먼저 못박는다(images 와 같은 이유 — 숫자-문자열·쓰레기 값 차단)
            IF jsonb_typeof(v_img->'source_time_sec') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'duration_sec') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'x') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'y') IS DISTINCT FROM 'number' THEN
                RAISE EXCEPTION 'texts[]: source_time_sec·duration_sec·x·y 는 숫자여야 합니다';
            END IF;
            IF v_img ? 'size' AND jsonb_typeof(v_img->'size') <> 'number' THEN
                RAISE EXCEPTION 'texts[].size 는 12~400 px(숫자)여야 합니다';
            END IF;
            IF v_img ? 'size' AND ((v_img->>'size')::numeric < 12 OR (v_img->>'size')::numeric > 400) THEN
                RAISE EXCEPTION 'texts[].size 는 12~400 px(숫자)여야 합니다';
            END IF;
            IF v_img ? 'rotate' AND jsonb_typeof(v_img->'rotate') <> 'number' THEN
                RAISE EXCEPTION 'texts[].rotate 는 -180~180 도(숫자)여야 합니다';
            END IF;
            IF v_img ? 'rotate' AND ((v_img->>'rotate')::numeric < -180
               OR (v_img->>'rotate')::numeric > 180) THEN
                RAISE EXCEPTION 'texts[].rotate 는 -180~180 도(숫자)여야 합니다';
            END IF;
            IF v_img ? 'color' AND (v_img->>'color') !~ '^#[0-9A-Fa-f]{6}$' THEN
                RAISE EXCEPTION 'texts[].color 는 #RRGGBB 여야 합니다: %', v_img->>'color';
            END IF;
            IF v_img ? 'stroke' AND (v_img->>'stroke') NOT IN ('dark','none','white') THEN
                RAISE EXCEPTION 'texts[].stroke 는 dark/none/white 중 하나입니다: %', v_img->>'stroke';
            END IF;
            IF v_img ? 'fx' AND (v_img->>'fx') NOT IN ('none','pop','shake') THEN
                RAISE EXCEPTION 'texts[].fx 는 none/pop/shake 중 하나입니다: %', v_img->>'fx';
            END IF;
            IF v_img ? 'font' AND (v_img->>'font') NOT IN ('Jalnan','JalnanGothic','mulmaru','Griun') THEN
                RAISE EXCEPTION 'texts[].font 는 번들 폰트(Jalnan/JalnanGothic/mulmaru/Griun)만 됩니다: %', v_img->>'font';
            END IF;
            IF (v_img->>'source_time_sec')::numeric < 0
               OR (v_img->>'duration_sec')::numeric <= 0 THEN
                RAISE EXCEPTION 'texts[]: source_time_sec(>=0)·duration_sec(>0) 이 필요합니다';
            END IF;
            IF (v_img->>'x')::numeric < 0 OR (v_img->>'x')::numeric > 1
               OR (v_img->>'y')::numeric < 0 OR (v_img->>'y')::numeric > 1 THEN
                RAISE EXCEPTION 'texts[]: x·y 는 0~1 (글자 중심, 캔버스 비율) 이어야 합니다';
            END IF;
        END LOOP;
    END IF;

    -- 타임드 제목(E8, ai-video bd58078) — title.segments 기본 검증. 겹침·창 순서의
    -- 정본 검증은 엔진(즉시 실패)이지만, 형태 오류는 렌더를 태우기 전에 여기서 거른다.
    IF jsonb_typeof(p_overrides->'title') = 'object'
       AND p_overrides->'title' ? 'segments' THEN
        IF jsonb_typeof(p_overrides->'title'->'segments') <> 'array' THEN
            RAISE EXCEPTION 'title.segments 는 배열이어야 합니다';
        END IF;
        IF jsonb_array_length(p_overrides->'title'->'segments') > 20 THEN
            RAISE EXCEPTION 'title.segments 는 최대 20개입니다 (%개)',
                jsonb_array_length(p_overrides->'title'->'segments');
        END IF;
        FOR v_img IN SELECT * FROM jsonb_array_elements(p_overrides->'title'->'segments') LOOP
            IF jsonb_typeof(v_img) <> 'object'
               OR coalesce(btrim(v_img->>'text'), '') = '' THEN
                RAISE EXCEPTION 'title.segments[] 항목은 text 가 있는 객체여야 합니다';
            END IF;
            IF jsonb_typeof(v_img->'start_sec') IS DISTINCT FROM 'number'
               OR jsonb_typeof(v_img->'end_sec') IS DISTINCT FROM 'number'
               OR (v_img->>'start_sec')::numeric < 0
               OR (v_img->>'end_sec')::numeric <= (v_img->>'start_sec')::numeric THEN
                RAISE EXCEPTION 'title.segments[]: start_sec(>=0)·end_sec(>start) 숫자가 필요합니다';
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
    -- (0071) texts 도 같은 규약. 두 키를 모두 걷어낸 **뒤** 한 번만 '변화 없음' 을 판정한다
    -- — 블록을 키마다 복붙하면 첫 strip 시점엔 v_ov 에 다른 빈 배열이 남아 가드가 안 선다.
    IF v_ov ? 'images' AND jsonb_array_length(v_ov->'images') = 0 THEN
        v_ov := v_ov - 'images';
    END IF;
    IF v_ov ? 'texts' AND jsonb_array_length(v_ov->'texts') = 0 THEN
        v_ov := v_ov - 'texts';
    END IF;
    -- 지울 이전 이미지·텍스트도, 다른 편집도 없으면 = 아무 변화 없는 렌더 체인 — 거절
    IF v_ov = '{}'::jsonb
       AND jsonb_array_length(coalesce(v_prev->'images', '[]'::jsonb)) = 0
       AND jsonb_array_length(coalesce(v_prev->'texts', '[]'::jsonb)) = 0 THEN
        RAISE EXCEPTION '고친 내용이 없습니다 — 지울 이미지·텍스트도 없습니다';
    END IF;
    -- 스키마 스탬프(0054) — 병합 결과 기준 내용 기반 3단.
    v_v3 := (v_ov ? 'images') OR (v_ov ? 'texts')
         OR (jsonb_typeof(v_ov->'title') = 'object' AND v_ov->'title' ? 'segments')
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
                               'images', jsonb_array_length(coalesce(v_ov->'images','[]'::jsonb)),
                               'texts', jsonb_array_length(coalesce(v_ov->'texts','[]'::jsonb))));
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
           coalesce(j.params->'edit_overrides'->'images', '[]'::jsonb) AS prev_images,
           coalesce(j.params->'edit_overrides'->'title'->'segments', '[]'::jsonb)
               AS prev_title_segments,
           coalesce(j.params->'edit_overrides'->'texts', '[]'::jsonb) AS prev_texts
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
                                  'prev_images', v_gen.prev_images,
                                  'prev_title_segments', v_gen.prev_title_segments,
                                  'prev_texts', v_gen.prev_texts);
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
                              'prev_images', v_gen.prev_images,
                              'prev_title_segments', v_gen.prev_title_segments,
                                  'prev_texts', v_gen.prev_texts);
END $$;

REVOKE ALL     ON FUNCTION public.request_editor_assets(uuid) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.request_editor_assets(uuid) TO authenticated;

-- 편집실 게이트 — 엔진(ai-video texts[]) 전 노드 배포 확인 후 운영자가 'on' 으로 바꾼다.
INSERT INTO public.ops_config(key, value, note)
VALUES ('editor_texts', 'off',
        '편집실 텍스트 레이어(F-411 texts[] — 의성어·강조·보조설명 자유 텍스트) — 엔진 2026-08-21 전 노드 배포 후 on')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0071','claude (0071_editor_texts.sql 편집실 텍스트 레이어 F-411 — texts[] 검증·v3 스탬프·prev_texts·editor_texts 게이트)')
ON CONFLICT DO NOTHING;
