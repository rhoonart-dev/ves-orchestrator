-- 0119 편집실 다시 제출 — 같은 수정이 실패로 끝났으면 다시 낼 수 있게(2026-09-30)
-- 원본 캐시가 치워져 '원본 영상을 찾을 수 없어요'로 실패한 뒤, 고친 내용 그대로 다시 제출하면
-- idempotency_key 가 실패한 잡에 묶여 '같은 수정을 이미 제출했어요'로 막혔다.
-- 대기·실행 중이거나 성공한 같은 수정은 지금처럼 막는다.
CREATE OR REPLACE FUNCTION public.request_tikitaka_edit(p_video uuid, p_overrides jsonb, p_based_on text, p_note text DEFAULT NULL::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE v record; v_job uuid; v_email text; v_key text;
BEGIN
  IF NOT public.has_role(auth.uid(), 'reviewer') THEN RAISE EXCEPTION '편집하려면 검수자 권한이 필요해요'; END IF;
  IF p_overrides IS NULL OR jsonb_typeof(p_overrides) <> 'object' OR p_overrides = '{}'::jsonb THEN RAISE EXCEPTION '고친 내용이 없어요'; END IF;
  SELECT id, work_order_id, suffix, node_id, render_fingerprint INTO v FROM public.tikitaka_videos WHERE id = p_video FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
  IF v.render_fingerprint IS DISTINCT FROM p_based_on THEN
    RAISE EXCEPTION '편집실을 연 뒤에 영상이 새로 만들어졌어요. 편집실을 다시 열어 최신 판에서 고쳐 주세요';
  END IF;
  IF v.node_id IS NULL THEN RAISE EXCEPTION '이 영상을 만든 맥미니를 알 수 없어요'; END IF;
  IF EXISTS (SELECT 1 FROM public.job_queue WHERE kind = 'tikitaka_apply_edit' AND params->>'video_id' = p_video::text
               AND status IN ('pending','running')) THEN
    RAISE EXCEPTION '이 영상을 다시 렌더하는 중이에요. 끝나면 새 판에서 고쳐 주세요';
  END IF;
  SELECT email INTO v_email FROM auth.users WHERE id = auth.uid();
  v_key := 'tikitaka-edit:' || encode(extensions.digest(p_video::text || '|' || p_based_on || '|' || p_overrides::text, 'sha256'), 'hex');
  -- 같은 수정이 실패·취소로 끝났으면 다시 낼 수 있게 그 잡의 열쇠를 비켜 둔다(원본이 치워져 실패한 뒤 같은 수정을 다시 내던 것이 막혔다)
  UPDATE public.job_queue SET idempotency_key = idempotency_key || ':retired:' || id::text
   WHERE idempotency_key = v_key AND status IN ('failed','dead','cancelled');
  INSERT INTO public.job_queue (work_order_id, kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
  VALUES (v.work_order_id, 'tikitaka_apply_edit',
          jsonb_build_object('video_id', p_video::text, 'suffix', v.suffix, 'overrides', p_overrides,
                             'based_on', p_based_on, 'by', coalesce(v_email, auth.uid()::text), 'note', left(coalesce(p_note, ''), 500)),
          v_key,
          ARRAY['generate', 'node:' || v.node_id], 300, 200)
  ON CONFLICT (idempotency_key) DO NOTHING
  RETURNING id INTO v_job;
  IF v_job IS NULL THEN RAISE EXCEPTION '같은 수정을 이미 제출했어요'; END IF;
  UPDATE public.tikitaka_edit_drafts SET submitted_job = v_job WHERE video_id = p_video AND user_id = auth.uid();
  PERFORM public._audit('request_tikitaka_edit', 'tikitaka_videos', p_video::text,
          jsonb_build_object('job', v_job, 'node', v.node_id, 'based_on', p_based_on));
  RETURN jsonb_build_object('edit_id', v_job, 'rendering', true, 'node', v.node_id);
END $function$;

