-- 0026: 잔망루피도 검수함에서 승인 → 업로드 (2026-08-12 사용자 요청)
--
-- 종전: video-localization-project 의 autopilot 이 스스로 돌고, 승인은 **그 레포 CLI 로만**
--       가능했다(`python -m src.autopilot approve <id>`). 사람이 mm-06 에 붙어야 했고,
--       관제에는 "오늘 실행 완료" 밖에 안 보였다.
-- 이제: daily 가 끝나면 승인 대기분이 다른 채널과 똑같이 검수함에 올라오고(zanmang.post_success),
--       여기 RPC 로 승인/반려하면 zanmang_decision 잡이 원장에 확정한다.
--
-- 다른 채널과 다른 점 두 가지 — 그래서 approve_and_publish 를 건드리지 않고 따로 뒀다:
--   ① **작업지시(work_order)가 없다.** 이 채널은 전용 파이프라인이라 잡 DAG 를 안 탄다.
--      approve_and_publish 는 work_order·clip_id·지오블락 스탬프를 전제하므로 맞지 않는다.
--   ② **공개 방식이 이미 정해져 있다.** 업로더가 비공개 업로드 + 19:00 JST 다음 빈 슬롯 예약이다
--      (R9 준수). 그래서 관제에서 privacy/예약시각을 고를 게 없다 — 승인이면 그 규칙대로 간다.

CREATE OR REPLACE FUNCTION public.decide_loopy(
    p_review_id uuid, p_approve boolean, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_vid text; v_repo text; v_node text; v_job uuid; v_action text;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
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
                               'review_id', p_review_id, 'note', p_note),
            'zanmang_decide:' || v_vid || ':' || v_action,
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
REVOKE ALL     ON FUNCTION public.decide_loopy(uuid, boolean, text) FROM public;
GRANT  EXECUTE ON FUNCTION public.decide_loopy(uuid, boolean, text) TO authenticated;

-- ── 채널별 현지화 등급 (사용자 결정 8/12) ────────────────────────────────
-- video-localization config levels: A=자막 트랙만(인페인트·더빙 없음) ·
-- B=번인 텍스트 제거 후 일본어 재합성(더빙 없음) · C=B+더빙 · BC=번인제거+더빙.
-- 종전엔 planner 가 전 JP 채널을 B 로 고정했다. 채널마다 다르므로 설정으로 뺀다.
--   ショトコン(혜미리예채파) = 오디오 현지화 불필요 + 한국어 텍스트도 지울 필요 없음 → BJ
--     (BJ = 번인 유지 + 일본어를 겹치지 않는 위치에 병기. 인페인트가 없어 LaMa 가중치 불필요·빠르다.
--      실측 8/12: B 는 mm-06 에 인페인터가 없어 3분 만에 실패했고, 이후 2시간 타임아웃을 반복했다.)
-- ⚠ 잔망루피는 이 설정이 안 걸린다 — planner 가 아니라 autopilot 이 돌고, 등급은 그 레포의
--   select.estimate_level(제목 키워드)이 정한다. '전부 더빙'은 그쪽 설정을 바꿔야 한다.
INSERT INTO public.ops_config(key, value, note)
VALUES ('localize_levels', '{"SHOTCONE":"BJ"}',
        '채널별 현지화 등급 A|B|BJ|C|BC. 없거나 이상하면 B(종전 동작). '
        'planner 가 localize 잡 params.level 로 싣는다. 잔망루피는 대상 아님(autopilot 소관).')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0026','claude-cloud (0026 잔망루피 검수함 승인·업로드 + 채널별 현지화 등급)')
ON CONFLICT DO NOTHING;
