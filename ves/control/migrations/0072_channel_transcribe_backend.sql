-- ─────────────────────────────────────────────────────────────────────────────
-- 0072_channel_transcribe_backend.sql — 채널 'design' 허용 키에 'transcribe_backend'
--
-- 사용자 요청(2026-08-21): "자막 전사를 기본과 일레븐랩스 둘 중에 선택할 수 있게".
-- 대사 자막의 원본은 엔진 chunk_transcribe 단계의 받아쓰기다(편집실 자막 탭이
-- '전사된 대사 원본'이라 부르는 그것) — 지금은 엔진 내장 전사 하나뿐이라 사람이
-- 고를 통로가 없다. 채널 템플릿에 키 하나를 얹어 그 통로를 만든다.
--
-- **왜 채널 단위인가(편집실이 아니라)**: 전사는 생성 초반 단계이고 편집실 재렌더는
-- from_step=resources|render 로 재개한다 — 편집실에서 고른 값은 그 편에 절대 반영되지
-- 않는다. '고쳤는데 안 바뀐다'를 만들 바에는 애초에 다음 생성부터 적용되는 채널
-- 설정으로 둔다(대사 자막 끔 스위치 0065 와 같은 자리·같은 성격).
--
-- 계약: transcribe_backend = 'default' | 'elevenlabs' → 엔진 --transcribe-backend.
-- 값 검증 정본은 엔진(argparse choices)이고, 어댑터 _transcribe_value 가 그 앞에서
-- 사람이 읽을 메시지로 한 번 더 거른다(registry 원칙 — 오타가 조용히 기본값으로
-- 발행되면 안 된다). 여기(RPC)는 셋째 검증 층인 **키** 화이트리스트다 — 0065 교훈
-- (어댑터·brain 은 넣고 v_allowed 를 빠뜨려 저장이 거부됐다)을 이번엔 동시에 잇는다.
--
-- 본문은 적용 시점 라이브 정의(0069 판) 베이스 + v_allowed 한 항목 델타(0065·0069 전례).
--
-- 적용 순서: **엔진(ai-video --transcribe-backend) + brain 미러 전 노드 배포 확인 →
-- DB 적용 → ops_config channel_transcribe = on**. 이 파일은 게이트를 off 로 만들어
-- 두므로 언제 적용해도 안전하다 — 화면에 선택칸이 뜨지 않아 저장될 일이 없고, 구
-- 엔진 노드는 모르는 CLI 플래그에 argparse 로 즉사한다(E7·E10 과 같은 롤아웃).
-- 짝: ves/adapters/aivideo.py(CHANNEL_DESIGN_FLAGS·TRANSCRIBE_BACKENDS) ·
--     대시보드 채널 설정 모달(df_transcribe_backend) · docs/prompts/e11-transcribe-backend.md
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
        'transcribe_backend'];
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

-- 채널 설정 게이트 — 엔진(--transcribe-backend)·어댑터·brain 전 노드 배포 확인 후
-- 운영자가 'on' 으로 바꾼다. off 인 동안 채널 모달에 선택칸이 뜨지 않는다.
INSERT INTO public.ops_config(key, value, note)
VALUES ('channel_transcribe', 'off',
        '채널 자막 전사 백엔드 선택(transcribe_backend: default|elevenlabs) — 엔진 --transcribe-backend 전 노드 배포 후 on')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0072','claude (design 허용 키 transcribe_backend — 자막 전사 기본/일레븐랩스 선택, channel_transcribe 게이트)')
ON CONFLICT DO NOTHING;
