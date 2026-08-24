-- =====================================================================
-- 0081 — 편집실 재료 캐시에 '마지막 렌더보다 새것인가' 검사 추가 (2026-08-24)
--
-- 실사고(원희는_스무살_b890368c, 2026-08-24): 재렌더 잡이 dead 인 동안(12:56~14:26)
-- 사람이 편집실을 열어(13:56) 재료가 **렌더 직전의 edit_plan.json** 으로 재생성·캐시
-- 됐다. 14:27 재시도 성공으로 edit_plan.json 은 편집 반영본(구간 12)으로 다시 써졌지만,
-- request_editor_assets 의 캐시 판정은 ready·만료 전·scan 존재·tts_gen 만 보므로
-- 13:56 캐시를 '유효'로 재사용 — 완성본은 편집 반영본인데 편집실은 AI 원안(구간 2)을
-- 보여줬다. 응급으로 expires_at 을 당겨 풀었고, 이 마이그레이션이 재발을 막는다.
--
-- 검사 기준: **재료 생성 잡(editor_assets:<run_id>)의 started_at > generate 의
-- finished_at** 일 때만 캐시를 쓴다.
--   · editor_assets.updated_at 을 쓰지 않는 이유 — 초안 저장(save_editor_draft, 0044)
--     이 그 컬럼을 갱신한다. 렌더 뒤에 초안만 저장해도 낡은 타임라인이 '새것'으로
--     오판된다.
--   · 잡의 finished_at 이 아니라 started_at 인 이유 — 생성은 1~2분 걸린다. 렌더 완료
--     직전에 시작한 생성이 렌더 완료 뒤에 끝나면 finished_at 비교는 통과하지만 읽은
--     파일은 옛것이다. '렌더가 끝난 뒤에 **읽기 시작**했는가'가 정확한 질문이다.
--   · v_built 가 NULL(잡 없음·미완)이거나 비교가 NULL 이면 캐시 탈락 → 재생성.
--     낡은 것을 내주는 쪽보다 1~2분 다시 만드는 쪽이 싸다(조용한 거짓 금지).
--
-- 변경점은 v_gen 에 finished_at 추가·v_built 조회·캐시 IF 의 한 줄뿐, 나머지는
-- 라이브 정의(0071) 전문 그대로다(부분 수정 불가 — CREATE OR REPLACE 는 전문 교체).
-- 짝: ves/adapters/editor_assets.py(재료 생성) · dashboard 편집실(edLoad)
-- =====================================================================

CREATE OR REPLACE FUNCTION public.request_editor_assets(p_review_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_ex record; v_job uuid;
    v_built timestamptz;   -- 0081: 재료 생성 잡의 마지막 성공 시작 시각
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
           j.finished_at AS gen_finished_at,   -- 0081: 캐시 신선도 비교 기준
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
                                           -- 0081 비교에는 그 '뒤집힘'이 오히려 정답이다
                                           -- — 마지막 실제 렌더 완료가 기준이므로.
    IF v_gen.run_id IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/node) 없음 — 편집실을 열 수 없습니다';
    END IF;

    -- 0081: 재료를 실제로 만든 잡의 시작 시각. editor_assets.updated_at 은 초안
    -- 저장(0044)도 갱신하므로 기준이 못 된다(머리말).
    SELECT bj.started_at INTO v_built
      FROM public.job_queue bj
     WHERE bj.idempotency_key = 'editor_assets:' || v_gen.run_id
       AND bj.status = 'succeeded';

    -- 캐시 재사용 조건(0045 + 0048 + 0049 + 0051 + 0081): ready · 만료 전 · 편집용
    -- 영상까지 갖춤(또는 신 세대가 상한 초과로 **시도했음** — scan_skip) · 신 세대
    -- 내레이션 오디오 · **마지막 렌더 완료 뒤에 만든 재료**(0081).
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
       AND v_ex.tts_gen >= 1
       AND v_built IS NOT NULL AND v_built > v_gen.gen_finished_at THEN
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

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0081','claude (0081 편집실 캐시 신선도 — 재렌더 뒤 낡은 타임라인 재사용 차단)')
ON CONFLICT DO NOTHING;
