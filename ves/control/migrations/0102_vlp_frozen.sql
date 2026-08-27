-- 0102 — P8: video-localization-project(vlp) 동결 (2026-08-27, 운영자 지시)
--
-- 레거시 카드 15장을 일괄 반려해 drain 0 을 확인한 뒤 켠다. 이 스위치가 켜지면
-- zanmang_decision 어댑터가 실행을 거절한다 — vlp 는 더 이상 어떤 잡도 받지 않는다.
-- 어댑터 코드는 지우지 않는다(감사 이력 재현용). 절차 정본: docs/P8_VLP_FREEZE.md.
-- 되돌리기: ops_config 에서 vlp_frozen 을 off 로 (긴급 시 사람 결정).

INSERT INTO public.ops_config(key, value)
VALUES ('vlp_frozen', 'on')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0102','claude (P8 vlp 동결 — 운영자 지시로 레거시 카드 15장 일괄 반려 후)')
ON CONFLICT DO NOTHING;
