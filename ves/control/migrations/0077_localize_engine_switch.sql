-- =====================================================================
-- 0077_localize_engine_switch.sql — 현지화 엔진 컷오버 스위치 (L-P2, 2026-08-23)
--
-- 발주서: docs/LOCALIZE_UNIFY.md §9 P2 · 근거: docs/prompts/e15-p1-report.md.
-- rerender 현지화(혜미리예채파)가 video-localization-project 에서 ai-video
-- `app/localize/` 로 이관됐다(P1). 실런 회귀 0 확인 — mm-05 혜미리예채파_7e42b761:
-- 길이 Δ0.000s · 샘플 프레임 12/12 일치 · 자막·메타 전부 동일.
--
-- 두 엔진이 **같은 산출 규약**을 지키므로(localize_<locale>/metadata.json 성공 마커 ·
-- shorts.mp4 교체본 · localize_backup_ko/) 어댑터의 argv·cwd 만 갈린다 —
-- 검수함·편집실·0066 편집 재렌더 체인은 **무변경**이다.
--
-- 값 규약 (ves/adapters/localize.py pick_engine):
--   'vlp'       구 경로(기본) — 이 마이그레이션은 여기서 시작한다
--   'ai-video'  새 경로
--   {"_default":"vlp","SHOTCONE":"ai-video"}   채널별 JSON 맵(점진 전환)
-- 모르는 값·깨진 JSON 은 기본(vlp)으로 떨어진다 — 오타가 검증 안 된 엔진을 켜면 안 된다.
--
-- 잡마다 읽으므로 **워커 재시작이 필요 없다**(gemini_key 와 같은 규약).
-- 되돌리기: UPDATE ops_config SET value='vlp' WHERE key='localize_engine';
-- =====================================================================

INSERT INTO public.ops_config(key, value, note)
VALUES ('localize_engine', 'vlp',
        'rerender 현지화 엔진: vlp | ai-video | {"_default":…,"<슬러그>":…} — '
        'L-P2 컷오버 스위치. 다음 잡부터 적용(워커 재시작 불필요)')
ON CONFLICT (key) DO NOTHING;   -- 이미 전환했다면 덮지 않는다

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0077','claude (0077 현지화 엔진 컷오버 스위치 — L-P2)')
ON CONFLICT DO NOTHING;
