-- =====================================================================
-- 0010_source_rotation.sql — 소스 회차 순환 관리 (사용자 결정 2026-08-07:
--   회차당 3회 사용 후 다음 회차 · 전 회차 소진 시 알림+대기 · 등록은 스크립트)
-- 1회 사용 = 취소/실패 아닌 work_order 1건 (= 쇼츠 1개 시도)
-- =====================================================================
ALTER TABLE public.sources ADD COLUMN IF NOT EXISTS use_limit int NOT NULL DEFAULT 3;
ALTER TABLE public.sources ADD COLUMN IF NOT EXISTS is_active boolean NOT NULL DEFAULT true;

-- 사용 횟수 정본 집계 — 별도 카운터를 두지 않고 work_orders 에서 센다(감사 가능·이중장부 방지).
-- security_invoker: 조회자 권한으로 RLS 적용 (authenticated read_all 경유, anon 차단 유지)
CREATE OR REPLACE VIEW public.source_usage
WITH (security_invoker = true) AS
SELECT s.id AS source_id, s.work_title, s.episode, s.use_limit, s.is_active,
       s.bytes, s.has_subtitle,
       COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')) AS times_used,
       GREATEST(s.use_limit - COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')), 0) AS remaining
FROM public.sources s
LEFT JOIN public.work_orders w
  ON w.work_title = s.work_title AND w.episode IS NOT DISTINCT FROM s.episode
GROUP BY s.id;

GRANT SELECT ON public.source_usage TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0010','claude-cloud (0010_source_rotation.sql 회차 순환)')
ON CONFLICT DO NOTHING;
