-- 0023: 소진을 채널별로 세고, 레거시 루프가 쓴 몫을 이어받는다 (2026-08-12 사용자 결정)
--
-- 두 가지를 고친다.
--
-- ① 채널별 분리 — SNL 코리아 리부트 시즌8 을 몰입도둑과 킥킥극장이 함께 쓴다. 종전엔
--    (작품, 회차)로만 세서 슬롯 3개를 두 채널이 나눠 썼다. 한 채널이 먼저 3번 쓰면
--    다른 채널은 그 회차를 아예 못 쓴다 — 배정이 겹칠수록 굶는 채널이 생긴다.
--    이제 채널마다 자기 use_limit 을 갖는다.
--
-- ② 레거시 이어받기 — 구 VES 루프(scene_loop)는 8/11 20:10 을 끝으로 멈췄고,
--    그때까지 '유튜브 공개 수'로 회차를 셌다(오케는 '발주 수'). 두 체계의 셈이 달라
--    오케스트레이터는 구 시스템이 이미 다 쓴 회차를 처음부터 다시 돈다.
--    구 결산치를 이 표에 담아 _pick_source 가 함께 세도록 한다.
--    ⚠ 회차 번호 체계가 달라 자동 대조가 불가능한 건은 넣지 않는다(사람이 확인 후 추가).

CREATE TABLE IF NOT EXISTS public.source_usage_legacy (
    work_title   text NOT NULL,
    episode      int,                                  -- NULL = 회차 미상 소스
    channel_slug text NOT NULL,
    used         int  NOT NULL DEFAULT 0 CHECK (used >= 0),
    note         text,
    recorded_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (work_title, channel_slug, episode)
);
COMMENT ON TABLE public.source_usage_legacy IS
  '구 scene_loop 루프가 이미 소진한 (작품·회차·채널) 몫. _pick_source 가 work_orders 수에 더해 센다.';

-- PRIMARY KEY 는 NULL 을 구분 못 한다 — 회차 미상 행이 여럿 들어가는 것을 따로 막는다.
CREATE UNIQUE INDEX IF NOT EXISTS source_usage_legacy_noep
    ON public.source_usage_legacy (work_title, channel_slug)
 WHERE episode IS NULL;

ALTER TABLE public.source_usage_legacy ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sul_read ON public.source_usage_legacy;
CREATE POLICY sul_read ON public.source_usage_legacy FOR SELECT TO authenticated USING (true);

-- 채널별 소진 현황 — 관제 소스 창고가 '이 소스를 어느 채널이 몇 번 썼나'를 보여줄 근거.
-- 종전 source_usage(소스 1행)는 그대로 두고 옆에 붙인다(대시보드 하위 호환).
CREATE OR REPLACE VIEW public.source_usage_by_channel AS
SELECT s.id                AS source_id,
       s.work_title,
       s.episode,
       c.channel_slug,
       s.use_limit,
       s.is_active,
       s.duration_sec,
       c.used_wo,
       c.used_legacy,
       c.used_wo + c.used_legacy                                   AS used_total,
       GREATEST(s.use_limit - (c.used_wo + c.used_legacy), 0)      AS remaining
  FROM public.sources s
  JOIN LATERAL (
        SELECT ch.channel_slug,
               (SELECT count(*) FROM public.work_orders w
                 WHERE w.work_title = s.work_title
                   AND w.episode IS NOT DISTINCT FROM s.episode
                   AND w.channel_slug = ch.channel_slug
                   AND w.status NOT IN ('cancelled','failed'))     AS used_wo,
               coalesce((SELECT l.used FROM public.source_usage_legacy l
                          WHERE l.work_title = s.work_title
                            AND l.episode IS NOT DISTINCT FROM s.episode
                            AND l.channel_slug = ch.channel_slug), 0) AS used_legacy
          FROM (SELECT cm.token_slug AS channel_slug
                  FROM public.channels_mirror cm
                 WHERE cm.works @> ARRAY[s.work_title]) ch
       ) c ON true;
