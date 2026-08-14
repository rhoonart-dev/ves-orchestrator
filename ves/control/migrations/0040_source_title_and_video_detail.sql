-- =====================================================================
-- 0040_source_title_and_video_detail.sql — 소스에 제목 저장 + 뷰에 영상 식별 노출
--                                          (2026-08-14, 운영 요청)
--
-- 왜: 0027 부터 소진은 영상 단위인데 화면은 회차 합산만 보여준다. "회차 1 — 한도 21,
-- 남음 17"까지는 보여도 **그 21이 영상 7개 중 어디에 남았는지**는 알 수 없다 —
-- sources 에 제목이 아예 없고(등록 때 읽고 버렸다), 뷰에 URL 도 없기 때문이다.
--
-- 셋을 한 번에 고친다.
--   ① sources.title — 등록 시점 제목을 박제한다. 나중에 유튜브에서 제목이 바뀌어도
--      '그때 쓴 영상'을 그대로 기억한다(소스 캐시 meta.json 의 video_id 박제와 같은 이유).
--   ② 두 뷰 끝에 source_url·title·published_ts·created_at 추가 — 화면이 영상을
--      식별하고 planner 와 같은 순서(COALESCE(published_ts, created_at))로 늘어놓는다.
--   ③ source_usage_by_channel 의 used_legacy 를 **못박히지 않은 몫만**으로 좁히고
--      used_legacy_pin(0039 로 영상에 못박힌 몫)을 끝에 추가한다. 종전 used_legacy 는
--      회차 값을 전 행에 반복해 줬다 — 행 단위로 읽는 순간 전부 소진으로 보였다
--      (실측: 도깨비 1회차 7행 전부 remaining 0, 실제 planner 는 17편 여유).
--
-- 뷰 규율(0032 와 동일): 컬럼은 끝에만 추가한다 — CREATE OR REPLACE VIEW 는 기존
-- 컬럼을 지우거나 옮기지 못한다. 기존 12개 컬럼의 이름·순서는 그대로다.
-- ⚠ used_legacy 의 **의미**는 좁아진다(못박힌 몫 제외). 배포 전 대시보드는 이 값을
--   회차당 한 번 세므로, 이 마이그레이션 후 새 대시보드 배포 전까지는 못박힌 작품
--   (도깨비)의 사용량이 화면에서 낮아 보인다 — planner 판단에는 영향 없다(뷰를 안 본다).
-- =====================================================================

ALTER TABLE public.sources ADD COLUMN IF NOT EXISTS title text;

COMMENT ON COLUMN public.sources.title IS
  '등록 시점의 영상 제목(박제) — 화면 식별용. 유튜브에서 제목이 바뀌어도 갱신하지 않는다. '
  '0040 이전 등록분은 NULL — 등록 잡이 다시 돌 때 빈 칸만 채운다.';

CREATE OR REPLACE VIEW public.source_usage
WITH (security_invoker = true) AS
SELECT s.id AS source_id, s.work_title, s.episode, s.use_limit, s.is_active,
       s.bytes, s.has_subtitle,
       COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')) AS times_used,
       GREATEST(s.use_limit - COUNT(w.id) FILTER (WHERE w.status NOT IN ('cancelled','failed')), 0) AS remaining,
       s.duration_sec,
       (s.is_active AND (s.duration_sec IS NULL
                         OR s.duration_sec > public.source_min_duration(s.work_title))) AS usable,
       -- 0040: 영상 식별 + planner 와 같은 정렬 재료
       s.source_url, s.title, s.published_ts, s.created_at
FROM public.sources s
LEFT JOIN public.work_orders w
  ON public.wo_matches_source(w.work_title, w.source_sha256, w.source_url,
                              s.work_title, s.sha256, s.source_url)
GROUP BY s.id;

GRANT SELECT ON public.source_usage TO authenticated;

CREATE OR REPLACE VIEW public.source_usage_by_channel
WITH (security_invoker = true) AS
SELECT s.id                AS source_id,
       s.work_title,
       s.episode,
       c.channel_slug,
       s.use_limit,
       s.is_active,
       s.duration_sec,
       c.used_wo,
       c.used_legacy,      -- 0040: 못박히지 않은(회차 단위) 몫만 — 행마다 반복되므로
                           -- 행 단위로 읽는 쪽은 앞선 행부터 배분해야 한다(planner 규칙)
       c.used_wo + c.used_legacy_pin + c.used_legacy               AS used_total,
       GREATEST(s.use_limit - (c.used_wo + c.used_legacy_pin + c.used_legacy), 0) AS remaining,
       (s.is_active AND (s.duration_sec IS NULL
                         OR s.duration_sec > public.source_min_duration(s.work_title))) AS usable,
       c.used_legacy_pin,  -- 0040: 이 영상에 못박힌 레거시 몫(0039) — 행 단위 정확값
       s.source_url, s.title, s.published_ts, s.created_at
  FROM public.sources s
  JOIN LATERAL (
        SELECT ch.channel_slug,
               (SELECT count(*) FROM public.work_orders w
                 WHERE public.wo_matches_source(w.work_title, w.source_sha256,
                                                w.source_url, s.work_title,
                                                s.sha256, s.source_url)
                   AND w.channel_slug = ch.channel_slug
                   AND w.status NOT IN ('cancelled','failed'))     AS used_wo,
               coalesce((SELECT sum(l.used) FROM public.source_usage_legacy l
                          WHERE l.work_title = s.work_title
                            AND l.episode IS NOT DISTINCT FROM s.episode
                            AND l.channel_slug = ch.channel_slug
                            AND l.source_url IS NULL), 0)::int     AS used_legacy,
               coalesce((SELECT sum(l.used) FROM public.source_usage_legacy l
                          WHERE l.work_title = s.work_title
                            AND l.channel_slug = ch.channel_slug
                            AND l.source_url = s.source_url), 0)::int AS used_legacy_pin
          FROM (SELECT cm.token_slug AS channel_slug
                  FROM public.channels_mirror cm
                 WHERE cm.works @> ARRAY[s.work_title]) ch
       ) c ON true;

GRANT SELECT ON public.source_usage_by_channel TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0040','claude (소스 제목 박제 + 뷰에 영상 식별 — 소스 화면 영상 단위 보기)')
ON CONFLICT DO NOTHING;
