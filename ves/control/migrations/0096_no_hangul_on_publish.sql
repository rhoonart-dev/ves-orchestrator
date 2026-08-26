-- 0096 — 일본 채널 문구에 한글이 남으면 승인을 막는다 (2026-08-26)
--
-- 첫 실물 2편 실측: 자동 생성된 메타가 원제의 한국어 해시태그를 **제목·설명 양쪽에**
-- 그대로 남겼다(`ルーピーをナメたらあかんで？👊✨ #닛몰캐쉬 …`). 0095 로 편집칸을
-- 붙였지만 그것은 **고칠 수단**이지 보장이 아니다 — 사람이 못 보고 넘기면 그대로 나간다.
--
-- 승인 시점에 막는다(발행 시점이 아니라): 사람이 그 화면에서 바로 고칠 수 있고, 발행에서
-- 막으면 이미 결정이 끝난 뒤다. 어떤 토막이 걸렸는지 메시지에 적어 무엇을 지울지 보인다.
-- 🛑 조용히 지우지 않는다 — 문구를 고치는 것은 사람의 결정이다.
--
-- 세 겹 중 둘째다: ① 프롬프트가 한글을 안 내게 지시 ② 승인 게이트(여기) ③ 발행
-- 어댑터의 마지막 그물(자동 경로·되살아난 옛 잡을 위해).
-- ⚠ 0095 판 본문 그대로에 이 검사만 더했다. 5-인자 위임은 0095 것이 살아 있다.

CREATE OR REPLACE FUNCTION public.decide_loopy(
    p_review_id uuid, p_approve boolean, p_note text DEFAULT NULL,
    p_privacy text DEFAULT NULL, p_publish_at timestamptz DEFAULT NULL,
    p_title text DEFAULT NULL, p_description text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_vid text; v_ext text; v_repo text; v_node text; v_job uuid;
    v_action text; v_ch record; v_title text; v_privacy text; v_meta jsonb;
    v_desc text;
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
        -- 사람이 고친 제목이 이긴다. 안 고쳤으면 초벌 1안(화면이 보여주는 그 값).
        v_title := coalesce(nullif(btrim(coalesce(p_title,'')), ''),
                            v_meta->'title_candidates'->>0, '');
        IF length(v_title) > 100 THEN
            RAISE EXCEPTION '제목이 100자를 넘습니다(%자) — 유튜브 상한입니다', length(v_title);
        END IF;
        v_desc := coalesce(nullif(btrim(coalesce(p_description,'')), ''),
                           v_meta->>'description', '');
        -- 🛑 일본 채널 문구에 한글이 남으면 승인 자체를 막는다. 실측(2026-08-26 첫
        -- 실물 2편): 번역이 원제의 한국어 해시태그(`#닛몰캐쉬`)를 제목·설명 양쪽에
        -- 그대로 남겼다. 사람이 **여기서** 고칠 수 있으므로(편집칸) 발행 시점이 아니라
        -- 승인 시점에 막는다 — 발행에서 막으면 이미 결정이 끝난 뒤라 되돌리기 번거롭다.
        -- 조용히 지우지 않는다: 무엇을 지울지는 사람이 정한다.
        IF v_title ~ '[가-힣ㄱ-ㆎ]' OR v_desc ~ '[가-힣ㄱ-ㆎ]' THEN
            RAISE EXCEPTION '일본 채널 문구에 한글이 남아 있습니다 — 제목·설명에서 지운 뒤 다시 승인하세요 (제목: %)',
                            coalesce((SELECT string_agg(w, ' · ')
                                        FROM unnest(string_to_array(v_title || ' ' || v_desc, ' ')) w
                                       WHERE w ~ '[가-힣ㄱ-ㆎ]'), '');
        END IF;
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
                    'title', v_title,               -- 사람이 승인한 그 제목이 올라간다
                    'description', v_desc,
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

        -- 승인된 그 문구를 카드에도 남긴다 — 나중에 카드를 보면 초벌이 아니라
        -- **실제로 올라간 것**이 보여야 한다(사람이 고쳤을 때 특히).
        UPDATE public.review_queue
           SET payload = payload || jsonb_build_object('approved_title', v_title,
                                                       'approved_description', v_desc)
         WHERE id = p_review_id;

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



INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0096','claude (0096 한글 잔존 승인 차단)')
ON CONFLICT DO NOTHING;
