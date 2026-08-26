-- 0098 — 편집실이 잔망루피 쇼츠(overlay)를 실제로 고칠 수 있게 (2026-08-26, P6)
--
-- 실측: 우리 파이프라인이 만든 overlay 카드를 편집실에서 고쳐 보내면 **실패한다**.
-- 0038 은 갈래가 둘뿐이다:
--
--     payload.zanmang_video_id 있음 → vlp zanmang_decision(rerender)   ← 8/26 은퇴한 길
--     그 외                        → generate 결과(run_id/run_dir/node) 필수
--                                     RAISE '재렌더 불가'
--
-- overlay 체인엔 generate 가 없다(acquire → localize). 그래서 우리 카드가 두 번째
-- 갈래로 떨어져 죽는다. 원본이 완성본 mp4 하나이므로 **localize 를 다시 돌리면**
-- 되고, 편집실이 고친 것은 overrides 로 실어 보낸다 — 엔진이 그 파일을 읽는 계약이
-- 이미 있다(overlay/pipeline `_apply_subtitle_overrides`·`_load_cuts`).
--
-- ⚠ 순서가 계약이다: zanmang(구 카드) → overlay(신규) → generate 기반(rerender).
--    mode='scene_rerender' 인 카드는 external_video_id 가 있어도 아래 갈래로 간다
--    (잔망루피 **롱폼**이 그렇다 — 우리 타임라인이 있어 그쪽이 맞다).

CREATE OR REPLACE FUNCTION public.reject_and_rerender(
    p_review_id uuid, p_edits jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_vid text; v_repo text; v_node text; v_job uuid;
    v_gen record; v_ext text; v_mode text; v_route text;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    IF p_edits IS NULL OR p_edits = '{}'::jsonb THEN
        RAISE EXCEPTION '수정 내용(p_edits)이 비어 있습니다 — 고칠 게 없으면 일반 반려를 쓰세요';
    END IF;

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind = 'localization_qa' AND rq.status = 'waiting'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '검수 대기 중인 현지화(localization_qa) 카드가 아닙니다';
    END IF;

    UPDATE public.review_queue
       SET status = 'rejected',
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(),
           decision_note = '[수정 재렌더 요청] ' || coalesce(p_note, '')
     WHERE id = p_review_id;

    v_vid := v_rq.payload->>'zanmang_video_id';

    -- ── 잔망루피 ──────────────────────────────────────────────────────
    IF v_vid IS NOT NULL THEN
        v_repo := coalesce(v_rq.payload->>'repo',
                           (SELECT value FROM public.ops_config WHERE key='zanmang_repo'),
                           '/opt/ves/engines/video-localization-project');
        v_node := coalesce((SELECT value FROM public.ops_config WHERE key='zanmang_node'), 'mm-06');

        INSERT INTO public.job_queue
            (kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
        VALUES ('zanmang_decision',
                jsonb_build_object('video_id', v_vid, 'action', 'rerender', 'repo', v_repo,
                                   'channel_slug', v_rq.channel_slug,
                                   'channel_name', 'まいにちじゃんまんるぴー',
                                   'review_id', p_review_id, 'note', p_note,
                                   'overrides', p_edits),
                'zanmang_rerender:' || v_vid || ':' || p_review_id,
                ARRAY[]::uuid[], ARRAY['localize', 'node:' || v_node], 1800, 150)
        ON CONFLICT (idempotency_key) DO UPDATE
            SET status='pending', attempt=0, error=NULL, error_class=NULL,
                node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
        RETURNING id INTO v_job;

        PERFORM public._audit('reject', 'review_queue', p_review_id::text,
                jsonb_build_object('mode','rerender','channel','LOOPY','video_id',v_vid,
                                   'job',v_job,'note',p_note,'edits',p_edits));
        RETURN jsonb_build_object('review_id', p_review_id, 'video_id', v_vid,
                                  'job_id', v_job, 'node', v_node, 'mode', 'loopy_rerender');
    END IF;

    -- ── overlay(잔망루피 쇼츠 — 우리 파이프라인) ─────────────────────
    -- 🛑 여기가 없어서 이 카드는 아래 갈래로 떨어졌고, 거기서 generate 결과를
    --    요구하다 '재렌더 불가'로 죽었다. overlay 체인엔 generate 가 없다
    --    (acquire → localize). 원본은 완성본 mp4 하나이므로 **localize 를 다시**
    --    돌리면 된다 — 편집실이 고친 것은 overrides 로 실어 보낸다(엔진이
    --    outputs/<id>/overrides.json 을 읽는다: subs 문구 치환 · cuts 구간 빼기).
    v_ext  := v_rq.payload->>'external_video_id';
    v_mode := v_rq.payload->>'mode';
    IF v_ext IS NOT NULL AND coalesce(v_mode, 'overlay') <> 'scene_rerender' THEN
        v_route := coalesce(v_rq.payload->>'route', 'B');
        INSERT INTO public.job_queue
            (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
             lease_ttl_sec, priority)
        VALUES ('localize', v_rq.work_order_id,
                jsonb_build_object('mode', 'overlay',
                                   'external_video_id', v_ext,
                                   'source_url', v_rq.payload->>'url',
                                   'channel_slug', v_rq.channel_slug,
                                   'level', v_route,
                                   'review_id', p_review_id, 'note', p_note,
                                   'overrides', p_edits),
                'overlay_rerender:' || v_ext || ':' || p_review_id,
                ARRAY[]::uuid[], ARRAY['localize'], 3600, 150)
        ON CONFLICT (idempotency_key) DO UPDATE
            SET params=EXCLUDED.params,
                status='pending', attempt=0, error=NULL, error_class=NULL,
                node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
        RETURNING id INTO v_job;

        PERFORM public._audit('reject', 'review_queue', p_review_id::text,
                jsonb_build_object('mode','overlay_rerender','channel',v_rq.channel_slug,
                                   'external_video_id',v_ext,'route',v_route,
                                   'job',v_job,'note',p_note,'edits',p_edits));
        RETURN jsonb_build_object('review_id', p_review_id, 'external_video_id', v_ext,
                                  'job_id', v_job, 'mode', 'overlay_rerender');
    END IF;

    -- ── SHOTCONE(scene_rerender) ─────────────────────────────────────
    IF v_rq.work_order_id IS NULL THEN
        RAISE EXCEPTION '작업지시 없는 카드 — 재렌더 경로가 없습니다';
    END IF;
    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC
     LIMIT 1;
    IF v_gen.run_id IS NULL OR v_gen.run_dir IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/run_dir/node) 없음 — 재렌더 불가';
    END IF;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('localize', v_rq.work_order_id,
            jsonb_build_object('mode', 'scene_rerender',
                               'run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                               'channel_slug', v_rq.channel_slug,
                               'review_id', p_review_id, 'note', p_note,
                               'overrides', p_edits),
            'rerender:' || p_review_id,
            ARRAY[]::uuid[], ARRAY['generate', 'node:' || v_gen.node_id], 300, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
    RETURNING id INTO v_job;

    PERFORM public._audit('reject', 'review_queue', p_review_id::text,
            jsonb_build_object('mode','rerender','wo',v_rq.work_order_id,'job',v_job,
                               'node',v_gen.node_id,'note',p_note,'edits',p_edits));
    RETURN jsonb_build_object('review_id', p_review_id, 'work_order_id', v_rq.work_order_id,
                              'job_id', v_job, 'node', v_gen.node_id, 'mode', 'scene_rerender');
END $$;

-- CREATE OR REPLACE 는 기존 ACL 을 보존하지만, 0038 과 같은 문면으로 다시 적는다 —
-- 이 파일 하나만 새 DB 에 적용해도 권한이 같도록.
REVOKE ALL     ON FUNCTION public.reject_and_rerender(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.reject_and_rerender(uuid, jsonb, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0098','claude (0098 overlay 카드 재렌더 갈래)')
ON CONFLICT DO NOTHING;
