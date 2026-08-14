-- =====================================================================
-- 0037_work_card_title_exclude.sql — 작품 카드에 '제목 제외 패턴' (2026-08-14)
--
-- 왜: 유튜브 원천에는 본편과 홍보물이 섞여 온다. 지금 거르는 수단은 두 가지뿐이다.
--   · title_filter — **포함** 조건이라 '이 작품인가'만 가른다
--   · min_source_duration_sec — 시간 기준이라 긴 홍보물을 못 거른다
--     (실측 8/14: 언더커버셰프 [9화 선공개] 10분 24초 · 칼라페 [3회 선공개] 6분 55초)
-- 그 결과 예고·선공개·티저가 소스로 등록돼 사람이 손으로 비활성 처리해 왔다
-- (도깨비 10주년 여행 8/14 — 18건을 손으로 내렸다).
--
-- 표기가 방송사마다 달라('[3화 예고]' vs '[3회 예고]') 전역 규칙 하나로는 안 맞는다 —
-- title_episode_regex 와 같은 이유로 작품별 컬럼으로 둔다. 비어 있으면(NULL) 아무것도
-- 거르지 않는다 — 기존 작품의 동작은 그대로다.
--
-- ★드라이브 작품에는 영향이 없다. 이 값을 읽는 곳은 register_sources(유튜브 목록)뿐이고,
--   드라이브 인입은 파일명을 보는 별개 경로다. 컬럼은 공용 표라 행에 생기지만 무시된다.
--
-- 시드는 **제목을 실제로 확인한 작품만** 넣는다(0030 의 규율 — "추측으로 채운 카드는
-- 없는 것보다 나쁘다"). 8/14 실측으로 대조한 결과:
--   · 도깨비 44건 중 9건 제외 · 칼라페 60건 중 11건 · 언더커버셰프 59건 중 9건
--   · 커리어데이 82건 중 0건(홍보물이 없는 채널 — 그래도 향후 대비로 같은 패턴)
--   · 네 작품 모두 '[N회 미방분]'은 제외되지 않는다(운영자 결정 8/14: 미방분은 쓴다)
--   · 대괄호 안의 '하이라이트'만 잡는다 — 본편에 붙는 해시태그 '#highlight' 는
--     대괄호가 없어 걸리지 않는다(칼라페 본편 10건이 여기 걸리면 통째로 사라진다)
-- 놀라운 토요일·스트릿 레스토랑 파이터·B급 스튜디오는 목록을 대조하지 않아 비워 둔다 —
-- 관제에서 set_work_card 로 채운다.
-- =====================================================================

ALTER TABLE public.work_cards
  ADD COLUMN IF NOT EXISTS title_exclude_regex text;

COMMENT ON COLUMN public.work_cards.title_exclude_regex IS
  '제목이 이 정규식에 걸리면 소스로 등록하지 않는다(예고·선공개·티저). '
  '이미 등록된 행은 등록 잡이 목록을 다시 볼 때 비활성으로 내린다. '
  'NULL = 아무것도 거르지 않음. 캡처그룹은 필요 없다. 유튜브 등록에만 쓰인다.';

-- ── set_work_card: 제외 패턴 인자 추가 (7인자 → 8인자) ─────────────────
CREATE OR REPLACE FUNCTION public.set_work_card(
    p_work text, p_regex text DEFAULT NULL, p_filter text DEFAULT NULL,
    p_playlist text DEFAULT NULL, p_note text DEFAULT NULL,
    p_clear boolean DEFAULT false, p_min_duration int DEFAULT NULL,
    p_exclude text DEFAULT NULL)
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

    IF p_min_duration IS NOT NULL AND p_min_duration < 0 THEN
        RAISE EXCEPTION '길이 하한은 0 이상이어야 합니다 (0 = 기본값 180 으로 되돌림)';
    END IF;

    -- 정규식 검증: 빈 문자('' = 지우기)는 통과, 그 외에는 실제로 써 본다.
    -- ⚠ 여기서 도는 것은 Postgres ARE 이고 실제 파싱은 Python re 다 — 최종 안전망은
    --   등록 어댑터 쪽 base.compile_* 의 PermanentError 다.
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

    -- 제외 패턴은 캡처그룹을 요구하지 않는다 — 걸리는지만 본다.
    IF p_exclude IS NOT NULL AND p_exclude <> '' THEN
        BEGIN
            PERFORM regexp_match('제외 확인용 표본 [3회 예고] 본문', p_exclude);
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION '제외 패턴 문법 오류입니다: % — 저장하지 않았습니다', SQLERRM;
        END;
    END IF;

    IF p_regex IS NULL AND p_filter IS NULL AND p_playlist IS NULL AND p_note IS NULL
       AND p_min_duration IS NULL AND p_exclude IS NULL THEN
        RETURN jsonb_build_object('work', p_work, 'saved', false,
                                  'note', '바꿀 값이 없습니다 — 카드를 지우려면 p_clear => true');
    END IF;

    INSERT INTO public.work_cards AS wc
        (work_title, title_episode_regex, title_filter, playlist_url, note,
         min_source_duration_sec, title_exclude_regex, updated_by, updated_at)
    VALUES (p_work, nullif(p_regex,''), nullif(p_filter,''), nullif(p_playlist,''),
            nullif(p_note,''), nullif(p_min_duration, 0), nullif(p_exclude,''),
            coalesce(auth.uid()::text,'system'), now())
    ON CONFLICT (work_title) DO UPDATE SET
        -- 안 넘긴 인자(NULL)는 기존 값 유지, ''(정수는 0)는 지우기
        title_episode_regex = CASE WHEN p_regex    IS NULL THEN wc.title_episode_regex
                                   ELSE nullif(p_regex,'')    END,
        title_filter        = CASE WHEN p_filter   IS NULL THEN wc.title_filter
                                   ELSE nullif(p_filter,'')   END,
        playlist_url        = CASE WHEN p_playlist IS NULL THEN wc.playlist_url
                                   ELSE nullif(p_playlist,'') END,
        note                = CASE WHEN p_note     IS NULL THEN wc.note
                                   ELSE nullif(p_note,'')     END,
        min_source_duration_sec = CASE WHEN p_min_duration IS NULL
                                       THEN wc.min_source_duration_sec
                                       ELSE nullif(p_min_duration, 0) END,
        title_exclude_regex = CASE WHEN p_exclude IS NULL THEN wc.title_exclude_regex
                                   ELSE nullif(p_exclude,'')  END,
        updated_by          = excluded.updated_by,
        updated_at          = now();
    RETURN jsonb_build_object('work', p_work, 'saved', true);
END $$;

-- 7인자 판이 남아 있으면 기본값이 겹쳐 호출이 모호해진다 — 지운다(0032 와 같은 이유).
DROP FUNCTION IF EXISTS public.set_work_card(text, text, text, text, text, boolean, int);
REVOKE ALL     ON FUNCTION public.set_work_card(text,text,text,text,text,boolean,int,text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.set_work_card(text,text,text,text,text,boolean,int,text) TO authenticated;

-- ── 시드: 8/14 에 목록을 실제로 대조한 작품만 ──────────────────────────
-- 사람이 이미 채운 카드는 덮지 않는다(IS NULL 조건).
UPDATE public.work_cards SET title_exclude_regex = v.rx, updated_at = now()
  FROM (VALUES
    ('도깨비 10주년 여행',        '\[(?:[^\]]*\s)?(?:예고|선공개|티저|하이라이트)\]'),
    ('언니네 산지직송 in 칼라페', '\[(?:[^\]]*\s)?(?:예고|선공개|티저|하이라이트)\]'),
    -- 언더커버셰프만 '선공개'를 남긴다(운영자 결정 8/14) — 이 작품의 선공개는 본편급
    -- 길이다: [9화 선공개] 10분 24초 · [6화 선공개] 10분 이상(8/14 실측).
    ('언더커버셰프',              '\[(?:[^\]]*\s)?(?:예고|티저|하이라이트)\]'),
    ('커리어데이',                '\[(?:[^\]]*\s)?(?:예고|선공개|티저|하이라이트)\]')
  ) AS v(work, rx)
 WHERE work_cards.work_title = v.work AND work_cards.title_exclude_regex IS NULL;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0037','claude (작품 카드 제목 제외 패턴 — 예고·선공개·티저 등록 차단)')
ON CONFLICT DO NOTHING;
