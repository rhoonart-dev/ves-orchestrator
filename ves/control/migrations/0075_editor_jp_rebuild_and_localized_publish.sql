-- =====================================================================
-- 0075_editor_jp_rebuild_and_localized_publish.sql (2026-08-23)
--   ① 편집실 재렌더가 일본어판까지 살아오게 — localize 잡에 rebuild 신호
--   ② 발행이 현지화판 제목·설명·해시태그를 쓰게 — publish 잡에 그 값들
--
-- ⚠ 번호 발번: 적용 직전 `SELECT max(version) FROM applied_migrations WHERE engine='orchestrator'`
--    로 확인하고 그 +1 로 파일명과 아래 INSERT 를 맞춘다(0074 머리말의 사고 참고).
--
-- ── 실사고 ①: 편집실이 일본어판에 아무 영향도 못 준다 ─────────────────────
-- 2026-08-23 SHOTCONE(혜미리예채파_7e42b761, review 18ef14f1) 실측. 원본(한국어)
-- 편집실에서 화면비 13:9 와 대사 자막 18줄을 고쳐 재렌더 체인을 돌렸다. 체인은 전부
-- succeeded 인데 새 검수 카드(210d3037)의 ko_ja_pairs 가 직전 카드와 **바이트 단위로
-- 동일**했다. localize 는 13초 만에 끝났다(최초 실행은 512초).
--
-- 원인은 vlp scripts/localize_run.py 세 곳:
--   · l0_backup 이 `if not backup.exists()` 라 한국어 백업이 최초 생성본에 영구 고정
--   · l1_translate 가 translation.json 이 있으면 무조건 재사용
--   · l4_render 가 일본어 폰트 두 개만 넘겨 나머지 --design-* 를 통째로 상실
--     (채널 템플릿 aspect_ratio 13:9 조차 일본어판에 반영된 적이 없다 — 엔진 기본 1:1)
-- 엔진 쪽 수정은 짝 커밋으로 끝났다(vlp --rebuild · design 복원, ai-video run_log.design_cli).
-- 여기서는 **그 rebuild 를 켜는 신호**만 잡 params 에 싣는다. planner 정상 체인은 첫
-- 현지화라 무효화할 캐시가 없으므로 이 키를 넣지 않는다 — 재번역(Gemini Pro 호출 +
-- 텔롭 재추출)은 싸지 않다.
--
-- ── 실사고 ②: 일본어 채널에 한국어 제목·설명이 발행된다 ────────────────────
-- 같은 clip(606a7e5c)의 clip_metadata.publish_snippet, 2026-08-23T14:58 발행분:
--   title       '몸만 오면 된다더니 문 열자마자 멘붕 온 이유'
--   description 'ヘミリイェチェパ 1화\n채널 ENA에서 시청 가능\nチャンネルENAで視聴可能\n\n#혜미리예채파 #46ckt'
--   tags        ['혜미리예채파']
-- 현지화가 localize_ja/metadata.json 에 올바른 일본어 제목·설명·해시태그를 만들고
-- localize 어댑터가 그것을 검수 카드 payload 에 담아 두는데, **발행까지 옮기는 배선이
-- 없었다**. publish 잡 params 는 clip_id·channel·run_id·episode·privacy 뿐이라
-- brain publish_youtube.py 가 clip_metadata 의 한국어 top_title 로 제목을 만들고
-- 한국어 작품명으로 해시태그를 조립했다. JP 체인은 ingest/evaluate 가 localize 보다
-- **앞**이라 clip_metadata 에는 언제나 한국어가 담긴다 — 순서를 바꾸지 않는 한 이 경로는
-- 구조적으로 한국어를 발행한다.
--
-- ── 이 마이그레이션이 하는 일 ─────────────────────────────────────────────
--  ① _localized_publish_meta(payload) 신설 — 검수 카드 payload → publish 잡 params 조각.
--  ② approve_and_publish 의 publish 잡 params 에 그 조각을 병합(라이브 정의 + 델타).
--  ③ submit_editor_render 의 JP localize 잡 params 에 'rebuild', true 추가(같은 방식).
--
-- ⚠ ②③ 을 **전문 재정의 대신 라이브 정의 텍스트 패치**로 하는 이유: 두 함수는 각각
--    110·370 줄이고 델타는 한 줄씩이다. 손으로 옮겨 적으면 오타 하나가 조용히 운영
--    동작을 바꾼다(0065·0069 가 v_allowed 한 항목을 빠뜨려 저장이 거부됐던 것과 같은
--    급의 위험). 그래서 pg_get_functiondef 를 베이스로 **정확히 그 조각만** 치환하고,
--    조각을 못 찾으면 즉시 실패시킨다. 재적용(이미 패치됨)은 조용히 건너뛴다.
-- =====================================================================

BEGIN;

-- ① 검수 카드 payload → 발행 잡 params 조각. 값이 없으면 빈 객체 = 종전과 동일(한국어
--    채널 회귀 0). brain 은 publish_title/description 이 없으면 종전대로 조립한다.
CREATE OR REPLACE FUNCTION public._localized_publish_meta(p_payload jsonb)
RETURNS jsonb
LANGUAGE sql
IMMUTABLE
AS $fn$
    SELECT coalesce(jsonb_strip_nulls(jsonb_build_object(
        'publish_title',
            nullif(btrim(coalesce(p_payload->>'youtube_title', '')), ''),
        'publish_description',
            nullif(btrim(coalesce(p_payload->>'description', '')), ''),
        'publish_tags',
            CASE WHEN jsonb_typeof(p_payload->'tags') = 'array'
                  AND jsonb_array_length(p_payload->'tags') > 0
                 THEN p_payload->'tags' END
    )), '{}'::jsonb);
$fn$;

COMMENT ON FUNCTION public._localized_publish_meta(jsonb) IS
    '현지화 검수 카드(localization_qa) payload → publish 잡 params 조각(0075). '
    '값이 없으면 {} — 한국어 카드는 종전 경로 그대로.';

-- ② approve_and_publish — publish 잡 params 에 현지화 메타 병합
DO $patch$
DECLARE v_def text; v_new text;
BEGIN
    v_def := pg_get_functiondef(
        'public.approve_and_publish(uuid,text,timestamptz,text)'::regprocedure);
    IF position('_localized_publish_meta' in v_def) > 0 THEN
        RAISE NOTICE '0075 ②: approve_and_publish 는 이미 패치돼 있습니다 — 건너뜁니다';
        RETURN;
    END IF;
    v_new := replace(
        v_def,
        '''privacy'', p_privacy, ''publish_at'', p_publish_at)',
        '''privacy'', p_privacy, ''publish_at'', p_publish_at)'
        || E'\n            || public._localized_publish_meta(v_rq.payload)');
    IF v_new = v_def THEN
        RAISE EXCEPTION '0075 ②: approve_and_publish 의 publish params 조각을 못 찾았습니다 '
                        '— 라이브 정의가 바뀌었습니다. 손으로 확인하고 이 파일을 고치세요';
    END IF;
    EXECUTE v_new;
END $patch$;

-- ③ submit_editor_render — JP 편집 재렌더의 localize 잡에 rebuild 신호
DO $patch$
DECLARE v_def text; v_new text;
BEGIN
    v_def := pg_get_functiondef(
        'public.submit_editor_render(uuid,jsonb,text)'::regprocedure);
    IF position('''rebuild''' in v_def) > 0 THEN
        RAISE NOTICE '0075 ③: submit_editor_render 는 이미 패치돼 있습니다 — 건너뜁니다';
        RETURN;
    END IF;
    -- 들여쓰기에 의존하지 않게 공백은 \s+ 로 받는다(정렬은 함수 서명 길이에 따라 흔들린다)
    v_new := regexp_replace(
        v_def,
        'jsonb_build_object\(''mode'', ''scene_rerender'',(\s*)''review_id''',
        'jsonb_build_object(''mode'', ''scene_rerender'', ''rebuild'', true,\1''review_id''');
    IF v_new = v_def THEN
        RAISE EXCEPTION '0075 ③: submit_editor_render 의 JP localize 잡 생성부를 못 찾았습니다 '
                        '— 라이브 정의가 바뀌었습니다. 손으로 확인하고 이 파일을 고치세요';
    END IF;
    EXECUTE v_new;
END $patch$;

-- 적용 검증 — 조용한 무패치를 막는다(EXECUTE 가 돌았는데 텍스트가 안 바뀌는 경우는 없지만,
-- 위 RETURN 분기를 잘못 타면 아무 일도 안 하고 초록불이 난다)
DO $verify$
BEGIN
    IF position('_localized_publish_meta' in pg_get_functiondef(
           'public.approve_and_publish(uuid,text,timestamptz,text)'::regprocedure)) = 0 THEN
        RAISE EXCEPTION '0075 검증 실패: approve_and_publish 에 현지화 메타 병합이 없습니다';
    END IF;
    IF position('''rebuild''' in pg_get_functiondef(
           'public.submit_editor_render(uuid,jsonb,text)'::regprocedure)) = 0 THEN
        RAISE EXCEPTION '0075 검증 실패: submit_editor_render 에 rebuild 신호가 없습니다';
    END IF;
END $verify$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0075','claude (편집실 JP 재렌더 rebuild 신호 + 현지화판 제목·설명·해시태그 발행 — SHOTCONE 8/23)')
ON CONFLICT DO NOTHING;

COMMIT;
