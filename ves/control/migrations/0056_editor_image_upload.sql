-- =====================================================================
-- 0056_editor_image_upload.sql — 편집실 이미지 업로드 정책 (F-408 대시보드 파트 1)
-- 적용 순서: DB 먼저(updater 게이트 ★③ 규율) — 이 정책은 새 표면 추가라 구 코드에 무해.
--
-- 브라우저→스토리지 **쓰기 표면 최초 신설** (사용자 승인 2026-08-19).
-- 지금까지 대시보드는 스토리지 읽기 전용(0009: authenticated SELECT)이었다. 편집실
-- 이미지 오버레이(F-408)는 검수자가 파일을 올려야 성립하므로 예외를 연다 — 단 표면을
-- 최소로 좁힌다(R12 관점):
--   · reviewer 이상만 (has_role — viewer 는 불가)
--   · ves-outputs 의 editor_uploads/ prefix 한정 — 다른 버킷·경로는 종전대로 불가
--   · 확장자 png/jpg/jpeg/webp 한정 (소문자 비교 — 대문자 확장자는 클라이언트가 정규화)
--   · INSERT 만 — UPDATE/DELETE 정책은 없다 = 덮어쓰기·삭제 불가(업로드는 불변,
--     잘못 올리면 새로 올리고 옛것은 버려진다)
-- 크기 상한(5MB)은 클라이언트 검증이다 — storage RLS 의 WITH CHECK 시점에 객체
-- 크기를 신뢰성 있게 알 수 없다(metadata 는 storage-api 구현 상세). 버킷 전역
-- file_size_limit 은 렌더 산출물(수백 MB)과 공유라 조일 수 없다. 악의적 대용량은
-- reviewer 계정 신뢰 범위의 문제로 남는다 — 계정은 운영자가 발급한다(0015).
--
-- GC: editor_uploads/ 는 editor_asset_catalog 대상 밖이라 지금은 쌓인다(이미지는
-- 수십 KB~수 MB 라 비용 미미). 렌더에 쓰인 키는 라운드 승계(0053)로 다음 판에도
-- 참조될 수 있어 함부로 지우면 안 된다 — 정리 제도는 후속(발행/폐기된 run 기준).
-- 주의: prefix 의 <run_id> 세그먼트는 이 정책이 검증하지 않는다(reviewer 는 남의 run
-- 경로에도 올릴 수 있다 — 참조는 항상 명시 key 라 오늘은 무해). 후속 GC 가 prefix
-- 목록 기반이면 이 무검증을 전제로 설계할 것(위조 prefix 미수거·오삭제 함정).
--
-- 제출 경로는 아직 닫혀 있다: submit_editor_render(0054)는 images 키를 조기 거절한다
-- (엔진 렌더 미구현 fail-loud). E2(엔진 합성) 배포 후 다음 마이그레이션이 거절을
-- 풀면서 images[] 검증(prefix 포함)을 넣는다. 이 정책은 그 전에 UI 개발·업로드
-- 테스트를 가능하게 하는 선행 조각이다.
-- =====================================================================

DROP POLICY IF EXISTS ves_reviewer_upload_editor_images ON storage.objects;
CREATE POLICY ves_reviewer_upload_editor_images ON storage.objects
  FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'ves-outputs'
    AND public.has_role(auth.uid(), 'reviewer')
    AND name LIKE 'editor_uploads/%'
    AND lower(name) ~ '\.(png|jpg|jpeg|webp)$'
  );

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0056','claude (0056_editor_image_upload.sql 편집실 이미지 업로드 정책)')
ON CONFLICT DO NOTHING;
