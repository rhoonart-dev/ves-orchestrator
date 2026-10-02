-- 0127 지역 제한이 필요한 작품도 예약 발행(2026-10-02) — 막지 않고, 공개 전에 스튜디오에서 지역 제한을 걸라고 알린다.
-- 사용자 운영: "지오블락 설정해야 해도 이전에는 일단 예약발행을 하고 스튜디오에 가서 고쳤다". tikitaka_reviews.meta.geo_block_todo 로 남겨 검수 카드가 알린다.
-- 0120 tikitaka_review_approve 와 같고 지역 제한 줄만 바꿨다.
CREATE OR REPLACE FUNCTION public.tikitaka_review_approve(p_video uuid, p_based_on text, p_meta jsonb, p_episode_part integer DEFAULT NULL,
  p_remarks text DEFAULT NULL, p_publish_at timestamptz DEFAULT NULL, p_is_aired boolean DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE ctx jsonb; v jsonb; ch jsonb; w jsonb; a jsonb; r record; route text; ep int; job uuid; meta jsonb; tags jsonb;
BEGIN
 IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '검수자 권한이 필요해요'; END IF;
 ctx := public._tikitaka_review_ctx(p_video, p_based_on);
 v := ctx->'video'; ch := ctx->'channel'; w := ctx->'work'; a := ctx->'application';
 SELECT * INTO r FROM public.tikitaka_reviews WHERE video_id = p_video FOR UPDATE;
 IF FOUND AND r.fingerprint = p_based_on AND r.stage NOT IN ('rejected','needs_attention')
    AND NOT (r.stage IN ('uploading','scheduling') AND EXISTS (SELECT 1 FROM public.job_queue
             WHERE id = r.upload_job_id AND status IN ('failed','dead','cancelled'))) THEN   -- 올리기가 실패했으면 다시 승인할 수 있다
  RAISE EXCEPTION '이미 승인해서 다음 단계가 진행 중이에요';
 END IF;
 IF FOUND AND r.fingerprint = p_based_on AND r.youtube_id IS NOT NULL THEN
  RAISE EXCEPTION '이 판은 이미 유튜브에 올라가 있어요. 레이블리 신청만 다시 시도해 주세요';
 END IF;
 IF a IS NULL OR jsonb_typeof(a) = 'null' OR (a->>'status')::boolean IS NOT TRUE OR (a->>'rejected_bool')::boolean IS TRUE THEN
  RAISE EXCEPTION '이 채널의 작품 사용 신청이 아직 승인되지 않았어요. 레이블리에서 사용 신청을 먼저 확인해 주세요';
 END IF;
 route := CASE w->>'inspection_policy' WHEN 'required' THEN 'rights' WHEN 'none' THEN 'direct'
            WHEN 'unaired_only' THEN CASE WHEN p_is_aired IS NULL THEN NULL WHEN p_is_aired THEN 'direct' ELSE 'rights' END END;
 IF route IS NULL THEN
  RAISE EXCEPTION '%', CASE WHEN w->>'inspection_policy' = 'unaired_only' THEN '방영 여부를 먼저 골라 주세요'
                         ELSE '이 작품의 검수 정책이 정해지지 않았어요. 권리사 검수에서 작품 검수 정책을 먼저 정해 주세요' END;
 END IF;
 -- 유튜브 제목 · 설명 · 태그(사람이 확인 · 고친 값)
 tags := CASE WHEN jsonb_typeof(p_meta->'tags') = 'array' THEN p_meta->'tags' ELSE '[]'::jsonb END;
 IF coalesce(btrim(p_meta->>'title'), '') = '' THEN RAISE EXCEPTION '유튜브 제목을 적어 주세요'; END IF;
 IF length(p_meta->>'title') > 100 THEN RAISE EXCEPTION '유튜브 제목은 100자까지예요'; END IF;
 IF length(coalesce(p_meta->>'description', '')) > 5000 THEN RAISE EXCEPTION '설명은 5000자까지예요'; END IF;
 IF jsonb_array_length(tags) > 15 THEN RAISE EXCEPTION '태그는 15개까지예요'; END IF;
 meta := jsonb_build_object('title', btrim(p_meta->>'title'), 'description', coalesce(p_meta->>'description', ''), 'tags', tags);
 IF route = 'rights' THEN
  ep := public._episode_no(v->>'episode');
  IF ep IS NULL THEN RAISE EXCEPTION '회차를 알 수 없어 권리사 검수를 신청할 수 없어요'; END IF;
  IF p_episode_part IS NULL OR p_episode_part < 1 THEN RAISE EXCEPTION '영상 번호를 확인해 주세요'; END IF;
 ELSE
  IF p_publish_at IS NULL OR p_publish_at < now() + interval '10 minutes' THEN
   RAISE EXCEPTION '공개 시각은 지금보다 10분 이상 뒤로 골라 주세요';
  END IF;
  -- 지역 제한이 필요한 작품도 일단 비공개 + 예약으로 올리고, 공개 전에 사람이 스튜디오에서 지역 제한을 건다(0127 — 사용자 운영 방식)
  IF (w->>'geo_block_required')::boolean IS TRUE THEN
   meta := meta || jsonb_build_object('geo_block_todo', true);
  END IF;
 END IF;
 -- 같은 판의 올리기가 실패 · 취소로 끝났으면(유튜브까지 못 갔다) 다시 걸 수 있게 그 열쇠를 비켜 둔다(0119 와 같은 방식)
 UPDATE public.job_queue SET idempotency_key = idempotency_key || ':retired:' || id::text
  WHERE idempotency_key = 'tikitaka-publish:' || p_video::text || ':' || p_based_on || ':' || route AND status IN ('failed','dead','cancelled');
 INSERT INTO public.job_queue (work_order_id, kind, params, idempotency_key, required_caps, lease_ttl_sec, priority, max_attempts)
 VALUES ((v->>'work_order_id')::uuid, 'tikitaka_publish',
   jsonb_build_object('video_id', p_video::text, 'fingerprint', p_based_on, 'channel_slug', ch->>'token_slug',
     'channel_id', ch->>'channel_id', 'privacy', CASE WHEN route = 'rights' THEN 'unlisted' ELSE 'private' END,
     'publish_at', CASE WHEN route = 'direct' THEN to_char(p_publish_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"') END,
     'purpose', CASE WHEN route = 'rights' THEN 'inspection' ELSE 'schedule' END, 'meta', meta),
   'tikitaka-publish:' || p_video::text || ':' || p_based_on || ':' || route,
   ARRAY['publish', 'node:' || (v->>'node_id')], 3600, 150, 1)   -- 다시 시도하지 않는다: 올리기가 저쪽에서 끝났는데 답만 잃을 수 있다
 ON CONFLICT (idempotency_key) DO NOTHING
 RETURNING id INTO job;
 IF job IS NULL THEN RAISE EXCEPTION '이 판은 이미 올리기를 시작했어요. 작업 이력에서 결과를 확인해 주세요'; END IF;
 INSERT INTO public.tikitaka_reviews(video_id, fingerprint, stage, route, work_id, application_id, policy, is_aired, episode, episode_part,
   remarks, meta, decided_by, decided_at, upload_job_id, publish_at, publish_kind, prev_inspection_id)
 VALUES (p_video, p_based_on, CASE WHEN route = 'rights' THEN 'uploading' ELSE 'scheduling' END, route, w->>'id', a->>'id',
   w->>'inspection_policy', p_is_aired, ep, CASE WHEN route = 'rights' THEN p_episode_part END, left(p_remarks, 3000), meta,
   auth.uid(), now(), job, CASE WHEN route = 'direct' THEN p_publish_at END, CASE WHEN route = 'direct' THEN 'auto' END,
   CASE WHEN r.video_id IS NOT NULL THEN coalesce(r.inspection_id, r.prev_inspection_id) END)
 ON CONFLICT (video_id) DO UPDATE SET fingerprint = EXCLUDED.fingerprint, stage = EXCLUDED.stage, route = EXCLUDED.route,
   work_id = EXCLUDED.work_id, application_id = EXCLUDED.application_id, policy = EXCLUDED.policy, is_aired = EXCLUDED.is_aired,
   episode = EXCLUDED.episode, episode_part = EXCLUDED.episode_part, remarks = EXCLUDED.remarks, meta = EXCLUDED.meta,
   decided_by = EXCLUDED.decided_by, decided_at = EXCLUDED.decided_at, upload_job_id = EXCLUDED.upload_job_id,
   publish_at = EXCLUDED.publish_at, publish_kind = EXCLUDED.publish_kind, prev_inspection_id = EXCLUDED.prev_inspection_id,
   reject_note = NULL, youtube_id = NULL, inspection_id = NULL, inspection_round = NULL, attachment_key = NULL,
   published_by = NULL, error = NULL, updated_at = now();
 PERFORM public._audit('tikitaka_review_approve', 'tikitaka_videos', p_video::text,
   jsonb_build_object('based_on', p_based_on, 'route', route, 'job', job, 'publish_at', p_publish_at));
 RETURN jsonb_build_object('stage', CASE WHEN route = 'rights' THEN 'uploading' ELSE 'scheduling' END, 'route', route, 'job', job);
END $$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0127','claude (지역 제한 작품도 예약 발행 · 스튜디오 알림)');
