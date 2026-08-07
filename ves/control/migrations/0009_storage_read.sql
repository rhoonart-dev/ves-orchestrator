-- =====================================================================
-- 0009_storage_read.sql — 대시보드 프리뷰 재생 (사용자 승인 2026-08-06, DB 적용 완료)
-- authenticated 만 ves-outputs/ves-localized 객체 읽기(서명URL 발급) 가능.
-- 버킷은 여전히 private — anon 은 목록/서명 불가. ves-sources 는 대상 외(마스터 소스 보호).
-- =====================================================================
DROP POLICY IF EXISTS ves_auth_read_outputs ON storage.objects;
CREATE POLICY ves_auth_read_outputs ON storage.objects
  FOR SELECT TO authenticated
  USING (bucket_id IN ('ves-outputs','ves-localized'));
INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0009','claude-cloud (0009_storage_read.sql 대시보드 프리뷰)')
ON CONFLICT DO NOTHING;
