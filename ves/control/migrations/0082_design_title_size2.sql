-- ─────────────────────────────────────────────────────────────────────────────
-- 0082_design_title_size2.sql — 제목 2줄 크기 단독 지정(title_size2) design 키
--
-- 편집실에서 제목 크기를 1줄·2줄 **따로** 바꾸고 싶다는 사용자 요청(2026-08-24).
-- 종전 --design-title-size 는 1줄 기준 값으로 [70,90] 위계를 유지한 채 두 줄을 함께
-- 스케일했다(F-409). 새 --design-title-size2 는 그 스케일을 덮고 2줄만 그 크기로
-- 그린다 — 줄별 색(title_color2)·배경 박스(title_box2)와 같은 '지정한 줄만 치환' 조립.
--
-- 4층 중 넷째(0065 교훈): ① 대시보드 UI ② 관제 어댑터 CHANNEL_DESIGN_FLAGS
-- ③ brain channel_registry 미러 ④ **이 파일(set_channel_design v_allowed)**.
-- 본문은 적용 시점 라이브 정의(pg_get_functiondef, 2026-08-24 확인) 베이스 + v_allowed 델타.
--
-- 적용 순서: **엔진(ai-video) + 어댑터 + brain 미러 전 노드 배포 확인 → DB 적용 →
-- ops_config editor_title_size2 = on**. 이 파일은 게이트를 off 로 만들어 두므로 언제
-- 적용해도 안전하다 — 편집실은 게이트 전엔 이 키를 화면에도 안 띄우고 전송도 안 한다.
-- 채널 템플릿(채널 모달)에서 저장하는 것은 v_allowed 가 열리는 이 시점부터 가능해지며,
-- 구 엔진 노드가 남아 있으면 그 노드 생성이 argparse 로 죽는다(운영자 판단, 0069 와 동일).
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
        -- 0076: E15 스타일 구성(true → --style-compose). 스토리 구성 뒤 AI 연출 단계.
        -- 불리언 스위치라 값 검증은 어댑터 _switch_value 가 한다(subtitles·title_bold 와 같은 규율).
        'style_compose',
        -- 0082: 제목 2줄 크기 단독 지정(px → --design-title-size2). 미지정이면 종전대로
        -- title_size × 90/70. 숫자 검증은 엔진 argparse(type=int) — title_size 와 같은 규율.
        'title_size2'];
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
    -- 0076: 스타일 구성은 불리언 스위치다. 문자열 "true" 가 들어오면 어댑터는 관용하지만
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

-- 편집실 게이트 — 엔진·어댑터·brain 전 노드 배포 확인 후 운영자가 'on' 으로 바꾼다.
INSERT INTO public.ops_config(key, value, note)
VALUES ('editor_title_size2', 'off',
        '편집실 제목 줄별 크기(title_size2) — 엔진 --design-title-size2 2026-08-24 + 어댑터 신 키 전 노드 배포 후 on')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0082','claude (design 허용 키 title_size2 + editor_title_size2 게이트)');
