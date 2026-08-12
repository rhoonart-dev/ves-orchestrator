-- 0022: 소스 길이를 관제에 노출 (2026-08-12 사용자 결정)
--
-- 길이가 두 가지 규칙의 근거가 됐다:
--   · 만들 편수  — 10분 미만 1편 · 10~30분 2편 · 30분 이상 3편 (use_limit)
--   · 사용 여부  — 3분 이하는 예고편·클립이라 쓰지 않는다 (is_active=false 로 등록)
-- 그런데 source_usage 뷰에 duration_sec 이 없어, 관제에서 '왜 비활성인지' 알 수가 없었다.
-- 컬럼만 더한다 — 기존 컬럼·순서·행 수·의미는 그대로다(대시보드 하위 호환).
-- ⚠ CREATE OR REPLACE VIEW 는 컬럼을 '끝에만' 붙일 수 있다(중간 삽입은 이름 변경으로 취급돼 거부).
--   그래서 duration_sec 은 맨 뒤다 — 보기엔 어색해도 이게 무중단으로 바꾸는 유일한 방법이다.

CREATE OR REPLACE VIEW public.source_usage AS
 SELECT s.id AS source_id,
    s.work_title,
    s.episode,
    s.use_limit,
    s.is_active,
    s.bytes,
    s.has_subtitle,
    count(w.id) FILTER (WHERE w.status <> ALL (ARRAY['cancelled'::text, 'failed'::text])) AS times_used,
    GREATEST(s.use_limit - count(w.id) FILTER (WHERE w.status <> ALL (ARRAY['cancelled'::text, 'failed'::text])), 0::bigint) AS remaining,
    s.duration_sec
   FROM sources s
     LEFT JOIN work_orders w ON w.work_title = s.work_title AND NOT w.episode IS DISTINCT FROM s.episode
  GROUP BY s.id;
