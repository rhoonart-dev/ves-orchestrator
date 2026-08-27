-- =====================================================================
-- 0100_trend_notice_dismiss.sql — 공지를 화면에서 내린다 (2026-08-27)
--
-- 0099 가 공지 칸을 열었는데 내리는 길이 psql 뿐이었다 — 운영자 지시(8/27):
-- "공지도 화면에서 지울 수 있게". 쓰기는 RPC 로만(R15), operator 게이트 + 감사.
-- 행을 지우는 게 아니라 값을 비운다? — 아니다, **행째 지운다**(0099 계약:
-- '행 삭제 = 칸 제거'). 다음 공지는 사람이 새 행을 넣는다.
-- =====================================================================

CREATE OR REPLACE FUNCTION public.dismiss_trend_notice()
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(), 'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    DELETE FROM public.ops_config WHERE key = 'trend_notice';
    PERFORM public._audit('dismiss_notice', 'ops_config', 'trend_notice', NULL);
END $$;

REVOKE ALL     ON FUNCTION public.dismiss_trend_notice() FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.dismiss_trend_notice() TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0100','claude (0100 공지 내리기 RPC)')
ON CONFLICT DO NOTHING;
