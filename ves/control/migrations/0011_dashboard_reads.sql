-- =====================================================================
-- 0011_dashboard_reads.sql — 관제 v2 읽기 정책 (사용자 승인 2026-08-07, DB 적용 완료)
-- clips·clip_metadata·judge_runs: authenticated 읽기 (judge 표시·발행 링크·회차)
-- dashboard_daily_snapshots: RLS 잠금 + authenticated 읽기 (기존: RLS 없이 노출돼 있었음)
-- 워커·brain 스크립트는 직결 계정이라 무영향. anon 은 전부 차단 유지.
-- =====================================================================
DO $$ DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['clips','clip_metadata','judge_runs'] LOOP
    EXECUTE format('DROP POLICY IF EXISTS ves_dash_read ON public.%I', t);
    EXECUTE format(
      'CREATE POLICY ves_dash_read ON public.%I FOR SELECT TO authenticated USING (true)', t);
  END LOOP;
END $$;
ALTER TABLE public.dashboard_daily_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ves_dash_read ON public.dashboard_daily_snapshots;
CREATE POLICY ves_dash_read ON public.dashboard_daily_snapshots
  FOR SELECT TO authenticated USING (true);
INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0011','claude-cloud (0011 관제 v2 읽기 정책·스냅샷 RLS)')
ON CONFLICT DO NOTHING;
