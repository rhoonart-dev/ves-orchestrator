-- =====================================================================
-- 0028_work_cards.sql — 작품 카드: 유튜브 회차 파싱 규칙의 정본 (운영 결정 2026-08-13)
--
-- 왜 DB 인가: 레거시 brain 의 works.json 은 git 파일이라 각 맥이 수정→푸시를
-- 반복하는 문제가 있었다. 여기서는 다른 정본(ops_config·channels_mirror)처럼
-- DB 테이블로 둔다 — 커밋 없음, 대시보드에서 즉시 조회·수정.
--
-- 쓰임: register_playlist 가 제목 회차 정규식·제목 필터를 여기서 읽는다
-- (잡 파라미터는 일회성 오버라이드로 유지). playlist_url 은 유튜브 자동
-- 재스캔(후속 브랜치)이 "어디를 다시 훑을지"의 정본이 된다.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.work_cards (
    work_title          text PRIMARY KEY,   -- laeebly 정본 표기와 정확히 일치(R14)
    title_episode_regex text,               -- 제목 → 방송 회차 (캡처그룹 1 = 회차)
    title_filter        text,               -- 공식채널 등 혼합 원천에서 제목 필터
    playlist_url        text,               -- 재스캔 원천 (자동 보충 후속 브랜치용)
    note                text,
    updated_by          text,
    updated_at          timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.work_cards ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS wc_read ON public.work_cards;
CREATE POLICY wc_read ON public.work_cards FOR SELECT TO authenticated USING (true);

CREATE OR REPLACE FUNCTION public.set_work_card(
    p_work text, p_regex text DEFAULT NULL, p_filter text DEFAULT NULL,
    p_playlist text DEFAULT NULL, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text;
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_work IS NULL OR btrim(p_work) = '' THEN
        RAISE EXCEPTION '작품명 필요';
    END IF;
    -- 정규식은 캡처그룹이 있어야 회차를 뽑는다 — 없는 채로 저장되는 실수를 막는다
    IF p_regex IS NOT NULL AND position('(' in p_regex) = 0 THEN
        RAISE EXCEPTION '정규식에 캡처그룹 ( ) 이 필요합니다 — 예: EP\.?(\d+)';
    END IF;
    IF p_regex IS NULL AND p_filter IS NULL AND p_playlist IS NULL AND p_note IS NULL THEN
        DELETE FROM public.work_cards WHERE work_title = p_work;
        RETURN jsonb_build_object('work', p_work, 'cleared', true);
    END IF;
    INSERT INTO public.work_cards AS wc
        (work_title, title_episode_regex, title_filter, playlist_url, note,
         updated_by, updated_at)
    VALUES (p_work, p_regex, p_filter, p_playlist, p_note,
            coalesce(auth.uid()::text,'system'), now())
    ON CONFLICT (work_title) DO UPDATE SET
        title_episode_regex = excluded.title_episode_regex,
        title_filter        = excluded.title_filter,
        playlist_url        = excluded.playlist_url,
        note                = excluded.note,
        updated_by          = excluded.updated_by,
        updated_at          = now();
    RETURN jsonb_build_object('work', p_work, 'saved', true);
END $$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0028','claude (작품 카드 — 회차 정규식·필터 정본, git 아닌 DB)')
ON CONFLICT DO NOTHING;
