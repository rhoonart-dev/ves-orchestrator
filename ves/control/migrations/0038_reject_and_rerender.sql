-- =====================================================================
-- 0038_reject_and_rerender.sql — 검수함 반려-수정 재렌더 (2026-08-14 사용자 요청)
--
-- "일본 채널 2개는 자막·제목·TTS 내용을 고쳐서 재렌더를 뽑아낼 수 있게 — 반려 시
--  선택지에 넣어서 재실행되게" — 일반 반려(기록/재생성)와 달리, 운영자가 카드에서
--  **텍스트를 직접 고치고** 그 본으로 같은 영상을 다시 렌더한다.
--
-- 좌표계: 카드 payload.ko_ja_pairs 의 idx — p_edits 는
--   {youtube_title_ja?, top_title_ja?, description_ja?,
--    subs:{"idx":"ja"}, tts:{"idx":"ja"}, telops:{"idx":{"ja":…}}}
--
-- 경로 2갈래(카드 하나에서 분기):
--   · 잔망루피(payload.zanmang_video_id): zanmang_decision(action=rerender) —
--     원장 정상 전이(pending_approval→skipped→selected→process)로 되돌려 재처리.
--     overrides 는 outputs/<vid>/overrides.json 으로 — dub(C)·process_video(B/BJ)가 병합.
--   · SHOTCONE(scene_rerender 카드): 같은 작업지시에 localize(mode=scene_rerender) 재투입 —
--     generate 결과(run_id/run_dir)와 그 노드 핀을 그대로 물려받아, 엔진이 L1 번역에
--     병합(localize_run --overrides) 후 L3+ 를 고친 본으로 다시 돈다.
-- 두 경로 다 완료 시 어댑터가 새 localization_qa 카드를 올린다(옛 카드는 여기서 rejected).
-- 짝: vlp apply_overrides/apply_dub_overrides · ves zanmang_decision(rerender) ·
--     localize scene_rerender overrides · 대시보드 '✏️ 수정 재렌더' 패널.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.reject_and_rerender(
    p_review_id uuid, p_edits jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_vid text; v_repo text; v_node text; v_job uuid;
    v_gen record;
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

REVOKE ALL     ON FUNCTION public.reject_and_rerender(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.reject_and_rerender(uuid, jsonb, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0038','claude (reject_and_rerender — 검수함 반려-수정 재렌더)')
ON CONFLICT DO NOTHING;
