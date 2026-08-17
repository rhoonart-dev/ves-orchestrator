-- =====================================================================
-- 0044_editor_draft_and_geoblock.sql — 편집 초안 보관 + 발행 전 채널 안내 (2026-08-17)
--
-- ① 편집 초안(draft): 편집실에서 제목·자막을 고치다 그냥 나가면 그 수정이 사라졌다.
--    실제 사용에서 "열어놓고 재렌더는 안 한" 상태가 계속 생기므로, 화면이 고칠 때마다
--    여기에 담아두고 편집실 첫 화면에서 **이어서 할 목록**으로 보여준다.
--    재렌더를 보내면 초안은 지운다 — 남아 있으면 '아직 안 보낸 것'과 구분이 안 된다.
--    editor_assets 에 붙이는 이유: run 당 1행이라 초안도 run 당 1개가 자연스럽고,
--    재료(timeline·sprites)와 함께 7일 뒤 같이 사라지는 편이 맞다.
--
-- ② 발행 전 채널 안내(geoblock_notice): 채널에 따라 발행 후 사람이 반드시 해야 하는
--    후속 조치가 있다(재미쇼츠 = YouTube Studio 국가 제한). 잊으면 권리 문제가 되므로
--    발행 버튼과 실제 발행 사이에 확인을 한 번 끼운다. 채널 목록을 코드에 박지 않고
--    ops_config 에 두는 이유는 채널이 계속 늘기 때문이다 — 값만 고치면 된다.
--
-- 짝: 대시보드 '편집실' 탭·검수함 발행 버튼 · ves/adapters/aivideo.py.
-- =====================================================================

ALTER TABLE public.editor_assets
  ADD COLUMN IF NOT EXISTS draft    jsonb,
  ADD COLUMN IF NOT EXISTS draft_at timestamptz,
  ADD COLUMN IF NOT EXISTS draft_by text;

COMMENT ON COLUMN public.editor_assets.draft IS
  '보내지 않은 편집 내용(edit_overrides 와 같은 모양: title/subtitles/clips). 재렌더 시 NULL.';

CREATE INDEX IF NOT EXISTS editor_assets_draft_idx
    ON public.editor_assets(draft_at DESC) WHERE draft IS NOT NULL;

-- ── 초안 저장/삭제 ────────────────────────────────────────────────────
-- 화면이 입력 중 자동 저장한다(디바운스). 비우면 초안 삭제 — '고친 게 없다'와
-- '아직 안 보냈다'는 다른 상태라 빈 초안을 남기지 않는다.
CREATE OR REPLACE FUNCTION public.save_editor_draft(p_run_id text, p_draft jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_n int;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    IF p_draft IS NULL OR p_draft = '{}'::jsonb THEN
        UPDATE public.editor_assets
           SET draft=NULL, draft_at=NULL, draft_by=NULL, updated_at=now()
         WHERE run_id = p_run_id;
        GET DIAGNOSTICS v_n = ROW_COUNT;
        RETURN jsonb_build_object('run_id', p_run_id, 'draft', false, 'updated', v_n);
    END IF;
    UPDATE public.editor_assets
       SET draft = p_draft, draft_at = now(),
           draft_by = coalesce(auth.email(), auth.uid()::text), updated_at = now()
     WHERE run_id = p_run_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n = 0 THEN
        RAISE EXCEPTION '편집실 재료가 없는 run 입니다: % — 편집실을 먼저 여세요', p_run_id;
    END IF;
    RETURN jsonb_build_object('run_id', p_run_id, 'draft', true, 'updated', v_n);
END $$;

REVOKE ALL     ON FUNCTION public.save_editor_draft(text, jsonb) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.save_editor_draft(text, jsonb) TO authenticated;

-- ── 발행 전 안내 채널 ─────────────────────────────────────────────────
INSERT INTO public.ops_config(key, value, note)
VALUES ('geoblock_notice',
        '{"JAEMISHOTS":"재미쇼츠는 발행 후 YouTube Studio에서 국가 제한(지오블락)을 설정해야 합니다. 설정 없이 공개되면 권리 문제가 생깁니다."}',
        '발행 전 확인 모달을 띄울 채널 — {슬러그: 안내문}. 채널이 늘면 이 값만 고친다(0044).')
ON CONFLICT (key) DO NOTHING;

-- ── 재렌더 시 초안 비우기 (0043 갱신 — 전문 재정의) ──────────────────
-- 이 레포 규율: 기존 함수를 고칠 때는 파일을 수정하지 않고 새 번호로 다시 쓴다
-- (0024→0027→0029→0031 누적 패턴). 바뀐 곳은 ⑦ 한 줄뿐이다.
CREATE OR REPLACE FUNCTION public.submit_editor_render(
    p_review_id uuid, p_overrides jsonb, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_rq record; v_gen record; v_busy uuid;
    v_ov jsonb; v_step text; v_params jsonb; v_common jsonb;
    v_gen_job uuid; v_up uuid; v_in uuid; v_ev uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;

    IF p_overrides IS NULL OR p_overrides = '{}'::jsonb THEN
        RAISE EXCEPTION '고친 내용이 없습니다';
    END IF;
    IF NOT (p_overrides ? 'title' OR p_overrides ? 'subtitles' OR p_overrides ? 'clips'
            OR p_overrides ? 'design') THEN
        RAISE EXCEPTION '편집 항목(title/subtitles/clips/design) 이 하나도 없습니다';
    END IF;
    v_ov := p_overrides || jsonb_build_object('schema', 'edit_overrides/v1');

    SELECT rq.id, rq.work_order_id, rq.channel_slug, rq.payload INTO v_rq
      FROM public.review_queue rq
     WHERE rq.id = p_review_id AND rq.kind = 'publish_gate' AND rq.status = 'waiting'
     FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION '편집 재렌더 대상이 아닙니다 — 대기중인 발행 검수 카드만 가능합니다';
    END IF;

    SELECT id INTO v_busy FROM public.job_queue
     WHERE work_order_id = v_rq.work_order_id AND kind = 'generate'
       AND status IN ('pending','running','blocked') LIMIT 1;
    IF v_busy IS NOT NULL THEN
        RAISE EXCEPTION '이미 렌더가 대기·진행 중입니다(job %) — 끝난 뒤 다시 시도하세요', v_busy;
    END IF;

    SELECT j.node_id, j.result->>'run_id' AS run_id, j.result->>'run_dir' AS run_dir,
           j.params AS params
      INTO v_gen
      FROM public.job_queue j
     WHERE j.work_order_id = v_rq.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC LIMIT 1;
    IF v_gen.run_id IS NULL OR v_gen.run_dir IS NULL OR v_gen.node_id IS NULL THEN
        RAISE EXCEPTION 'generate 결과(run_id/run_dir/node) 없음 — 편집 재렌더 불가';
    END IF;

    v_step := CASE WHEN p_overrides ? 'clips' THEN 'resources' ELSE 'render' END;

    UPDATE public.review_queue
       SET status = 'rejected',
           decided_by = coalesce(auth.email(), auth.uid()::text),
           decided_at = now(),
           decision_note = '[편집실 재렌더] ' || coalesce(p_note, '')
     WHERE id = p_review_id;

    v_params := coalesce(v_gen.params, '{}'::jsonb) || jsonb_build_object(
                    'resume_run_id', v_gen.run_id, 'from_step', v_step,
                    'edit_overrides', v_ov,
                    'run_id', v_gen.run_id, 'run_dir', v_gen.run_dir,
                    'review_id', p_review_id);
    v_common := jsonb_build_object(
                    'work_title',   v_gen.params->>'work_title',
                    'episode',      v_gen.params->'episode',
                    'channel_slug', coalesce(v_gen.params->>'channel_slug', v_rq.channel_slug),
                    'channel_name', v_gen.params->>'channel_name',
                    'outdir',       coalesce(v_gen.params->>'outdir', 'outputs'),
                    'run_id',       v_gen.run_id, 'run_dir', v_gen.run_dir);

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('generate', v_rq.work_order_id, v_params,
            'editrender:' || p_review_id,
            ARRAY[]::uuid[], ARRAY['generate', 'node:' || v_gen.node_id], 300, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            params=excluded.params, updated_at=now()
    RETURNING id INTO v_gen_job;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('upload_artifacts', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':up',
            ARRAY[v_gen_job], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_up;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('ingest', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':in',
            ARRAY[v_up], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_in;

    INSERT INTO public.job_queue
        (kind, work_order_id, params, idempotency_key, depends_on, required_caps,
         lease_ttl_sec, priority)
    VALUES ('evaluate', v_rq.work_order_id, v_common,
            'editrender:' || p_review_id || ':ev',
            ARRAY[v_in], ARRAY['analyze'], 120, 150)
    ON CONFLICT (idempotency_key) DO UPDATE
        SET status='pending', attempt=0, error=NULL, error_class=NULL, result=NULL,
            node_id=NULL, lease_expires_at=NULL, run_after=now(),
            depends_on=excluded.depends_on, params=excluded.params, updated_at=now()
    RETURNING id INTO v_ev;

    -- ⑦ 재료는 낡았고(구간·자막이 바뀐다) 초안은 이제 보냈다 — 둘 다 정리.
    --    초안을 남기면 편집실 목록에 '아직 안 보낸 것'으로 계속 떠서 사람을 혼란시킨다.
    UPDATE public.editor_assets
       SET status='pending', draft=NULL, draft_at=NULL, draft_by=NULL, updated_at=now()
     WHERE run_id = v_gen.run_id;

    PERFORM public._audit('editor_render','review_queue', p_review_id::text,
            jsonb_build_object('run_id', v_gen.run_id, 'job', v_gen_job,
                               'node', v_gen.node_id, 'from_step', v_step,
                               'note', p_note,
                               'keys', (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_overrides) k),
                               'subs', jsonb_array_length(coalesce(p_overrides->'subtitles','[]'::jsonb)),
                               'clips', jsonb_array_length(coalesce(p_overrides->'clips','[]'::jsonb))));
    RETURN jsonb_build_object('review_id', p_review_id, 'work_order_id', v_rq.work_order_id,
                              'run_id', v_gen.run_id, 'job_id', v_gen_job,
                              'node', v_gen.node_id, 'from_step', v_step,
                              'chain', jsonb_build_array(v_gen_job, v_up, v_in, v_ev));
END $$;

REVOKE ALL     ON FUNCTION public.submit_editor_render(uuid, jsonb, text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.submit_editor_render(uuid, jsonb, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0044','claude (편집 초안 보관 · 발행 전 채널 안내)')
ON CONFLICT DO NOTHING;
