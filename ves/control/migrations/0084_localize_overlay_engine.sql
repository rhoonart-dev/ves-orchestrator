-- =====================================================================
-- 0084_localize_overlay_engine.sql — overlay 컷오버 스위치 (L-P4, 2026-08-25)
--
-- rerender 는 0077(localize_engine)로 이미 컷오버됐다. overlay(잔망루피 쇼츠)를 위한
-- **별도 스위치**다.
--
-- 🛑 왜 별도인가: `localize_engine` 은 이미 'ai-video' 다. 같은 값을 공유하면 P4 코드가
--    배포되는 순간 overlay 까지 함께 넘어간다 — "켜는 것은 사람"이라는 P2 규율을 깬다.
--
-- ⚠ **지금 켜면 잡이 실패한다(그것이 의도다).** ai-video venv 에 overlay 런타임 의존
--    (OCR·인페인트·더빙 백엔드)이 없다. 어댑터가 **비싼 단계 앞에서** 사전검사로 막고
--    무엇이 없는지 이름으로 알린다 — 지연 임포트라 안 막으면 소스를 내려받고 프레임을
--    뽑은 뒤 detect 에서 터진다(2026-08-25 실측).
--    켜기 전에: ai-video requirements 에 의존을 넣고 6대 배포를 확인한다(계획 §10-1 결정 1).
-- =====================================================================

INSERT INTO public.ops_config(key, value, note) VALUES
 ('localize_overlay_engine', 'vlp',
  'overlay 현지화 엔진(잔망루피 쇼츠): vlp | ai-video | {"_default":…,"<슬러그>":…} — '
  'L-P4 컷오버 스위치. rerender 의 localize_engine 과 **별개**다. 다음 잡부터 적용. '
  '⚠ ai-video 로 켜기 전에 그 venv 에 OCR·인페인트·더빙 의존이 있어야 한다 '
  '(없으면 어댑터 사전검사가 잡을 즉시 실패시킨다 — 무엇이 없는지 메시지에 나온다). '
  '등급 J(convert_short)는 이 스위치와 무관하게 항상 vlp 다(이식 안 함)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0084','claude (0084 overlay 컷오버 스위치 — L-P4)')
ON CONFLICT DO NOTHING;
