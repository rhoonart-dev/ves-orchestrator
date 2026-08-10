-- 0014: 채널 템플릿 관제 편집 (2026-08-10, 사용자 요청 "관제에서 변경·적용")
-- 정본(channels.json "design")은 그대로 — 관제 저장분은 오버라이드로 겹쳐 쓰고,
-- 해제하면 파일 기본으로 복귀한다. generate 실행 시점에 주입되어 다음 잡부터 즉시 적용.

-- ① 미러에 design 사본(대시보드가 '파일 기본값'을 보여주는 용도)
ALTER TABLE public.channels_mirror ADD COLUMN IF NOT EXISTS design jsonb;

-- ② 오버라이드 본체
CREATE TABLE IF NOT EXISTS public.channel_design_overrides (
    token_slug text PRIMARY KEY,
    design     jsonb NOT NULL,
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.channel_design_overrides ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cdo_read ON public.channel_design_overrides;
CREATE POLICY cdo_read ON public.channel_design_overrides
    FOR SELECT TO authenticated USING (true);
-- 쓰기는 RPC 로만 (operator+)

-- ③ RPC — 저장(NULL 이면 해제). 키 오타는 여기서 즉시 거부(생성 전에 크게 실패).
CREATE OR REPLACE FUNCTION public.set_channel_design(p_slug text, p_design jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_role text;
    v_key  text;
    v_allowed text[] := ARRAY[
        'title_y','title_font','title_size','title_color','title_color2',
        'subtitle_font','subtitle_size','subtitle_color','subtitle_y_margin',
        'subtitle_style','tts_color','tts_size','tts_y_margin',
        'work_title_y','work_font_size','work_color','aspect_ratio','face_tracking'];
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
