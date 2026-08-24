-- ─────────────────────────────────────────────────────────────────────────────
-- 0081_channel_subtitle_avoid_burned.sql — 채널 'design' 허용 키에 'subtitle_avoid_burned'
--
-- 사용자 요청(2026-08-24): "영상에 원래 자막이 있으면 그 위치 피해서 자막이 들어가게
-- 해줘. 물론, 자막이 제목과도 겹치면 안되고." → 엔진 E17-2. 렌더 앞에서 영상 밴드
-- 아래쪽을 재서 **소스에 이미 박힌 원본 자막 띠**를 찾고, 우리 대사 자막을 그 위로
-- 올린다(상한은 제목 블록 아래 — 제목과도 안 겹친다). 못 찾으면 아무것도 안 바뀐다.
--
-- ⚠ **엔진 기본이 켜짐('auto')이다.** 다른 design 키와 반대로, 이 키는 **끄는 쪽만**
--   의미가 있다: 사람이 실렌더 픽셀로 맞춰 승인된 채널이 자막 위치를 그대로 지키려면
--   'off' 를 저장한다. 키를 안 넣은 채널은 회피가 도는 것이 정상이다.
--
-- **왜 채널 단위인가**: 자막 위치는 채널 정체성(템플릿)이고, 회피 판정은 렌더 단계라
--   편집실 재렌더(from_step=resources|render)에서도 같은 체크포인트를 다시 쓴다.
--   transcribe_backend(0072)·style_compose(0076)와 같은 자리·같은 성격이다.
--
-- 계약: subtitle_avoid_burned = 'auto' | 'off' → 엔진 --design-subtitle-avoid-burned.
-- 값 검증 정본은 엔진(argparse choices), 어댑터 _subtitle_avoid_value 가 그 앞에서 한 번,
-- 여기(RPC)가 셋째 층이다 — 오타가 조용히 지나가면 'off' 를 쓴 줄 아는 채널의 자막이
-- 움직인다(0072 와 같은 규율로 값까지 본다).
--
-- 본문은 적용 시점 라이브 정의(0076 판) 베이스 + v_allowed 한 항목 델타
-- (0065·0069·0072·0076 전례). 0077~0080 은 set_channel_design 을 건드리지 않는다.
-- ⚠ 적용 직전 `SELECT max(version) FROM applied_migrations WHERE engine='orchestrator'`
--   로 번호가 이 파일의 -1 인지 확인할 것(0074 머리말 규칙).
--
-- 적용 순서: **엔진(ai-video --design-subtitle-avoid-burned) 전 노드 배포 확인 →
-- DB 적용 → ops_config channel_subtitle_avoid = on**. 게이트가 off 인 동안은 화면에
-- 선택칸이 뜨지 않고 어댑터도 키를 걷어낸다(구 엔진 노드가 모르는 플래그에 즉사하는 것을
-- 막는다 — E7·E10·E11·E15 와 같은 롤아웃). 게이트가 off 여도 **회피 자체는 엔진 기본으로
-- 돈다** — 이 게이트가 여는 것은 '끌 수 있는 권한'이다.
-- 짝: ves/adapters/aivideo.py(CHANNEL_DESIGN_FLAGS.subtitle_avoid_burned·
--     SUBTITLE_AVOID_MODES) · 대시보드 채널 설정 모달(df_subtitle_avoid_burned) ·
--     docs/prompts/e17-subtitle-avoid-burned.md
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
        -- 0081: E17-2 원본 자막 회피('auto'|'off' → --design-subtitle-avoid-burned).
        -- 엔진 기본이 'auto'(켜짐)라 이 키는 **끄는 쪽만** 의미가 있다.
        'subtitle_avoid_burned'];
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
    -- 원본 자막 회피도 값을 본다 — 오타가 조용히 지나가면 'off' 를 쓴 줄 아는 채널의
    -- 자막이 회피로 움직인다(사람이 픽셀로 맞춘 위치가 승인 산출이다).
    IF p_design ? 'subtitle_avoid_burned'
       AND coalesce(p_design->>'subtitle_avoid_burned','') NOT IN ('auto','off') THEN
        RAISE EXCEPTION 'subtitle_avoid_burned 는 auto/off 중 하나입니다: %',
            p_design->>'subtitle_avoid_burned';
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

-- 채널 설정 게이트 — 엔진(--design-subtitle-avoid-burned) 전 노드 배포 확인 후
-- 운영자가 'on' 으로 바꾼다. off 인 동안 채널 모달에 선택칸이 뜨지 않는다.
-- (회피 자체는 엔진 기본으로 돈다 — 이 게이트가 여는 것은 채널별로 **끌 수 있는 권한**이다.)
INSERT INTO public.ops_config(key, value, note)
VALUES ('channel_subtitle_avoid', 'off',
        'E17-2 원본 자막 회피 채널 설정(subtitle_avoid_burned: auto|off) — 엔진 기본은 auto(켜짐). 이 게이트는 채널별로 끄는 통로를 연다. 엔진 --design-subtitle-avoid-burned 전 노드 배포 후 on')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0081','claude (design 허용 키 subtitle_avoid_burned — E17-2 원본 자막 회피, channel_subtitle_avoid 게이트)')
ON CONFLICT DO NOTHING;
