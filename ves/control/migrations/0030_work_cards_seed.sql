-- =====================================================================
-- 0030_work_cards_seed.sql — 작품 카드 시드(레거시 works.json 이관) + anon 권한 마무리
--
-- 0028 이 work_cards 를 만들었지만 표가 비어 있어 register_playlist 가 잡 파라미터
-- 폴백으로만 돌았다. 레거시 brain 의 config/works.json(작품 카드 정본)에서 **유튜브
-- 소스 작품만** 옮긴다 — local 타입은 파일명 기반이라 register_drive 가 처리하고
-- 이 표와 무관하다.
--
-- ★ works.json _doc 의 규율을 그대로 따른다: "카드는 검증한 작품만 넣는다. 추측으로
--   채운 카드는 없는 것보다 나쁘다(엉뚱한 소스로 조용히 생성된다)."
--   · title_episode_regex 는 works.json 의 source.episode_regex 를 글자 그대로 옮겼다.
--     7개 모두 Python re 로 컴파일되고 캡처그룹 1개를 갖는 것을 확인했다.
--   · title_filter 는 works.json 에 없는 필드다. **tvN Joy 공식채널을 세 작품이
--     공유하는 경우에만** 넣었다 — 그 채널은 여러 프로그램이 섞여 있어 필터가 없으면
--     다른 작품 영상이 서수 회차로 등록된다. 값은 각 작품 regex 의 해시태그에서
--     그대로 왔다(plan_rows 의 대조는 띄어쓰기를 무시한다).
--   · 놀라운 토요일은 전용 채널인지 확인되지 않아 필터를 비웠다 — regex 가 이미
--     amazingsaturday 를 요구한다. 필요하면 관제에서 set_work_card 로 채운다.
--   · 커리어데이·B급 스튜디오는 works.json 에 회차 정규식이 없다. 없는 채로 두면
--     plan_rows 가 기본 패턴(EP·제N회·N화)을 쓴다 — 추측 정규식을 넣지 않는다.
--     playlist_url 은 후속 자동 재스캔의 정본이라 채워 둔다.
--
-- ⚠ 옮기지 못한 것: works.json 의 start_episode(장기 방영작 시작 회차)와
--   min_source_duration_sec(작품별 길이 하한 — 놀토·도깨비 600s, 산지직송·스레파 500s,
--   커리어데이·B급 300s)는 work_cards 에 대응 컬럼이 없다. 0027 은 3분(180s) 일괄이라
--   작품별 하한이 아직 반영되지 않는다. 스키마 확장은 별도 결정.
--
-- ON CONFLICT DO NOTHING: 사람이 관제에서 이미 채운 카드를 시드가 덮지 않는다.
-- =====================================================================

INSERT INTO public.work_cards
    (work_title, title_episode_regex, title_filter, playlist_url, note, updated_by)
VALUES
    -- tvN Joy 공식채널 공유 3작품 — 필터 필수
    ('언니네 산지직송 in 칼라페',
     '#언니네산지직송in칼라페\s*EP[.\s]?(\d{1,3})\b',
     '언니네산지직송in칼라페',
     'https://www.youtube.com/@tvNJoy_official/videos',
     'works.json 이관(0030). 채널 전체가 소스라 제목으로 작품을 한정해야 한다. '
     '레거시 길이 하한 500s(선공개 227~415s·티저 20~66s 를 거르기 위함) — 미반영',
     'migration:0030'),
    ('스트릿 레스토랑 파이터',
     '#스트릿레스토랑파이터\s*EP[.\s]?(\d{1,3})\b',
     '스트릿레스토랑파이터',
     'https://www.youtube.com/@tvNJoy_official/videos',
     'works.json 이관(0030). tvN Joy 공유 채널 — 필터 필수. 레거시 길이 하한 500s 미반영',
     'migration:0030'),
    ('언더커버셰프',
     '#언더커버셰프\s*EP[.\s]?(\d{1,3})\b',
     '언더커버셰프',
     'https://www.youtube.com/@tvNJoy_official/videos',
     'works.json 이관(0030). tvN Joy 공유 채널 — 필터 필수. 레거시 길이 하한 600s 미반영',
     'migration:0030'),
    -- 전용 원천 — 필터 불필요
    ('놀라운 토요일',
     'amazingsaturday\s*EP[.\s]?(\d{1,3})\b',
     NULL,
     'https://www.youtube.com/channel/UCTnafh2iyIWh7MhcGBmGU0g/videos',
     'works.json 이관(0030). 전용 채널 여부 미확인이라 필터는 비움 — regex 가 이미 '
     'amazingsaturday 를 요구한다. 레거시 시작 회차 411 · 길이 하한 600s 미반영',
     'migration:0030'),
    ('도깨비 10주년 여행',
     '\bEP[.\s]?(\d{1,3})\b',
     NULL,
     'https://www.youtube.com/playlist?list=PLgbB1gJhmG7CbBf0iq8vzN8QPzZ47xq5C',
     'works.json 이관(0030). 작품 전용 재생목록이라 필터 불필요. 길이 하한 600s 미반영',
     'migration:0030'),
    -- 회차 정규식이 레거시에도 없던 작품 — 추측하지 않는다(기본 패턴으로 간다)
    ('커리어데이',
     NULL, NULL,
     'https://www.youtube.com/@careerday_official/videos',
     'works.json 에 회차 정규식 없음 — 추측 금지(_doc 규율). 기본 패턴으로 파싱하고 '
     '실패분은 서수 폴백. 레거시 시작 회차 4 · 길이 하한 300s 미반영',
     'migration:0030'),
    ('B급 스튜디오',
     NULL, NULL,
     'https://www.youtube.com/@B급studio/videos',
     'works.json 에 회차 정규식 없음 — 추측 금지(_doc 규율). '
     '레거시 시작 회차 35 · 길이 하한 300s 미반영',
     'migration:0030')
ON CONFLICT (work_title) DO NOTHING;

-- 0029 에서 빠뜨린 마지막 anon 회수 — wo_matches_source 는 SECURITY INVOKER 순수
-- 비교 함수라 실위험은 없지만(인자만 비교한다) advisor 가 계속 잡는다.
-- 0008_rpc_grants_fix.sql 의 함정: REVOKE FROM public 으로는 Supabase 가 걸어 둔
-- anon 직접 grant 가 안 걷힌다 — anon 을 명시해야 한다.
REVOKE ALL ON FUNCTION public.wo_matches_source(text,text,text,text,text,text) FROM anon;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0030','claude (작품 카드 시드 — works.json 유튜브 7작품 + anon 회수 마무리)')
ON CONFLICT DO NOTHING;
