-- 0008_rpc_grants_fix.sql — advisor 지적 반영 (2026-08-06 fdidiqd 적용됨)
-- Supabase 는 함수에 anon/authenticated EXECUTE 를 기본 부여 — REVOKE FROM public 으로는
-- 직접 grant 가 안 걷힌다. anon 차단 + _audit 은 내부 전용(외부 호출 전면 차단).

DO $$
DECLARE fn text;
BEGIN
  FOREACH fn IN ARRAY ARRAY['approve_and_publish(uuid,text,timestamptz,text)',
                            'reject_review(uuid,text)','retry_job(uuid)',
                            'cancel_job(uuid,text)','set_node_status(text,text)',
                            'pin_engine(text,text,text)','unpin_engine(text)',
                            'has_role(uuid,text)'] LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION public.%s FROM anon', fn);
  END LOOP;
END $$;

-- _audit: 다른 definer 함수 내부에서만 호출(owner 권한으로 실행) — 외부 노출 불필요
REVOKE EXECUTE ON FUNCTION public._audit(text,text,text,jsonb) FROM anon, authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0008','claude-session')
ON CONFLICT DO NOTHING;
