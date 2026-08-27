-- =====================================================================
-- 0101_cast_tags_and_latest_first.sql — 도달 복구 2레버 (2026-08-27)
--
-- 성과 검증 3차('4개월 늦은 1화')가 확정한 원인 둘에 대한 처방이다:
--   ① 검색되는 고유명사 부재 → work_cards.cast_names — 발행 시 [작품명]+출연자
--      실명을 일반 해시태그로 주입(brain Publish.enrich_params → --hashtags).
--      laeebly 정산 태그(#식별코드)는 엔진 별도 경로(work_hashtags)라 안 건드린다.
--   ② 회차 지연(4~5개월) → work_cards.prefer_latest — planner 소스 정렬을
--      최신 회차 우선으로 뒤집는다(기본 false = 종전 오름차순 그대로).
--
-- 편집은 RPC 하나(set_work_publish_policy) — operator 게이트 + 감사. NULL 인자는
-- '그대로 둔다'는 뜻이라 한 필드만 고칠 수 있다.
-- =====================================================================

ALTER TABLE public.work_cards
    ADD COLUMN IF NOT EXISTS cast_names    text[],
    ADD COLUMN IF NOT EXISTS prefer_latest boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.work_cards.cast_names IS
 '출연자 실명(0101) — 발행 일반 해시태그로 주입된다. 검증 3차: 검색되는 고유명사가 도달을 가른다';
COMMENT ON COLUMN public.work_cards.prefer_latest IS
 '최신 회차 우선(0101) — planner 소스 정렬 내림차순. 방영 중 작품에 켠다. 켜고 끄는 것은 사람';

CREATE OR REPLACE FUNCTION public.set_work_publish_policy(
    p_work text, p_cast text[] DEFAULT NULL, p_prefer_latest boolean DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(), 'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    INSERT INTO public.work_cards(work_title, cast_names, prefer_latest, updated_by, updated_at)
    VALUES (p_work, p_cast, coalesce(p_prefer_latest, false), auth.uid()::text, now())
    ON CONFLICT (work_title) DO UPDATE SET
        cast_names    = coalesce(p_cast,          work_cards.cast_names),
        prefer_latest = coalesce(p_prefer_latest, work_cards.prefer_latest),
        updated_by = auth.uid()::text, updated_at = now();
    PERFORM public._audit('set_publish_policy', 'work_cards', p_work,
        jsonb_build_object('cast', p_cast, 'prefer_latest', p_prefer_latest));
END $$;

REVOKE ALL     ON FUNCTION public.set_work_publish_policy(text,text[],boolean) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.set_work_publish_policy(text,text[],boolean) TO authenticated;

-- 시드 — 검증 3차가 실측한 두 방영작만. coalesce 로 사람 편집을 덮지 않는다.
--   가왕쇼: 한 입 주막이 이미 이 세 명으로 63,852회를 증명했다.
--   SNL 시즌8: 1위 채널(레전드라마, 편당 39.5만)의 태그 구성에서 가져왔다.
INSERT INTO public.work_cards (work_title, cast_names, prefer_latest, updated_by)
VALUES
 ('가왕쇼', ARRAY['박서진','홍지윤','전유진'], true, 'claude(0101 시드 — 검증 3차)'),
 ('SNL 코리아 리부트 시즌8', ARRAY['이수지','신동엽','김원훈','김규원','지예은'], true,
  'claude(0101 시드 — 검증 3차)')
ON CONFLICT (work_title) DO UPDATE SET
    cast_names    = coalesce(work_cards.cast_names,    EXCLUDED.cast_names),
    prefer_latest = (work_cards.prefer_latest OR EXCLUDED.prefer_latest);

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0101','claude (0101 출연자 해시태그 + 최신 회차 우선)')
ON CONFLICT DO NOTHING;
