-- =====================================================================
-- 0041_work_card_start_episode.sql — 작품 카드에 '시작 회차' (2026-08-14, 운영 결정)
--
-- 왜: 장수 방영작은 권리·운영 범위가 특정 회차부터다. 놀라운 토요일은 **410화부터**
-- 쓰고 있는데(운영자 확인 8/14), 전용 재생목록에는 344~429화가 다 들어 있다.
-- 그대로 등록하면 269건이 범위 밖으로 들어오고, planner 는 '최저 회차부터' 고르므로
-- 344화가 먼저 뽑힌다 — 쓰지 않기로 한 회차가 자동으로 제작된다.
--
-- 레거시 works.json 에는 이미 start_episode 가 있었다. 0030 이관 때 대응 컬럼이 없어
-- 옮기지 못했고(그 파일 머리말에 '옮기지 못한 것'으로 적혀 있다), min_source_duration_sec
-- 만 0032 로 들어왔다. 남은 절반을 여기서 채운다.
--
-- 규칙(register_sources.plan_rows):
--   · 제목에서 읽은 회차 < start_episode → 등록하지 않는다
--   · **회차를 못 읽은 항목(서수 폴백)도 등록하지 않는다** — 서수는 1부터 매겨져
--     start_episode(410) 보다 항상 작다. 그대로 두면 planner 가 그것부터 집어
--     시작 회차 설정이 통째로 무력해진다.
--   · 이미 등록된 범위 밖 행은 등록 잡이 목록을 다시 볼 때 비활성으로 내린다
--     (0037 제외 패턴과 같은 경로).
--   · NULL 이면 아무 제한 없음 — 기존 작품 동작 그대로.
--
-- 놀라운 토요일 설정(8/14 실측·운영 결정):
--   · 원천을 tvN Joy 채널 피드에서 **전용 재생목록**으로 바꾼다. 종전 등록 잡은 채널
--     피드+제목 필터라 최신 60개에서 2건만 걸렸고(그중 1건은 80초라 하한 미달),
--     사실상 쓸 수 있는 소스가 1건뿐이었다. 재생목록은 351개 중 350개가 회차 인식된다.
--   · start_episode 410 → 등록 대상 80건(410~429화, 회차당 4건).
--   · min_source_duration_sec 은 **300 유지**(운영자 결정 8/14) — 이 작품은 본편
--     클립이 대부분 10분 이하라 600 이면 거의 다 잘린다. 0032 시드가 의도했던 600 은
--     당시 이미 300 이 들어 있어 적용되지 않았고, 이번에 300 이 맞는 값으로 확정한다.
--   · 제외 패턴은 다른 작품과 같은 것을 건다 — 이 작품의 [예고]는 46초·1분대라 길이
--     하한에서 이미 걸리지만, 긴 예고가 올라올 때를 대비한다.
-- =====================================================================

ALTER TABLE public.work_cards
  ADD COLUMN IF NOT EXISTS start_episode int
  CHECK (start_episode IS NULL OR start_episode > 0);

COMMENT ON COLUMN public.work_cards.start_episode IS
  '이 회차부터만 소스로 쓴다(장수 방영작의 운영 시작점). 제목에서 읽은 회차가 이 값보다 '
  '작으면 등록하지 않고, 이미 등록된 것은 등록 잡이 비활성으로 내린다. '
  '회차를 못 읽은 항목(서수)도 제외한다 — 서수는 항상 이 값보다 작아 먼저 뽑힌다. NULL = 제한 없음.';

UPDATE public.work_cards
   SET start_episode      = 410,
       playlist_url       = 'https://www.youtube.com/playlist?list=PLgbB1gJhmG7Al52Qxn33TFTK3QZKoWNEF',
       title_exclude_regex = coalesce(title_exclude_regex,
                                      '\[(?:[^\]]*\s)?(?:예고|선공개|티저|하이라이트)\]'),
       updated_at         = now()
 WHERE work_title = '놀라운 토요일';

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0041','claude (작품 카드 시작 회차 — 놀라운 토요일 410화부터 · 전용 재생목록)')
ON CONFLICT DO NOTHING;
