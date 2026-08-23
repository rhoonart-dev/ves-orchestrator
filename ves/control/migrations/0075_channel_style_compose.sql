-- ─────────────────────────────────────────────────────────────────────────────
-- 0075_channel_style_compose.sql — 채널 'design' 허용 키에 'style_compose'
--
-- 사용자 요청(2026-08-23): "스토리 구성을 하고 나서 여러가지 영상의 요소들을 멋지게
-- 구성하는 단계를 추가" — E15 스타일 구성 단계(기획서 docs/prompts/e15-style-compose.md).
-- 엔진이 스토리 구성 뒤(silence_cut 뒤 · resources 앞) AI 로 편 단위 연출 플랜을 만들고
-- 그대로 렌더한다: 효과 텍스트(texts)·자막 강조·스티커·타임드 제목·회전/배속·TTS 톤.
-- 어휘는 전부 edit_overrides/v3 + design 키 재사용이라 편집실·재렌더 경로가 그대로다.
--
-- **왜 채널 단위인가(편집실이 아니라)**: style 은 silence_cut 뒤 단계이고 편집실
-- 재렌더는 from_step=resources|render 로 재개한다 — 그 편에서 켜도 다시 돌지 않는다
-- (체크포인트를 그대로 재적용한다). transcribe_backend(0072)와 같은 자리·같은 성격이다.
-- 사람이 결과를 고치는 통로는 편집실이고, 편집실이 보낸 카테고리는 AI 항목을 전량 이긴다
-- (우선순위: 편집실 > 채널 명시 플래그 > AI 플랜 > 기본값 — 엔진이 강제).
--
-- 계약: style_compose = true → 엔진 --style-compose (불리언 스위치, 값 없는 플래그).
-- 미지정 = 단계 자체가 없다(엔진 회귀 0 — 체크포인트를 쓰지도 읽지도 않는다).
-- 값 검증 정본은 어댑터 _switch_value(불리언만) 이고, 여기(RPC)는 **키** 화이트리스트다.
--
-- 본문은 적용 시점 라이브 정의(0072 판) 베이스 + v_allowed 한 항목 델타(0065·0069·0072 전례).
--
-- 적용 순서: **엔진(ai-video --style-compose) + brain 미러 전 노드 배포 확인 →
-- DB 적용 → ops_config channel_style = on**. 이 파일은 게이트를 off 로 만들어 두므로
-- 언제 적용해도 안전하다 — 화면에 선택칸이 뜨지 않아 저장될 일이 없고, 구 엔진 노드는
-- 모르는 CLI 플래그에 argparse 로 즉사한다(E7·E10·E11 과 같은 롤아웃).
-- ⚠ JP(현지화) 채널은 켜지 않는다 — 한국어로 번인된 연출 텍스트를 vlp 가 지울 수 없다
--   (기획서 §9-1). 개방은 KR 채널 파일럿 1곳부터.
-- 짝: ves/adapters/aivideo.py(CHANNEL_DESIGN_SWITCHES.style_compose) ·
--     대시보드 채널 설정 모달(df_style_compose) · docs/prompts/e15-style-compose.md
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.set_channel_design(p_slug text, p_design jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_role text;
    v_key  text;
    v_allowed text[] := ARRAY[
        'title_y','title_font','title_size','title_color','title_color2',
        'subtitle_font','subtitle_size','subtitle_color','subtitle_y_margin',
        'subtitle_style','tts_color','tts_size','tts_y_margin',
        'work_title_y','work_font_size','work_color','aspect_ratio','face_tracking',
        -- 0052: 영상 세로 위치 + 플랫폼 표기(영상영역 왼쪽 상단 로고/텍스트)
        'video_y',
        'platform_image','platform_text','platform_x','platform_y',
        'platform_image_width','platform_image_height',
        'platform_font_size','platform_color','platform_align',
        -- 0065: 대사 자막 끔 스위치(false → --no-subtitles, 편집실 자막 예외 우선)
        'subtitles',
        -- 0069: 제목 줄별 배경 박스(none·round·rect)·배경색·굵게(true) + 제목 Y 고정(F-409)
        'title_box','title_box2','title_box_color','title_box_color2',
        'title_bold','title_bold2','title_y_fixed',
        -- 0069: E10 영상 밴드 가로 폭(ai-video d195cb9 · 어댑터 fcf5233 · brain 미러 804a9f4 동반)
        'video_width',
        -- 0072: E11 자막 전사 백엔드('default'|'elevenlabs' → --transcribe-backend).
        -- 값 검증은 어댑터·엔진 — 여기는 키만 본다(다른 키와 같은 규율).
        'transcribe_backend',
        -- 0075: E15 스타일 구성(true → --style-compose). 스토리 구성 뒤 AI 연출 단계.
        -- 불리언 스위치라 값 검증은 어댑터 _switch_value 가 한다(subtitles·title_bold 와 같은 규율).
        'style_compose'];
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN
        RAISE EXCEPTION '없는 채널: %', p_slug;
    END IF;
    IF p_design IS NULL OR p_design = 'null'::jsonb THEN
        DELETE FROM public.channel_design_overrides WHERE token_slug = p_slug;
        RETURN jsonb_build_object('slug', p_slug, 'cleared', true);
    END IF;
    IF jsonb_typeof(p_design) <> 'object' THEN
        RAISE EXCEPTION 'design 은 JSON 객체여야 합니다';
    END IF;
    -- 전사 백엔드만은 값도 여기서 본다 — 다른 design 키와 달리 이 값은 **돈이 나가는
    -- 외부 API 선택**이라(일레븐랩스 Scribe 는 초 단위 과금) 오타가 조용히 지나가면
    -- 안 된다. 화면은 select 라 오타가 안 나지만 채널 템플릿은 손으로도 고친다.
    IF p_design ? 'transcribe_backend'
       AND coalesce(p_design->>'transcribe_backend','') NOT IN ('default','elevenlabs') THEN
        RAISE EXCEPTION 'transcribe_backend 는 default/elevenlabs 중 하나입니다: %',
            p_design->>'transcribe_backend';
    END IF;
    -- 0075: 스타일 구성은 불리언 스위치다. 문자열 "true" 가 들어오면 어댑터는 관용하지만
    -- (손 편집 템플릿 대비) 화면 저장 경로는 JSON 불리언으로만 보낸다 — 숫자·임의 문자열이
    -- 조용히 '켜짐'으로 해석되지 않도록 여기서 한 번 더 막는다(AI 호출 = 돈이 나간다).
    IF p_design ? 'style_compose'
       AND jsonb_typeof(p_design->'style_compose') NOT IN ('boolean') THEN
        RAISE EXCEPTION 'style_compose 는 true/false 여야 합니다: %',
            p_design->>'style_compose';
    END IF;
    FOR v_key IN SELECT jsonb_object_keys(p_design) LOOP
        IF left(v_key, 1) <> '_' AND NOT (v_key = ANY (v_allowed)) THEN
            RAISE EXCEPTION '알 수 없는 design 키: % (허용: %)', v_key, array_to_string(v_allowed, ', ');
        END IF;
    END LOOP;
    INSERT INTO public.channel_design_overrides (token_slug, design, updated_by, updated_at)
    VALUES (p_slug, p_design, coalesce(auth.email(), auth.uid()::text), now())
    ON CONFLICT (token_slug) DO UPDATE SET
        design = EXCLUDED.design, updated_by = EXCLUDED.updated_by, updated_at = now();
    RETURN jsonb_build_object('slug', p_slug, 'saved', true);
END $function$;

-- 채널 설정 게이트 — 엔진(--style-compose)·어댑터·brain 전 노드 배포 확인 후
-- 운영자가 'on' 으로 바꾼다. off 인 동안 채널 모달에 선택칸이 뜨지 않는다.
INSERT INTO public.ops_config(key, value, note)
VALUES ('channel_style', 'off',
        'E15 스타일 구성(style_compose: true|false) — 스토리 구성 뒤 AI 연출 단계. 엔진 --style-compose 전 노드 배포 후 on. JP 채널은 켜지 않는다(연출 텍스트가 한국어로 번인된다)')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0075','claude (design 허용 키 style_compose — E15 스타일 구성 단계, channel_style 게이트)')
ON CONFLICT DO NOTHING;
