-- ─────────────────────────────────────────────────────────────────────────────
-- 0105_design_band_offset.sql — v3 자막 밴드 상대 앵커 design 키 (2026-09-04)
--
-- 절대 margin(subtitle_y_margin·tts_y_margin)은 화면비·video_y 마다 손으로 다시 잡아야
-- 했다 — 가왕쇼 7화: 13:9·video_y 440 에 맞춘 tts 550 이 video_y 500 에서 두 줄 내레이션
-- 윗줄을 영상에 25px 겹치게 했다. v3 는 자막 블록 **윗변**을 '밴드 하단 + N px' 에 거는
-- 키 둘을 받는다(음수 = 밴드 안쪽). 내레이션은 cue 별 줄 수를 세어 한 줄·두 줄 모두
-- 같은 자리에 걸린다. v1 엔진엔 이 플래그가 없어 어댑터가 v1 잡에는 싣지 않는다
-- (V3_ONLY_DESIGN_KEYS — channel_design_flags 가 거른다).
--
--   subtitle_band_offset  대사 어절 자막 윗변 오프셋(px)  예: 30
--   tts_band_offset       내레이션 자막 윗변 오프셋(px)   예: 24
--
-- 4층(0065 교훈): ① 대시보드 UI ② 어댑터 CHANNEL_DESIGN_FLAGS(+V3_ONLY) ③ brain 미러
-- ④ **이 파일(set_channel_design v_allowed)**. 본문은 0085 베이스 + v_allowed 델타.
-- 적용 순서: 엔진(ai-video v3 --design-*-band-offset) + 어댑터 배포 → DB 적용.
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
        'title_size2',
        -- 0085: F-412 내레이션 자막 통 가로 폭(0.3~1.0 캔버스 비율 → --design-tts-width).
        -- 미지정이면 종전 0.852(=(1080−80×2)/1080). 글자 크기는 그대로 두고 좌우만 넓혀
        -- 줄이 접히는 것을 막는다. 범위 검증은 엔진 CLI(_E7_RANGES) — video_width 와 같은 규율.
        'tts_width',
        -- 0105: v3 전용 밴드 상대 앵커(자막/내레이션 윗변 = 밴드 하단 + N px)
        'subtitle_band_offset','tts_band_offset'];
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
-- 이 하나로 넷을 함께 연다: 자막/내레이션/텍스트 칸의 Enter 줄바꿈 · 자막 줄별 통 폭
-- (style.width, 화면 ⇔ 핸들) · 내레이션 통 폭(design.tts_width, 스타일 탭 + ⇔ 핸들) ·
-- **JP 편집실의 같은 기능**(유령 자막 ⇔ + Enter 줄바꿈). ⚠ 적용 후 정정(2026-08-25
-- 실측): SHOTCONE JP 는 ai-video localize(validate_line_style)가 받지만, **잔망루피는
-- localize_engine 스위치와 무관하게 vlp(zanmang_decision → process)가 굽는다** —
-- vlp 23648e0(F-412) 전 노드 배포가 잔망루피 개방의 실제 선행 조건이었다. 그 전의
-- 잔망루피 재렌더에서 구 vlp 가 width 를 몰라 오버라이드 전체가 삼켜지는 사고가
-- 실제로 났다(fail-loud 로 고침 — vlp 커밋 메시지 참고).
INSERT INTO public.ops_config(key, value, note)
VALUES ('editor_wrap', 'off',
        '편집실 자막 줄바꿈·글자 통 폭(F-412) — 엔진 2026-08-25 + 어댑터 tts_width 전 노드 배포 후 on')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0085','claude (design 허용 키 tts_width + editor_wrap 게이트 — F-412)');
