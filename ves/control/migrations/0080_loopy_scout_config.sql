-- =====================================================================
-- 0080_loopy_scout_config.sql — 수집기 설정 행 (L-P3 보완, 2026-08-24)
--
-- 0078 이 아카이브 테이블을 열면서 **수집기 설정 행을 빠뜨렸다.** 코드는
-- merge_config(None) → DEFAULTS(enabled=False) 로 안전하게 꺼진 채 돌지만,
-- 행이 없으면 **사람이 켤 수단이 없다** — "켜는 것은 사람이다"가 성립하지 않는다.
-- 값은 loopy_scout.DEFAULTS 와 같아야 한다(다르면 화면과 동작이 어긋난다).
-- =====================================================================

INSERT INTO public.ops_config(key, value, note) VALUES
 ('loopy_scout',
  '{"enabled": false, "channel_slug": "LOOPY", "handle": "@zanmangloopy", "max_scan": 0, "shorts_max_sec": 61}',
  '외부 쇼츠 수집기(L-P3) — 매일 03:00 KST, 원 채널 전량 재나열(약 46 쿼터 유닛 = '
  '무료 일일 한도의 0.5%). max_scan=0 은 무제한, shorts_max_sec 이하가 쇼츠. '
  'enabled=false 면 수집하지 않는다 — YOUTUBE_API_KEY 확인 뒤 사람이 켠다')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0080','claude (0080 수집기 설정 행 — 0078 누락 보완)')
ON CONFLICT DO NOTHING;
