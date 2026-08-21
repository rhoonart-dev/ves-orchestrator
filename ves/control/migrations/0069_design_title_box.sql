-- ─────────────────────────────────────────────────────────────────────────────
-- 0069_design_title_box.sql — 제목 줄별 배경 박스·굵게 design 키 + title_y_fixed 승격
--
-- 제목 줄별 배경 박스(없음/둥근네모/각진네모)·배경색·굵게(ai-video 2026-08-21, 어댑터·brain
-- 미러 동반)의 셋째 검증 층 — 0065 교훈(어댑터·brain 은 넣고 v_allowed 를 빠뜨려 저장 거부).
-- title_y_fixed 는 편집실 '현재 스타일을 채널 템플릿으로 저장'(edDesign() 통째 스냅샷)에
-- 드래그 제목 위치가 title_y 와 함께 실리도록 채널 템플릿 키로 승격(brain 미러 동반).
-- 본문은 적용 시점 라이브 정의(pg_get_functiondef, 0065 와 동일 확인) 베이스 + v_allowed 델타.
--
-- 적용 순서: **엔진(ai-video) + brain 미러 전 노드 배포 확인 → DB 적용 → ops_config
-- editor_title_box = on**. 이 파일은 게이트를 off 로 만들어 두므로 언제 적용해도 안전하다 —
-- 채널 모달에서 박스 키를 저장하는 것은 운영자 판단(구 brain 노드가 남아 있으면 그 노드
-- 생성이 unknown-key 로 죽는다).
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
        'title_bold','title_bold2','title_y_fixed'];
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
END $function$;

-- 편집실 게이트 — 엔진·어댑터·brain 전 노드 배포 확인 후 운영자가 'on' 으로 바꾼다.
INSERT INTO public.ops_config(key, value, note)
VALUES ('editor_title_box', 'off',
        '편집실 제목 줄별 배경 박스·굵게(title_box*·title_bold*) — 엔진 2026-08-21 + 어댑터 신 키 전 노드 배포 후 on')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0069','claude (design 허용 키 title_box·bold + title_y_fixed 승격, editor_title_box 게이트)');
