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

-- 인자 규약 (부분 갱신을 안전하게):
--   NULL       = 그 필드는 건드리지 않는다  ← 기본값. 한 필드만 고칠 때 나머지가 산다
--   ''(빈 문자) = 그 필드를 지운다(NULL 로)
--   p_clear    = 카드 자체를 삭제
-- 종전 구현은 안 넘긴 인자를 NULL 로 덮어써서, 정규식만 고치면 title_filter 와
-- playlist_url 이 조용히 날아갔다(놀라운 토요일처럼 필터가 필수인 작품은 다음 등록에서
-- 채널의 다른 프로그램까지 전부 소스로 들어온다). '안 넘김'과 '비움'을 구분한다.
CREATE OR REPLACE FUNCTION public.set_work_card(
    p_work text, p_regex text DEFAULT NULL, p_filter text DEFAULT NULL,
    p_playlist text DEFAULT NULL, p_note text DEFAULT NULL,
    p_clear boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text; v_n int;
BEGIN
    SELECT role INTO v_role FROM public.user_roles WHERE user_id = auth.uid();
    IF v_role IS NULL OR v_role NOT IN ('operator','admin') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_work IS NULL OR btrim(p_work) = '' THEN
        RAISE EXCEPTION '작품명 필요';
    END IF;

    IF p_clear THEN
        DELETE FROM public.work_cards WHERE work_title = p_work;
        GET DIAGNOSTICS v_n = ROW_COUNT;
        RETURN jsonb_build_object('work', p_work, 'cleared', v_n > 0);
    END IF;

    -- 정규식 검증: 빈 문자('' = 지우기)는 통과, 그 외에는 실제로 써 본다.
    -- ⚠ 여기서 도는 것은 Postgres ARE 이고 실제 파싱은 Python re 다 — 문법이 완전히
    --   같지 않아 이 검사는 '명백한 오류'만 잡는다. 최종 안전망은 등록 어댑터 쪽
    --   base.compile_episode_regex 의 PermanentError 다(0027 리뷰 후속).
    IF p_regex IS NOT NULL AND p_regex <> '' THEN
        IF position('(' in p_regex) = 0 THEN
            RAISE EXCEPTION '정규식에 캡처그룹 ( ) 이 필요합니다 — 예: EP\.?(\d+)';
        END IF;
        BEGIN
            PERFORM regexp_match('회차 확인용 표본 EP.410', p_regex);
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION '정규식 문법 오류입니다: % — 저장하지 않았습니다', SQLERRM;
        END;
    END IF;

    IF p_regex IS NULL AND p_filter IS NULL AND p_playlist IS NULL AND p_note IS NULL THEN
        RETURN jsonb_build_object('work', p_work, 'saved', false,
                                  'note', '바꿀 값이 없습니다 — 카드를 지우려면 p_clear => true');
    END IF;

    INSERT INTO public.work_cards AS wc
        (work_title, title_episode_regex, title_filter, playlist_url, note,
         updated_by, updated_at)
    VALUES (p_work, nullif(p_regex,''), nullif(p_filter,''), nullif(p_playlist,''),
            nullif(p_note,''), coalesce(auth.uid()::text,'system'), now())
    ON CONFLICT (work_title) DO UPDATE SET
        -- 안 넘긴 인자(NULL)는 기존 값 유지, ''는 지우기
        title_episode_regex = CASE WHEN p_regex    IS NULL THEN wc.title_episode_regex
                                   ELSE nullif(p_regex,'')    END,
        title_filter        = CASE WHEN p_filter   IS NULL THEN wc.title_filter
                                   ELSE nullif(p_filter,'')   END,
        playlist_url        = CASE WHEN p_playlist IS NULL THEN wc.playlist_url
                                   ELSE nullif(p_playlist,'') END,
        note                = CASE WHEN p_note     IS NULL THEN wc.note
                                   ELSE nullif(p_note,'')     END,
        updated_by          = excluded.updated_by,
        updated_at          = now();
    RETURN jsonb_build_object('work', p_work, 'saved', true);
END $$;

-- 0028 초판(5인자)이 이미 적용된 DB 가 있으면 기본값이 겹쳐 호출이 모호해진다 — 지운다.
DROP FUNCTION IF EXISTS public.set_work_card(text, text, text, text, text);
REVOKE ALL     ON FUNCTION public.set_work_card(text,text,text,text,text,boolean) FROM public;
GRANT  EXECUTE ON FUNCTION public.set_work_card(text,text,text,text,text,boolean) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0028','claude (작품 카드 — 회차 정규식·필터 정본, git 아닌 DB)')
ON CONFLICT DO NOTHING;
