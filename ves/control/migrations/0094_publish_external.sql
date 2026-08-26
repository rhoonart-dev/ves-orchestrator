-- 0094 — 외부 완성본(잔망루피) 발행을 VES 로 (2026-08-26, L-P5-발행)
--
-- 지금까지 잔망루피 발행은 **vlp 원장**이 했다: decide_loopy → zanmang_decision 잡 →
-- mm-06 의 video-localization-project CLI(approve→upload). 그 길은 카드 payload 의
-- `zanmang_video_id`(= vlp 원장 열쇠)를 요구한다.
--
-- 우리 overlay 파이프라인이 만든 카드에는 그 열쇠가 없다(아카이브 id 와 산출 키뿐).
-- 그래서 첫 실전 왕복으로 만들어진 두 편이 **어느 승인 RPC 도 받지 않았다**:
--   · decide_loopy        → 'payload.zanmang_video_id 없음'
--   · approve_and_publish → 'clip_id 를 찾을 수 없습니다'(우리가 만든 클립이 아니다)
--
-- 이 마이그레이션은 같은 버튼(decide_loopy)이 **새 카드도** 받게 한다. 판정 기준은
-- payload 에 무엇이 있는가 하나다:
--
--     payload.external_video_id 있음 → publish_external 잡 (VES 발행 · 이 레포 어댑터)
--     payload.zanmang_video_id  있음 → zanmang_decision 잡 (종전 그대로 · 회귀 0)
--
-- 🛑 **발행 결정은 그대로 사람이다.** 바뀌는 것은 '승인 뒤 누가 올리는가'뿐이다.
-- 🛑 반려는 새 경로에서 **잡을 만들지 않는다** — 구 경로가 잡을 만든 이유는 vlp 원장에
--    skipped 를 찍어야 다음 daily 가 같은 건을 또 올리지 않기 때문이다. 새 경로의
--    상태는 이 DB 에 있으므로 여기서 바로 찍는다(state='skipped').
-- ⚠ 안전 게이트는 사람의 검수 승인이다. brain 의 judge 게이트는 우리가 만든 클립용이라
--    외부 완성본에는 적용되지 않는다(있지도 않은 판정을 지어내지 않는다).

CREATE OR REPLACE FUNCTION public.decide_loopy(
    p_review_id uuid, p_approve boolean, p_note text DEFAULT NULL,
    p_privacy text DEFAULT NULL, p_publish_at timestamptz DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_vid text; v_ext text; v_repo text; v_node text; v_job uuid;
    v_action text; v_ch record; v_title text; v_privacy text; v_meta jsonb;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
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
    v_ext := v_rq.payload->>'external_video_id';
    v_action := CASE WHEN coalesce(p_approve,false) THEN 'publish' ELSE 'skip' END;

    -- ── 새 경로: 우리 overlay 가 만든 편 ────────────────────────────────
    IF v_ext IS NOT NULL THEN
        UPDATE public.review_queue
           SET status = CASE WHEN coalesce(p_approve,false) THEN 'approved' ELSE 'rejected' END,
               decided_by = coalesce(auth.email(), auth.uid()::text),
               decided_at = now(), decision_note = p_note
         WHERE id = p_review_id;

        IF NOT coalesce(p_approve,false) THEN
            -- 반려 — 상태만 찍는다(다음 선별이 다시 뽑지 않게). 잡은 없다.
            UPDATE public.external_shorts
               SET state = 'skipped', block_reason = coalesce(p_note, '검수 반려'),
                   updated_at = now()
             WHERE video_id = v_ext;
            PERFORM public._audit('reject','review_queue', p_review_id::text,
                    jsonb_build_object('channel', v_rq.channel_slug,
                                       'external_video_id', v_ext, 'note', p_note));
            RETURN jsonb_build_object('review_id', p_review_id, 'external_video_id', v_ext,
                                      'action', 'skip', 'job_id', NULL);
        END IF;

        v_meta := coalesce(v_rq.payload->'metadata', '{}'::jsonb);
        v_title := coalesce(v_meta->'title_candidates'->>0, '');
        IF btrim(v_title) = '' THEN
            RAISE EXCEPTION '일본어 제목이 없습니다 — 메타 초벌이 비었습니다(현지화를 다시 돌리세요). 빈 채로 올리면 한국어 원제가 일본 채널에 뜹니다';
        END IF;

        SELECT m.name, m.gcp_project INTO v_ch
          FROM public.channels_mirror m WHERE m.token_slug = v_rq.channel_slug;

        -- 공개 방식: schedule(기본) = private + 예약. 시각을 안 주면 어댑터가 다음 빈 슬롯.
        v_privacy := CASE WHEN coalesce(p_privacy,'schedule') = 'unlisted'
                          THEN 'unlisted' ELSE 'private' END;

        INSERT INTO public.job_queue
            (kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
        VALUES ('publish_external',
                jsonb_build_object(
                    'external_video_id', v_ext,
                    'channel_slug', v_rq.channel_slug,
                    'channel_name', v_ch.name,
                    'gcp_project', v_ch.gcp_project,
                    'bucket', coalesce(v_rq.payload->>'bucket', 'ves-localized'),
                    'key', v_rq.payload->>'preview_key',
                    'metadata', v_meta,
                    'route', v_rq.payload->>'route',
                    'audio_ja', (upper(coalesce(v_rq.payload->>'route','')) IN ('C','BC')),
                    'privacy', v_privacy,
                    'schedule', (coalesce(p_privacy,'schedule') = 'schedule'),
                    'review_id', p_review_id, 'note', p_note)
                || CASE WHEN p_publish_at IS NOT NULL
                        THEN jsonb_build_object('publish_at',
                                 to_char(p_publish_at AT TIME ZONE 'UTC',
                                         'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
                        ELSE '{}'::jsonb END,
                'publish_external:' || v_ext,
                ARRAY[]::uuid[], ARRAY['publish'], 1800, 150)
        ON CONFLICT (idempotency_key) DO UPDATE
            SET params=EXCLUDED.params,      -- 재합격은 '마지막 결정'을 실행한다(0068 규약)
                status='pending', attempt=0, error=NULL, error_class=NULL,
                node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
        RETURNING id INTO v_job;

        PERFORM public._audit('approve_publish','review_queue', p_review_id::text,
                jsonb_build_object('channel', v_rq.channel_slug, 'external_video_id', v_ext,
                                   'title', v_title, 'privacy', v_privacy,
                                   'publish_at', p_publish_at, 'job', v_job));
        RETURN jsonb_build_object('review_id', p_review_id, 'external_video_id', v_ext,
                                  'action', 'publish', 'job_id', v_job,
                                  'title', v_title, 'privacy', v_privacy);
    END IF;

    -- ── 종전 경로: vlp 원장(zanmang autopilot) ─────────────────────────
    IF v_vid IS NULL THEN
        RAISE EXCEPTION 'payload 에 external_video_id 도 zanmang_video_id 도 없습니다 — 이 카드는 decide_loopy 대상이 아닙니다';
    END IF;

    v_repo := coalesce(v_rq.payload->>'repo',
                       (SELECT value FROM public.ops_config WHERE key='zanmang_repo'),
                       '/opt/ves/engines/video-localization-project');
    v_node := coalesce((SELECT value FROM public.ops_config WHERE key='zanmang_node'), 'mm-06');

    UPDATE public.review_queue
       SET status = CASE WHEN coalesce(p_approve,false) THEN 'approved' ELSE 'rejected' END,
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(), decision_note = p_note
     WHERE id = p_review_id;

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
        SET params=EXCLUDED.params,
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
VALUES ('orchestrator','0094','claude (0094 외부 완성본 발행을 VES 로)')
ON CONFLICT DO NOTHING;
