-- 0052: 채널 템플릿에 플랫폼 표기 + 영상 세로 위치 키 허용 (2026-08-19)
-- ai-video 에 영상영역 왼쪽 상단 로고/텍스트(--design-platform-*)와 영상 세로 위치
-- (--design-video-y, 위로 올려 하단 밴드 확보)가 생겼다 — 권리사
-- '영상 내 플랫폼 노출' 요구(가왕쇼 티빙, 약한영웅 Wavve 로고 등)용. set_channel_design 의
-- 화이트리스트에 새 키를 추가한다. 함수 본문 전체 재정의(0014 원본과 v_allowed 만 다름).
-- ※0050 번호로 만들었다가 같은 날 editor 마이그레이션(0050·0051)과 충돌해 0052 로 옮김.

CREATE OR REPLACE FUNCTION public.set_channel_design(p_slug text, p_design jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
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
        'platform_font_size','platform_color','platform_align'];
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
END $$;
REVOKE ALL ON FUNCTION public.set_channel_design(text, jsonb) FROM public;
GRANT EXECUTE ON FUNCTION public.set_channel_design(text, jsonb) TO authenticated;
