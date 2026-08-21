-- =====================================================================
-- 0068_loopy_decide_review_link.sql — 잔망루피 재합격 시 발행 잡 params 갱신 (2026-08-21)
--
-- 경위(8/20 실측, video 349jZIBj-0s): 합격 → 반려-수정 재렌더 → 새 카드 재합격 흐름에서
-- 재합격의 INSERT 가 첫 합격이 만든 잡과 멱등 키('zanmang_decide:<vid>:publish[:privacy]',
-- review_id 미포함)로 충돌한다. 종전 ON CONFLICT 는 상태만 되돌리고 params 는 옛 결정
-- 그대로라, 잡의 review_id 가 이미 반려된 옛 카드를 가리킨 채 남았다. 그 결과:
--   · 관제 unpublished 배너가 현재 합격 카드의 발행 잡을 못 찾아 "발행 잡 없음" 오경보
--     (실제로는 업로드·예약까지 끝나 있었다 — youtu.be/Xgk-sLnGZZU, 8/21 19:00 JST).
--   · 재합격 때 publish_at 을 다르게 골라도 옛 값이 남는다(멱등 키에 publish_at 없음).
--
-- 고침: ON CONFLICT 에서 params 도 EXCLUDED 로 갈아끼운다 — 잡은 언제나 '마지막 결정'을
-- 실행·기록한다. 재실행 안전은 종전대로 어댑터의 원장 멱등이 지킨다(이미 uploaded 면 no-op).
-- 함수 본문은 0035 판 그대로에 이 한 줄만 다르다.
-- 짝: 대시보드 pubJobOf(0068 이전 잡을 위해 video_id 로도 잇는다).
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
        SET params=EXCLUDED.params,          -- 0068: 잡은 마지막 결정을 가리킨다(위 머리말)
            status='pending', attempt=0, error=NULL, error_class=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
    RETURNING id INTO v_job;

    PERFORM public._audit(CASE WHEN coalesce(p_approve,false) THEN 'approve' ELSE 'reject' END,
            'review_queue', p_review_id::text,
            jsonb_build_object('channel','LOOPY','video_id',v_vid,'action',v_action,
                               'job',v_job,'note',p_note));

    RETURN jsonb_build_object('review_id', p_review_id, 'video_id', v_vid,
                              'action', v_action, 'job_id', v_job, 'node', v_node);
END $$;

REVOKE ALL     ON FUNCTION public.decide_loopy(uuid, boolean, text, text, timestamptz) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.decide_loopy(uuid, boolean, text, text, timestamptz) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0068','claude (0068 잔망루피 재합격 시 발행 잡 params 갱신)')
ON CONFLICT DO NOTHING;
