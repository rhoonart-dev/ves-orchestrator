-- =====================================================================
-- 0007_rpc_dashboard.sql — 대시보드 RLS + RPC (ARCHITECTURE §10)
-- ⚠ 적용은 사용자 확인 후. 0006 선행 필수. 전량 가산적.
--
-- 원칙(R15): anon key 는 공개값 — JS 검증은 UX 일 뿐. 규칙은 전부 이 파일 안에 산다.
--   읽기: authenticated 전원 / 쓰기: security definer RPC 만 (테이블 쓰기 정책 없음)
--   워커·brain 스크립트는 직결 계정(테이블 소유자)이라 RLS 우회 — FORCE RLS 금지.
-- =====================================================================

-- ── 역할 (미결정 §17-② 최소 구현: user_roles + has_role) ─────────────
CREATE TABLE IF NOT EXISTS public.user_roles (
    user_id uuid PRIMARY KEY,
    role    text NOT NULL DEFAULT 'viewer',
    note    text,
    CONSTRAINT user_roles_chk CHECK (role IN ('viewer','reviewer','operator','admin'))
);
ALTER TABLE public.user_roles ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ur_read ON public.user_roles;
CREATE POLICY ur_read ON public.user_roles FOR SELECT TO authenticated
  USING (user_id = auth.uid());

CREATE OR REPLACE FUNCTION public.has_role(p_user uuid, p_min text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT COALESCE((
    SELECT array_position(ARRAY['viewer','reviewer','operator','admin'], r.role)
        >= array_position(ARRAY['viewer','reviewer','operator','admin'], p_min)
      FROM public.user_roles r WHERE r.user_id = p_user), false);
$$;

-- ── RLS: 읽기 전원 · 쓰기 정책 없음 ──────────────────────────────────
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['work_orders','job_queue','job_events','artifacts',
                           'review_queue','node_registry','resource_limits',
                           'resource_leases','sources','deployments',
                           'applied_migrations','channels_mirror',
                           'dashboard_actions','loop_rounds'] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS read_all ON public.%I', t);
    EXECUTE format(
      'CREATE POLICY read_all ON public.%I FOR SELECT TO authenticated USING (true)', t);
  END LOOP;
END $$;

-- ── 감사 헬퍼 ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public._audit(p_action text, p_kind text, p_id text, p_payload jsonb)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  INSERT INTO public.dashboard_actions(actor, action, target_kind, target_id, payload)
  VALUES (auth.uid()::text, p_action, p_kind, p_id, coalesce(p_payload,'{}'::jsonb));
$$;

-- ── approve_and_publish (★① 스탬프 검증 — ARCHITECTURE §10-3 전문) ──
CREATE OR REPLACE FUNCTION public.approve_and_publish(
    p_review_id uuid, p_privacy text,
    p_publish_at timestamptz DEFAULT NULL, p_note text DEFAULT NULL
) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
  SET search_path = public, extensions AS $$  -- extensions: digest()=pgcrypto (fdidiqd 실측)
DECLARE v_rq record; v_job uuid;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    IF p_privacy NOT IN ('private','unlisted','public') THEN
        RAISE EXCEPTION 'invalid privacy %', p_privacy; END IF;

    SELECT rq.id, rq.work_order_id, rq.clip_id, rq.channel_slug,
           wo.geoblock_required
      INTO v_rq
      FROM public.review_queue rq
      JOIN public.work_orders wo ON wo.id = rq.work_order_id
     WHERE rq.id = p_review_id AND rq.kind = 'publish_gate' AND rq.status = 'waiting'
     FOR UPDATE OF rq;
    IF NOT FOUND THEN RAISE EXCEPTION 'review not waiting'; END IF;

    -- R9-a: 지오블락 필수 → private/unlisted 만 (API 로 지역제한 설정 불가, §1-1)
    IF v_rq.geoblock_required AND p_privacy NOT IN ('private','unlisted') THEN
        RAISE EXCEPTION 'R9-a: geoblock-required work — Studio manual only'; END IF;
    -- R9-c: publishAt 은 private 에만 (§1-2)
    IF p_publish_at IS NOT NULL AND p_privacy <> 'private' THEN
        RAISE EXCEPTION 'R9-c: publish_at requires privacy=private'; END IF;
    -- R10: 등록 채널 (★② 미러 참조 — 정본은 channels.json, 미러는 sync 사본)
    IF NOT EXISTS (SELECT 1 FROM public.channels_mirror
                    WHERE token_slug = v_rq.channel_slug) THEN
        RAISE EXCEPTION 'R10: unknown channel %', v_rq.channel_slug; END IF;

    UPDATE public.review_queue
       SET status='approved', decided_by=auth.uid()::text, decided_at=now(),
           decision_note=p_note
     WHERE id = p_review_id;

    INSERT INTO public.job_queue(work_order_id, kind, params, idempotency_key, required_caps)
    VALUES (v_rq.work_order_id, 'publish',
            jsonb_build_object('clip_id', v_rq.clip_id, 'channel_slug', v_rq.channel_slug,
                               'privacy', p_privacy, 'publish_at', p_publish_at),
            encode(digest(v_rq.work_order_id::text||'publish'||coalesce(v_rq.clip_id::text,''),
                          'sha256'),'hex'),
            '{publish}')
    ON CONFLICT (idempotency_key) DO NOTHING
    RETURNING id INTO v_job;

    PERFORM public._audit('approve_publish','review_queue',p_review_id::text,
            jsonb_build_object('privacy',p_privacy,'publish_at',p_publish_at));
    RETURN v_job;
END $$;

-- ── reject_review ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.reject_review(p_review_id uuid, p_note text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    UPDATE public.review_queue
       SET status='rejected', decided_by=auth.uid()::text, decided_at=now(),
           decision_note=p_note
     WHERE id = p_review_id AND status = 'waiting';
    IF NOT FOUND THEN RAISE EXCEPTION 'review not waiting'; END IF;
    PERFORM public._audit('reject','review_queue',p_review_id::text,
                          jsonb_build_object('note',p_note));
END $$;

-- ── retry_job / cancel_job ──────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.retry_job(p_job uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    UPDATE public.job_queue
       SET status='pending', attempt=0, error=NULL, error_class=NULL,
           node_id=NULL, lease_expires_at=NULL, run_after=now(), updated_at=now()
     WHERE id = p_job AND status IN ('dead','failed','cancelled');
    IF NOT FOUND THEN RAISE EXCEPTION 'job not retryable'; END IF;
    PERFORM public._audit('retry','job_queue',p_job::text,'{}'::jsonb);
END $$;

-- cancel: pending 은 즉시, running 은 상태만 바꾼다 → 워커의 다음 lease 갱신이
-- 0행이 되어 ~갱신주기(≤TTL/4) 안에 서브프로세스가 중단된다(펜싱의 부수효과, §6-3)
CREATE OR REPLACE FUNCTION public.cancel_job(p_job uuid, p_note text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    UPDATE public.job_queue
       SET status='cancelled', lease_expires_at=NULL,
           error=coalesce(p_note,'cancelled from dashboard'),
           updated_at=now()
     WHERE id = p_job AND status IN ('pending','running','blocked');
    IF NOT FOUND THEN RAISE EXCEPTION 'job not cancellable'; END IF;
    PERFORM public._audit('cancel','job_queue',p_job::text,
                          jsonb_build_object('note',p_note));
END $$;

-- ── set_node_status (drain / active / disabled) ─────────────────────
CREATE OR REPLACE FUNCTION public.set_node_status(p_node text, p_status text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    IF p_status NOT IN ('active','draining','disabled') THEN
        RAISE EXCEPTION 'invalid status %', p_status; END IF;
    UPDATE public.node_registry SET status=p_status WHERE node_id=p_node;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown node %', p_node; END IF;
    PERFORM public._audit('set_node_status','node_registry',p_node,
                          jsonb_build_object('status',p_status));
END $$;

-- ── pin_engine / unpin_engine (런북 부록C — 악성 커밋 롤백 핀) ───────
CREATE OR REPLACE FUNCTION public.pin_engine(p_engine text, p_sha text, p_note text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    UPDATE public.deployments
       SET auto_update=false, pinned_sha=p_sha, updated_at=now()
     WHERE engine=p_engine;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown engine %', p_engine; END IF;
    PERFORM public._audit('pin_engine','deployments',p_engine,
                          jsonb_build_object('sha',p_sha,'note',p_note));
END $$;

CREATE OR REPLACE FUNCTION public.unpin_engine(p_engine text)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    UPDATE public.deployments
       SET auto_update=true, pinned_sha=NULL, updated_at=now()
     WHERE engine=p_engine;
    PERFORM public._audit('unpin_engine','deployments',p_engine,'{}'::jsonb);
END $$;

-- ── 권한: RPC 는 authenticated 만, 직접 테이블 쓰기는 원천 부재 ──────
DO $$
DECLARE fn text;
BEGIN
  FOREACH fn IN ARRAY ARRAY['approve_and_publish(uuid,text,timestamptz,text)',
                            'reject_review(uuid,text)','retry_job(uuid)',
                            'cancel_job(uuid,text)','set_node_status(text,text)',
                            'pin_engine(text,text,text)','unpin_engine(text)'] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION public.%s FROM public', fn);
    EXECUTE format('GRANT EXECUTE ON FUNCTION public.%s TO authenticated', fn);
  END LOOP;
END $$;
