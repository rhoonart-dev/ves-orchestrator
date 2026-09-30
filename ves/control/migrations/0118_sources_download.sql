-- 0118 — 원본 회차 받기(프리미어로 내보내기) (2026-09-30)
-- 워크스페이스 '프리미어로 내보내기'는 XML 이 가리키는 원본 회차를 사람이 받아 프리미어에 연결해야 한다.
-- 원본(ves-sources/masters/<sha>)은 지금까지 맥미니(서비스 키)만 읽었다. 운영자부터 서명 URL 을 만들 수 있게 한다(받기만, 쓰기·지우기는 그대로 막힘).
-- 처음엔 검수자부터였다가 같은 날 운영자부터로 올림 — 프리미어로 내보내기는 우리 팀만(크리에이터는 편집실).
DROP POLICY IF EXISTS ves_sources_read ON storage.objects;
CREATE POLICY ves_sources_read ON storage.objects FOR SELECT TO authenticated
 USING (bucket_id = 'ves-sources' AND public.has_role((SELECT auth.uid()), 'operator'));

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0118','claude (프리미어로 내보내기: 운영자 원본 받기)');
