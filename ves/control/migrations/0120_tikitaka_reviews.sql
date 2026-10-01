-- 0120 새 파이프라인(맥미니) 영상 검수 흐름 — 내부 검수 → (권리사 검수 필요 작품) 일부공개 업로드 · 레이블리 신청 → 권리사 검수 → 공개
-- (2026-10-01). 예전 review_queue 흐름(워크스페이스 로컬 서버 workflow_api)은 예전 파이프라인 전용이라 새로 짠다.
--
-- 편(tikitaka_videos) 하나에 검수 기록 하나. 편이 다시 렌더되면(render_fingerprint 가 바뀌면) 새 판으로 내부 검수를 다시 한다 —
-- 그때 이전 레이블리 신청 id 는 prev_inspection_id 로 남겨 다음 신청이 그걸 대체(supersedes)한다.
-- 쓰기는 아래 RPC 로만(검수자부터). 업로드는 맥미니 tikitaka_publish 잡, 레이블리 신청은 스케줄러(tikitaka_inspect_submit).
-- 유튜브 연결이 '올리기' 권한뿐인 채널이 많아(올린 영상의 공개 상태를 바꿀 수 없다) 권리사 승인 뒤 공개는 사람이 스튜디오에서 하고
-- 그 시각을 여기 적는다(mark_published). 검수가 필요 없는 작품은 올릴 때 비공개 + 예약 시각을 함께 걸어 바로 예약된다.

CREATE TABLE public.tikitaka_reviews (
 video_id uuid PRIMARY KEY REFERENCES public.tikitaka_videos(id) ON DELETE CASCADE,
 fingerprint text NOT NULL,
 stage text NOT NULL CHECK (stage IN ('rejected','uploading','submitting','rights_pending','scheduling','scheduled','needs_attention')),
 route text NOT NULL CHECK (route IN ('rights','direct')),
 work_id text, application_id text, policy text, is_aired boolean,
 episode integer, episode_part integer CHECK (episode_part IS NULL OR episode_part BETWEEN 1 AND 999),
 remarks text CHECK (remarks IS NULL OR length(remarks) <= 3000),
 meta jsonb NOT NULL DEFAULT '{}'::jsonb,
 reject_note text CHECK (reject_note IS NULL OR length(reject_note) <= 2000),
 decided_by uuid REFERENCES auth.users(id), decided_at timestamptz,
 upload_job_id uuid, youtube_id text,
 inspection_id text, inspection_round integer, prev_inspection_id text,
 attachment_key text,
 publish_at timestamptz, publish_kind text CHECK (publish_kind IS NULL OR publish_kind IN ('auto','studio')),
 published_by uuid REFERENCES auth.users(id),
 error text,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX tikitaka_reviews_stage ON public.tikitaka_reviews(stage);
ALTER TABLE public.tikitaka_reviews ENABLE ROW LEVEL SECURITY;
CREATE POLICY tikitaka_reviews_read ON public.tikitaka_reviews FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.tikitaka_reviews TO authenticated;

-- 회차 글자('1화' · '12')에서 숫자만 — 레이블리 신청은 회차를 정수로 받는다
CREATE FUNCTION public._episode_no(p text) RETURNS integer LANGUAGE sql IMMUTABLE AS $$
 SELECT nullif(substring(coalesce(p,'') from '(\d+)'), '')::integer $$;

-- 편 · 채널 · 작품 · 사용 신청을 한 번에(검수 흐름 RPC 공용). 레이블리는 우리 사본(laeebly_works · laeebly_applications, 0116·0117)
CREATE FUNCTION public._tikitaka_review_ctx(p_video uuid, p_based_on text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record; ch record; w record; a record; n int;
BEGIN
 SELECT id, work_order_id, node_id, suffix, channel_slug, work_title, episode, render_fingerprint INTO v
   FROM public.tikitaka_videos WHERE id = p_video FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
 IF v.render_fingerprint IS DISTINCT FROM p_based_on THEN
  RAISE EXCEPTION '화면을 연 뒤에 영상이 새로 만들어졌어요. 새로고침한 뒤 다시 해 주세요';
 END IF;
 IF EXISTS (SELECT 1 FROM public.job_queue WHERE kind = 'tikitaka_apply_edit' AND params->>'video_id' = p_video::text
              AND status IN ('pending','running')) THEN
  RAISE EXCEPTION '이 영상을 다시 렌더하는 중이에요. 끝나면 새 판에서 검수해 주세요';
 END IF;
 SELECT token_slug, name, channel_id, gcp_project INTO ch FROM public.channels_mirror WHERE token_slug = v.channel_slug;
 IF NOT FOUND OR ch.channel_id IS NULL THEN RAISE EXCEPTION '이 영상의 채널을 찾지 못했어요. 채널 관리에서 채널을 확인해 주세요'; END IF;
 SELECT count(*) INTO n FROM public.laeebly_works WHERE title = v.work_title;
 IF n <> 1 THEN RAISE EXCEPTION '레이블리 작품을 하나로 찾지 못했어요(같은 제목 %개). 작품 관리에서 작품 이름을 확인해 주세요', n; END IF;
 SELECT id, title, inspection_policy, company, geo_block_required INTO w FROM public.laeebly_works WHERE title = v.work_title;
 SELECT id, status, rejected_bool INTO a FROM public.laeebly_applications
  WHERE video_id = w.id AND youtube_channel_id = ch.channel_id ORDER BY synced_at DESC LIMIT 1;
 RETURN jsonb_build_object('video', to_jsonb(v), 'channel', to_jsonb(ch), 'work', to_jsonb(w), 'application', to_jsonb(a));
END $$;
REVOKE ALL ON FUNCTION public._tikitaka_review_ctx(uuid, text) FROM public, anon, authenticated;

-- 내부 검수 반려 — 편집실에서 고쳐 새 판이 나오면 다시 내부 검수
CREATE FUNCTION public.tikitaka_review_reject(p_video uuid, p_based_on text, p_note text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE ctx jsonb; r record;
BEGIN
 IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '검수자 권한이 필요해요'; END IF;
 IF coalesce(btrim(p_note), '') = '' THEN RAISE EXCEPTION '반려 사유를 적어 주세요'; END IF;
 ctx := public._tikitaka_review_ctx(p_video, p_based_on);
 SELECT * INTO r FROM public.tikitaka_reviews WHERE video_id = p_video FOR UPDATE;
 IF FOUND AND r.fingerprint = p_based_on AND r.stage NOT IN ('rejected','needs_attention') THEN
  RAISE EXCEPTION '이미 승인해서 다음 단계가 진행 중이에요';
 END IF;
 INSERT INTO public.tikitaka_reviews(video_id, fingerprint, stage, route, reject_note, decided_by, decided_at, prev_inspection_id)
 VALUES (p_video, p_based_on, 'rejected', coalesce(r.route, 'rights'), left(btrim(p_note), 2000), auth.uid(), now(),
         coalesce(r.inspection_id, r.prev_inspection_id))
 ON CONFLICT (video_id) DO UPDATE SET fingerprint = EXCLUDED.fingerprint, stage = 'rejected', reject_note = EXCLUDED.reject_note,
   decided_by = EXCLUDED.decided_by, decided_at = EXCLUDED.decided_at, prev_inspection_id = EXCLUDED.prev_inspection_id,
   upload_job_id = NULL, youtube_id = NULL, inspection_id = NULL, inspection_round = NULL, attachment_key = NULL,
   publish_at = NULL, publish_kind = NULL, error = NULL, updated_at = now();
 PERFORM public._audit('tikitaka_review_reject', 'tikitaka_videos', p_video::text, jsonb_build_object('based_on', p_based_on));
 RETURN jsonb_build_object('stage', 'rejected');
END $$;

-- 내부 승인 — 권리사 검수가 필요하면 일부공개로 올려 레이블리에 신청, 아니면 비공개 + 예약 시각으로 올린다(맥미니 tikitaka_publish)
CREATE FUNCTION public.tikitaka_review_approve(p_video uuid, p_based_on text, p_meta jsonb, p_episode_part integer DEFAULT NULL,
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
  IF (w->>'geo_block_required')::boolean IS TRUE THEN
   RAISE EXCEPTION '지역 제한이 필요한 작품이에요. 유튜브 스튜디오에서 지역 제한과 공개를 직접 설정해 주세요';
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

-- 권리사 승인 뒤 스튜디오에서 직접 공개 · 예약한 시각을 적는다(검수한 일부공개 링크 그대로 공개돼야 해서 사람이 바꾼다)
CREATE FUNCTION public.tikitaka_review_mark_published(p_video uuid, p_publish_at timestamptz)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE r record; i record;
BEGIN
 IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '검수자 권한이 필요해요'; END IF;
 IF p_publish_at IS NULL THEN RAISE EXCEPTION '공개(또는 예약)한 시각을 적어 주세요'; END IF;
 SELECT * INTO r FROM public.tikitaka_reviews WHERE video_id = p_video FOR UPDATE;
 IF NOT FOUND OR r.route <> 'rights' OR r.stage NOT IN ('rights_pending','scheduled') OR r.youtube_id IS NULL THEN
  RAISE EXCEPTION '권리사 승인을 받은 영상만 적을 수 있어요';
 END IF;
 SELECT status, revision_outcome INTO i FROM public.laeebly_inspections WHERE id = r.inspection_id;
 IF NOT FOUND OR i.status <> 'completed' OR i.revision_outcome IS NOT NULL THEN
  RAISE EXCEPTION '권리사 승인이 아직 확인되지 않았어요. 몇 분 뒤 다시 해 주세요';
 END IF;
 UPDATE public.tikitaka_reviews SET stage = 'scheduled', publish_at = p_publish_at, publish_kind = 'studio',
   published_by = auth.uid(), updated_at = now() WHERE video_id = p_video;
 PERFORM public._audit('tikitaka_review_published', 'tikitaka_videos', p_video::text, jsonb_build_object('publish_at', p_publish_at));
 RETURN jsonb_build_object('stage', 'scheduled');
END $$;

-- 레이블리 신청을 못 했을 때(needs_attention) 다시 시도 — 올린 영상은 그대로 두고 신청만 다시
CREATE FUNCTION public.tikitaka_review_retry_submit(p_video uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
 IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '검수자 권한이 필요해요'; END IF;
 UPDATE public.tikitaka_reviews SET stage = 'submitting', error = NULL, updated_at = now()
  WHERE video_id = p_video AND stage = 'needs_attention' AND route = 'rights' AND youtube_id IS NOT NULL AND inspection_id IS NULL;
 IF NOT FOUND THEN RAISE EXCEPTION '다시 신청할 수 있는 상태가 아니에요'; END IF;
 PERFORM public._audit('tikitaka_review_retry', 'tikitaka_videos', p_video::text, '{}'::jsonb);
 RETURN jsonb_build_object('stage', 'submitting');
END $$;

REVOKE ALL ON FUNCTION public.tikitaka_review_reject(uuid, text, text) FROM public, anon;
REVOKE ALL ON FUNCTION public.tikitaka_review_approve(uuid, text, jsonb, integer, text, timestamptz, boolean) FROM public, anon;
REVOKE ALL ON FUNCTION public.tikitaka_review_mark_published(uuid, timestamptz) FROM public, anon;
REVOKE ALL ON FUNCTION public.tikitaka_review_retry_submit(uuid) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.tikitaka_review_reject(uuid, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.tikitaka_review_approve(uuid, text, jsonb, integer, text, timestamptz, boolean) TO authenticated;
GRANT EXECUTE ON FUNCTION public.tikitaka_review_mark_published(uuid, timestamptz) TO authenticated;
GRANT EXECUTE ON FUNCTION public.tikitaka_review_retry_submit(uuid) TO authenticated;

-- 레이블리 신청에 붙이는 완성본 사본(1년 서명 링크) — 서비스 키(맥미니 스케줄러)만 쓴다
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES ('workspace-inspections', 'workspace-inspections', false, 262144000, ARRAY['video/mp4'])
ON CONFLICT (id) DO NOTHING;
