-- =====================================================================
-- 0049_editor_tts_audio.sql — 편집실 내레이션 미리듣기 재료의 캐시 판정 (2026-08-19, F-204)
--
-- 어댑터가 합성 mp3(checkpoint_resources.tts_cue_files 의 파일)를 ves-outputs 에 올리고
-- timeline.tts[].key 로 노출한다 — 편집실이 문구를 고치기 전의 '실제 음성'을 들려준다.
-- 구 재료에는 오디오가 없으므로 한 번 다시 떠야 한다. 그 판정을 여기 넣는다.
--
-- 세대 마커(tts_gen)인 이유는 0048 과 같다: 'mp3 존재'를 조건으로 걸면 cue 에 파일
-- 경로가 없는 구 run·내레이션 없는 run 이 재생성해도 조건을 영영 못 채워 열 때마다
-- 무한 재생성된다. 마커는 "신 코드 산출물인가"만 묻는다.
--
-- ⚠ 적용 순서: **DB 먼저**가 시스템의 유일한 순서다 — updater 의 마이그레이션 게이트
-- (★③)가 '새 코드 + 구 스키마'를 막으므로, 이 파일이 적용돼야 노드가 신 어댑터로
-- 올라간다. 적용~노드 갱신 사이 창에서 구 어댑터가 tts_gen 없는 재료를 다시 쓰면
-- 열 때마다 재생성된다(유한, 자가 치유 — 0048 실측과 같은 패턴).
--
-- 본문은 0048 판 전문 + 캐시 조건 한 줄(tts_gen) 델타 — 0045 규율 그대로.
-- 짝: ves/adapters/editor_assets.py(TTS_GEN=1·오디오 업로드) · 대시보드 내레이션 탭 ▶.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.request_editor_assets(p_review_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_ex record; v_job uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq WHERE rq.id = p_review_id;
    IF NOT FOUND THEN RAISE EXCEPTION '없는 검수 항목입니다'; END IF;
    IF v_rq.work_order_id IS NULL THEN
        RAISE EXCEPTION '작업지시 없는 카드는 편집실 대상이 아닙니다(잔망루피 등)';
    END IF;

    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC LIMIT 1;
    IF v_gen.run_id IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/node) 없음 — 편집실을 열 수 없습니다';
    END IF;

    -- 캐시 재사용 조건(0045 + 0048 + 0049): ready · 만료 전 · 편집용 영상까지 갖춤 ·
    -- 신 세대 scan(0048) · **신 세대 내레이션 오디오**(0049 — 머리말 참고).
    SELECT status, expires_at,
           (sprites->'assets'->'media'->>'scan') AS scan_key,
           coalesce((sprites->'assets'->'media'->>'scan_bytes')::bigint, 0) AS scan_bytes,
           coalesce((sprites->'assets'->'media'->>'scan_gen')::int, 1) AS scan_gen,
           coalesce((sprites->'assets'->>'tts_gen')::int, 0) AS tts_gen
      INTO v_ex FROM public.editor_assets WHERE run_id = v_gen.run_id;
    IF FOUND AND v_ex.status = 'ready' AND v_ex.expires_at > now() + interval '1 day'
       AND v_ex.scan_key IS NOT NULL AND v_ex.scan_bytes <= 400 * 1024 * 1024
       AND v_ex.scan_gen >= 2 AND v_ex.tts_gen >= 1 THEN
        RETURN jsonb_build_object('run_id', v_gen.run_id, 'status', 'ready', 'cached', true);
    END IF;

    INSERT INTO public.editor_assets (run_id, work_order_id, review_id, status, updated_at)
    VALUES (v_gen.run_id, v_rq.work_order_id, p_review_id, 'pending', now())
    ON CONFLICT (run_id) DO UPDATE SET status='pending', review_id=excluded.review_id,
        error=NULL, updated_at=now();

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('editor_assets', v_rq.work_order_id,
            jsonb_build_object('run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                               'review_id', p_review_id,
                               'channel_slug', v_rq.channel_slug),
            'editor_assets:' || v_gen.run_id,
            ARRAY[]::uuid[], ARRAY['generate', 'node:' || v_gen.node_id], 1800, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
    RETURNING id INTO v_job;

    PERFORM public._audit('editor_open','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_job, 'node', v_gen.node_id));
    RETURN jsonb_build_object('run_id', v_gen.run_id, 'status', 'pending',
                              'job_id', v_job, 'node', v_gen.node_id);
END $$;

REVOKE ALL     ON FUNCTION public.request_editor_assets(uuid) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.request_editor_assets(uuid) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0049','claude (편집실 내레이션 미리듣기 — 오디오 세대 마커)')
ON CONFLICT DO NOTHING;
