-- =====================================================================
-- 0099_trend_notice.sql — 트렌드 탭 공지 칸 (2026-08-27)
--
-- 노출 0 원인 판정(TREND_REPORT.md §11)이 저장소 문서에만 있었다 — 문서는 아무도
-- 안 연다. 일일 facts 로 환원되지 않는 **일회성 판정·공지**를 화면 상단에 실을
-- 자리를 만든다. 내용은 ops_config.trend_notice 한 행 — 사람이 고치고 지운다
-- (행을 지우면 칸도 사라진다). RPC 는 _safe_jsonb 로 읽는다(깨진 JSON 무해).
-- =====================================================================

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
                                WHERE key='algo_constants_proposed'),
        'notice',             (SELECT public._safe_jsonb(value) FROM public.ops_config
                                WHERE key='trend_notice'));
$$;

REVOKE ALL     ON FUNCTION public.get_trend_report(date) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.get_trend_report(date) TO authenticated;

-- 첫 공지 — 노출 0 판정(§11). 상황이 바뀌면 사람이 고치거나 지운다.
INSERT INTO public.ops_config(key, value, note) VALUES
 ('trend_notice',
  '{"title": "판정 — 왜 노출이 0인가 (8/27 실측)", "severity": "crit", "body": "일괄 개설(7/24~8/04) 17채널은 첫 주부터 테스트 배포 자체를 받지 못했다 — 개별 개설한 한 입 주막은 첫 주 노출 27,881, 일괄 개설군은 0~200. 받다가 꺼진 게 아니라 처음부터 억제다.\n따라서 썸네일·훅·길이 수정으로는 못 고친다(배포 이전 단계). 억제 채널 계속 발행은 배포 0이 보장된 제작비 지출이다.\n권고: 새 채널 1~2개를 개별로 만들어 죽은 작품(예: SNL 시즌8)을 같은 파이프라인으로 발행 — 첫 주 노출이 서면 채널 문제 확정, 점진 이관. 대체 채널을 다시 일괄로 만들지 말 것. 상세: docs/TREND_REPORT.md §11"}',
  '트렌드 탭 상단 공지(0099) — 사람이 고치고 지운다. 행을 지우면 칸도 사라진다')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0099','claude (0099 트렌드 탭 공지 칸)')
ON CONFLICT DO NOTHING;
