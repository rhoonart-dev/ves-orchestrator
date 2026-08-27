-- =====================================================================
-- 0098_trend_report.sql — 일일 트렌드 리포트 2단: 저장·조회 (T-P2·P3, 2026-08-27)
--
-- 발주서: docs/TREND_REPORT.md §4·§7. 1단(수집)은 0097.
--
-- 한 행 = 하루. **facts 와 narrative 를 컬럼으로 분리**한다 — facts 는 SQL 집계
-- (trend_report.py build_facts, 검증 가능한 숫자 전부), narrative 는 Gemini 해설
-- (없어도 리포트 성립 → NULL 허용). 숫자와 해설을 한 덩어리로 섞으면 해설이
-- 지어낸 수치를 걸러낼 방법이 없다.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.trend_report (
    report_date  date PRIMARY KEY,
    facts        jsonb NOT NULL,          -- build_facts 산출 (version 필드로 스키마 진화)
    narrative    jsonb,                   -- Gemini 해설 — 실패 시 NULL, 화면은 안 죽는다
    model        text,
    prompt_sha   text,                    -- 프롬프트 지문 — 해설 품질 회귀 추적용
    status       text,                    -- ok | facts_only | no_gemini_key | gemini_* …
    generated_at timestamptz NOT NULL DEFAULT now()
);

-- RLS — 0097 과 같은 규율: authenticated 읽기만. 쓰기는 service_role(생성기)만.
ALTER TABLE public.trend_report ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS trend_report_read ON public.trend_report;
CREATE POLICY trend_report_read ON public.trend_report
    FOR SELECT TO authenticated USING (true);

-- ── 조회 RPC ──────────────────────────────────────────────────────────
-- 원천은 이미 직접 SELECT 로 열려 있으므로 이 RPC 는 보안이 아니라 **조립 계층**이다
-- (0079 list_external_shorts 와 같은 갈래): 리포트 본문 + 임계값 현행/제안 + 날짜
-- 목록을 화면이 한 번에 받는다 — 배지(제안이 현행과 다름)를 그리려면 셋이 같이 와야 한다.
-- ops_config.value 는 text 이고 algo_constants 는 **사람이 손으로 고치는 값**이다(§5).
-- 무방비 ::jsonb 는 오타 하나(따옴표·꼬리 콤마)에 RPC 전체가 죽어 탭이 통째로
-- '조회 실패'가 된다 — 생성기(Python merge_constants)는 같은 값을 관용하는데 읽기가
-- 더 약하면 "facts 만으로 성립" 불변식이 화면에서 깨진다(리뷰 지적). 못 읽으면 NULL.
CREATE OR REPLACE FUNCTION public._safe_jsonb(p text)
RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN p::jsonb;
EXCEPTION WHEN others THEN
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION public.get_trend_report(p_date date DEFAULT NULL)
RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
    SELECT jsonb_build_object(
        'report', (SELECT to_jsonb(r) FROM (
                     SELECT report_date, facts, narrative, model, status, generated_at
                       FROM public.trend_report
                      WHERE p_date IS NULL OR report_date = p_date
                      ORDER BY report_date DESC LIMIT 1) r),
        'dates',  (SELECT coalesce(jsonb_agg(d.report_date ORDER BY d.report_date DESC),
                                   '[]'::jsonb)
                     FROM (SELECT report_date FROM public.trend_report
                            ORDER BY report_date DESC LIMIT 30) d),
        'constants',          (SELECT public._safe_jsonb(value) FROM public.ops_config
                                WHERE key='algo_constants'),
        'constants_proposed', (SELECT public._safe_jsonb(value) FROM public.ops_config
                                WHERE key='algo_constants_proposed'));
$$;

REVOKE ALL     ON FUNCTION public.get_trend_report(date) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.get_trend_report(date) TO authenticated;

-- ── 설정 행 ───────────────────────────────────────────────────────────
-- 기본 off 관례(0080)의 예외: 운영자가 2026-08-27 "활성화도 진행해줘 · 모든 예정된
-- 작업 완료"로 켠 채 출발을 지시했다 — 사람이 켰다는 사실을 여기 남긴다.
INSERT INTO public.ops_config(key, value, note) VALUES
 ('trend_report',
  '{"enabled": true, "model": "gemini-3.6-flash", "narrative": true}',
  '일일 리포트 생성기(T-P2) — 매일 05:00 KST. facts 는 SQL, 해설은 Gemini(실패해도 '
  'facts 로 성립). 모델·해설 여부는 여기서 고친다. 2026-08-27 운영자 지시로 켠 채 시작'),
 ('algo_watch',
  '{"enabled": true, "model": "gemini-3.6-flash", "interval_days": 7}',
  '알고리즘 상수 주간 조사(T-C3) — 주 1회 검색 grounding 조사, algo_constants_proposed '
  '에 제안만 기록. 자동 반영 안 함 — 반영은 사람이 algo_constants 를 고친다. '
  '2026-08-27 운영자 지시로 켠 채 시작')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0098','claude (0098 트렌드 리포트 저장·조회 — T-P2·P3)')
ON CONFLICT DO NOTHING;
