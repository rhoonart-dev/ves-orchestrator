-- 0017: 채널 작품 배정 관제 편집 (2026-08-10 사용자 요청 "채널 템플릿에서 작품도 변경")
-- 정본은 channels.json works — 관제 저장분이 있으면 그것이 유효 배정(planner·작품지정 검증
-- 모두 이 유효값을 본다). 해제하면 파일 정본 복귀. 템플릿(0014)·회차지정(0016)과 같은 규약.

CREATE TABLE IF NOT EXISTS public.channel_works_overrides (
    token_slug text PRIMARY KEY,
    works      text[] NOT NULL CHECK (array_length(works, 1) >= 1),
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.channel_works_overrides ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cwo_read ON public.channel_works_overrides;
CREATE POLICY cwo_read ON public.channel_works_overrides
    FOR SELECT TO authenticated USING (true);

CREATE OR REPLACE FUNCTION public.set_channel_works(p_slug text, p_works text[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text; v_clean text[]; w text;
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN
        RAISE EXCEPTION '없는 채널: %', p_slug;
    END IF;
    IF p_works IS NULL THEN
        DELETE FROM public.channel_works_overrides WHERE token_slug = p_slug;
        -- 작품이 파일 기본으로 돌아가면, 그 목록에 없는 작품·회차 지정(0016)은 정리
        DELETE FROM public.channel_plan_overrides o
         WHERE o.token_slug = p_slug
           AND NOT (o.work_title = ANY ((SELECT works FROM public.channels_mirror
                                          WHERE token_slug = p_slug)));
        RETURN jsonb_build_object('slug', p_slug, 'cleared', true);
    END IF;
    v_clean := ARRAY(SELECT DISTINCT btrim(x) FROM unnest(p_works) AS x
                      WHERE btrim(x) <> '');
    IF coalesce(array_length(v_clean, 1), 0) = 0 THEN
        RAISE EXCEPTION '작품 목록이 비어 있습니다';
    END IF;
    INSERT INTO public.channel_works_overrides (token_slug, works, updated_by, updated_at)
    VALUES (p_slug, v_clean, coalesce(auth.email(), auth.uid()::text), now())
    ON CONFLICT (token_slug) DO UPDATE SET
        works = EXCLUDED.works, updated_by = EXCLUDED.updated_by, updated_at = now();
    -- 새 목록에 없는 작품·회차 지정(0016)은 정리(모순 방지)
    DELETE FROM public.channel_plan_overrides o
     WHERE o.token_slug = p_slug AND NOT (o.work_title = ANY (v_clean));
    RETURN jsonb_build_object('slug', p_slug, 'works', v_clean);
END $$;
REVOKE ALL ON FUNCTION public.set_channel_works(text, text[]) FROM public;
GRANT EXECUTE ON FUNCTION public.set_channel_works(text, text[]) TO authenticated;

-- 작품·회차 지정(0016) 검증도 유효 작품(오버라이드 > 파일)을 보도록 갱신
CREATE OR REPLACE FUNCTION public.set_channel_plan(
    p_slug text, p_work text, p_episode integer DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text; v_works text[];
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    SELECT coalesce(o.works, m.works) INTO v_works
      FROM public.channels_mirror m
      LEFT JOIN public.channel_works_overrides o ON o.token_slug = m.token_slug
     WHERE m.token_slug = p_slug;
    IF v_works IS NULL THEN
        RAISE EXCEPTION '없는 채널: %', p_slug;
    END IF;
    IF p_work IS NULL THEN
        DELETE FROM public.channel_plan_overrides WHERE token_slug = p_slug;
        RETURN jsonb_build_object('slug', p_slug, 'cleared', true);
    END IF;
    IF NOT (p_work = ANY (v_works)) THEN
        RAISE EXCEPTION '이 채널의 작품이 아닙니다: % (유효 작품: %)', p_work, array_to_string(v_works, ', ');
    END IF;
    IF p_episode IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.sources
         WHERE work_title = p_work AND episode = p_episode AND is_active) THEN
        RAISE EXCEPTION '등록된 활성 소스가 없는 회차입니다: % %회차', p_work, p_episode;
    END IF;
    INSERT INTO public.channel_plan_overrides (token_slug, work_title, episode, note, updated_by, updated_at)
    VALUES (p_slug, p_work, p_episode, p_note, coalesce(auth.email(), auth.uid()::text), now())
    ON CONFLICT (token_slug) DO UPDATE SET
        work_title = EXCLUDED.work_title, episode = EXCLUDED.episode,
        note = EXCLUDED.note, updated_by = EXCLUDED.updated_by, updated_at = now();
    RETURN jsonb_build_object('slug', p_slug, 'work', p_work, 'episode', p_episode);
END $$;
