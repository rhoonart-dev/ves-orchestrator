-- 0016: 채널별 다음 작업(작품·회차) 지정 (2026-08-10 사용자 요청)
-- 기본은 자동(channels.json works 순서 + 회차 순환). 관제에서 고정하면 planner 가
-- 그 채널은 지정 작품(·회차)만 계획한다. 해제하면 자동 복귀. 정본 밖 작품은 거부(R14).

CREATE TABLE IF NOT EXISTS public.channel_plan_overrides (
    token_slug text PRIMARY KEY,
    work_title text NOT NULL,
    episode    integer,          -- NULL = 작품만 고정, 회차는 순환
    note       text,
    updated_by text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.channel_plan_overrides ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS cpo_read ON public.channel_plan_overrides;
CREATE POLICY cpo_read ON public.channel_plan_overrides
    FOR SELECT TO authenticated USING (true);

CREATE OR REPLACE FUNCTION public.set_channel_plan(
    p_slug text, p_work text, p_episode integer DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text; v_works text[];
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    SELECT works INTO v_works FROM public.channels_mirror WHERE token_slug = p_slug;
    IF v_works IS NULL THEN
        RAISE EXCEPTION '없는 채널: %', p_slug;
    END IF;
    IF p_work IS NULL THEN
        DELETE FROM public.channel_plan_overrides WHERE token_slug = p_slug;
        RETURN jsonb_build_object('slug', p_slug, 'cleared', true);
    END IF;
    IF NOT (p_work = ANY (v_works)) THEN
        RAISE EXCEPTION '이 채널의 작품이 아닙니다: % (채널 작품: %)', p_work, array_to_string(v_works, ', ');
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
REVOKE ALL ON FUNCTION public.set_channel_plan(text, text, integer, text) FROM public;
GRANT EXECUTE ON FUNCTION public.set_channel_plan(text, text, integer, text) TO authenticated;
