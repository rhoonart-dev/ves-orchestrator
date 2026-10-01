-- 0122 유튜브 원천 지금 확인(2026-10-01) — 소스 창고에서 원천을 저장하면 아침 7시를 기다리지 않고 바로 새 클립을 모은다.
-- 원천마다 register_playlist, 원천이 둘 이상이면 그 뒤에 youtube_overlap(scheduler/youtube_watch 와 같은 잡). 10분 안에 다시 누르면 같은 잡이라 두 번 걸리지 않는다.
CREATE OR REPLACE FUNCTION public.request_youtube_check(p_work text)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record; v_ids uuid[] := '{}'; v_id uuid; v_slot text := to_char(date_trunc('minute', now()) - (extract(minute FROM now())::int % 10) * interval '1 minute', 'YYYYMMDDHH24MI');
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  FOR v IN SELECT id, url FROM public.work_youtube_sources WHERE work_title = p_work AND is_active ORDER BY rank LOOP
    INSERT INTO public.job_queue(kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
    VALUES ('register_playlist', jsonb_build_object('yt_source_id', v.id, 'work_title', p_work, 'playlist_url', v.url),
            'ytcheck:' || v.id || ':' || v_slot, ARRAY['network'], 300, 140)
    ON CONFLICT (idempotency_key) DO NOTHING RETURNING id INTO v_id;
    IF v_id IS NULL THEN SELECT id INTO v_id FROM public.job_queue WHERE idempotency_key = 'ytcheck:' || v.id || ':' || v_slot; END IF;
    v_ids := v_ids || v_id; v_id := NULL;
  END LOOP;
  IF cardinality(v_ids) >= 2 THEN
    INSERT INTO public.job_queue(kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
    VALUES ('youtube_overlap', jsonb_build_object('work_title', p_work), 'ytcheck-overlap:' || p_work || ':' || v_slot,
            v_ids, ARRAY['network'], 900, 140)
    ON CONFLICT (idempotency_key) DO NOTHING;
  END IF;
  PERFORM public._audit('request_youtube_check', 'work_cards', p_work, jsonb_build_object('sources', cardinality(v_ids)));
  RETURN cardinality(v_ids);
END $$;
REVOKE ALL ON FUNCTION public.request_youtube_check(text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.request_youtube_check(text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0122','claude (유튜브 원천 지금 확인)');
