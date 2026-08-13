-- =====================================================================
-- 0035_loopy_privacy_choice.sql — 잔망루피도 공개 방식 3택 (2026-08-14 사용자 결정)
--
-- "잔망루피 채널도 다른 채널들처럼 비공개·일부공개·예약공개로" — 종전 decide_loopy 는
-- 방식이 업로더에 고정(비공개+다음 19:00 JST 예약)이었다. 0026 판 그대로에:
--   ① p_privacy(schedule|private|unlisted)·p_publish_at 인자 추가 — NULL 이면 종전 기본.
--   ② R9 검증: public 없음 · publish_at 은 schedule 전용 · 과거 시각 거부.
--   ③ zanmang_decision 잡 params 로 전달 — 어댑터가 CLI --privacy/--publish-at 로 잇는다.
-- 짝: vlp cmd_upload(--privacy/--publish-at) · ves zanmang.action_argv · 대시보드 loopyCard.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.decide_loopy(
    p_review_id uuid, p_approve boolean, p_note text DEFAULT NULL,
    p_privacy text DEFAULT NULL, p_publish_at timestamptz DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_vid text; v_repo text; v_node text; v_job uuid; v_action text;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    -- 공개 방식(0035, 관제 3택): NULL=종전 기본(다음 19:00 JST 예약). public 은 없다(R9).
    IF p_privacy IS NOT NULL AND p_privacy NOT IN ('schedule','private','unlisted') THEN
        RAISE EXCEPTION 'privacy 는 schedule|private|unlisted (받은 값: %)', p_privacy;
    END IF;
    IF p_publish_at IS NOT NULL AND coalesce(p_privacy,'schedule') <> 'schedule' THEN
        RAISE EXCEPTION 'publish_at 은 예약공개(schedule)에서만 씁니다';
    END IF;
    IF p_publish_at IS NOT NULL AND p_publish_at <= now() THEN
        RAISE EXCEPTION '예약 시각이 과거입니다: %', p_publish_at;
    END IF;

    SELECT rq.id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind = 'localization_qa' AND rq.status = 'waiting'
     FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '잔망루피 검수 항목이 아니거나 이미 결정됨'; END IF;

    v_vid := v_rq.payload->>'zanmang_video_id';
    IF v_vid IS NULL THEN
        RAISE EXCEPTION 'payload.zanmang_video_id 없음 — 이 카드는 decide_loopy 대상이 아닙니다';
    END IF;

    v_action := CASE WHEN coalesce(p_approve,false) THEN 'publish' ELSE 'skip' END;
    v_repo := coalesce(v_rq.payload->>'repo',
                       (SELECT value FROM public.ops_config WHERE key='zanmang_repo'),
                       '/opt/ves/engines/video-localization-project');
    v_node := coalesce((SELECT value FROM public.ops_config WHERE key='zanmang_node'), 'mm-06');

    UPDATE public.review_queue
       SET status = CASE WHEN coalesce(p_approve,false) THEN 'approved' ELSE 'rejected' END,
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(), decision_note = p_note
     WHERE id = p_review_id;

    -- 원장 확정 잡. 반려도 잡을 만든다 — skipped 로 안 찍으면 다음 daily 가 같은 건을 또 올린다.
    INSERT INTO public.job_queue
        (kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
    VALUES ('zanmang_decision',
            jsonb_build_object('video_id', v_vid, 'action', v_action, 'repo', v_repo,
                               'channel_slug', v_rq.channel_slug,
                               'channel_name', 'まいにちじゃんまんるぴー',
                               'review_id', p_review_id, 'note', p_note)
            || CASE WHEN p_privacy IS NOT NULL
                    THEN jsonb_build_object('privacy', p_privacy) ELSE '{}'::jsonb END
            || CASE WHEN p_publish_at IS NOT NULL
                    THEN jsonb_build_object('publish_at',
                             to_char(p_publish_at AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
                    ELSE '{}'::jsonb END,
            'zanmang_decide:' || v_vid || ':' || v_action
                || coalesce(':' || p_privacy, ''),
            ARRAY[]::uuid[], ARRAY['localize', 'node:' || v_node], 1800, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
    RETURNING id INTO v_job;

    PERFORM public._audit(CASE WHEN coalesce(p_approve,false) THEN 'approve' ELSE 'reject' END,
            'review_queue', p_review_id::text,
            jsonb_build_object('channel','LOOPY','video_id',v_vid,'action',v_action,
                               'job',v_job,'note',p_note));

    RETURN jsonb_build_object('review_id', p_review_id, 'video_id', v_vid,
                              'action', v_action, 'job_id', v_job, 'node', v_node);
END $$;

-- 구판(3인자) 제거 — 기본값 겹침으로 호출 모호해지는 것 방지
DROP FUNCTION IF EXISTS public.decide_loopy(uuid, boolean, text);
REVOKE ALL     ON FUNCTION public.decide_loopy(uuid, boolean, text, text, timestamptz) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.decide_loopy(uuid, boolean, text, text, timestamptz) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0035','claude (decide_loopy 공개 방식 3택 — privacy·publish_at 전달)')
ON CONFLICT DO NOTHING;
