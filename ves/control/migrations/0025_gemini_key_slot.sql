-- 0025: Gemini 예비 키 슬롯 — 6대를 한 번에 갈아끼운다 (2026-08-12 사용자 요청)
--
-- 계기: 저녁에 evaluate 3건이 429 로 맴돌았다. 원문을 보니 분당 rate limit 이 아니라
--       "Your billing account has exceeded its monthly spending cap" 이었다.
--       상한은 **키가 아니라 결제 계정**에 걸린다 — 같은 계정의 새 키로는 못 푼다.
--       그래서 예비 키는 '다른 결제 계정'의 키여야 하고, 근본 해제는 ai.studio/billing 이다.
--       이 마이그레이션은 그때까지 회전을 이어가는 장치다.
--
-- 설계(ves/agent/gemini_key.py 와 짝):
--   · 키 **값**은 종전대로 env 파일에만 둔다(코드·DB 금지 — ARCHITECTURE §5·§11).
--     ves.env 에 GEMINI_API_KEY(주) 와 GEMINI_API_KEY_FALLBACK(예비)을 함께 둔다.
--   · 여기 DB 가 정하는 것은 **어느 쪽을 쓸지**뿐이다. 값이 아니라 선택이라 시크릿이 아니다.
--     그래서 6대가 다음 잡부터 함께 바뀐다 — 워커 재시작이 필요 없다.
--   · 자동 전환은 워커가 한다(지출 상한 429 를 만났을 때만). **되돌리기는 사람이** 한다 —
--     자동 복귀는 플래핑을 만든다.

INSERT INTO public.ops_config(key, value, note)
VALUES ('gemini_key', 'primary',
        'Gemini 키 슬롯: primary=GEMINI_API_KEY · fallback=GEMINI_API_KEY_FALLBACK. '
        '값이 아니라 선택만 담는다(키는 ves.env). 워커가 지출 상한 429 를 만나면 자동으로 '
        'fallback 으로 넘기고, 되돌리기는 관제에서 사람이 한다.')
ON CONFLICT (key) DO NOTHING;

-- 관제 [주 키로 되돌리기] / [예비 키로 전환]
CREATE OR REPLACE FUNCTION public.set_gemini_key(p_slot text, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_prev text; v_requeued int;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_slot NOT IN ('primary','fallback') THEN
        RAISE EXCEPTION '슬롯은 primary 또는 fallback 이어야 합니다 (받은 값: %)', p_slot;
    END IF;

    SELECT value INTO v_prev FROM public.ops_config WHERE key = 'gemini_key';

    INSERT INTO public.ops_config(key, value, note)
    VALUES ('gemini_key', p_slot,
            coalesce(nullif(btrim(p_note), ''),
                     '관제 전환 · ' || coalesce(auth.email(), auth.uid()::text)))
    ON CONFLICT (key) DO UPDATE
      SET value = EXCLUDED.value, note = EXCLUDED.note, updated_at = now();

    -- 쿼터로 한 시간 뒤에 세워둔 잡을 지금 다시 세운다. 안 그러면 전환 효과가
    -- 최대 한 시간 뒤에야 나타난다(lease.fail 이 quota 를 now()+1h 로 민다).
    UPDATE public.job_queue
       SET run_after = now(), updated_at = now()
     WHERE status = 'pending' AND error_class = 'quota' AND run_after > now();
    GET DIAGNOSTICS v_requeued = ROW_COUNT;

    PERFORM public._audit('set_gemini_key','ops_config','gemini_key',
            jsonb_build_object('from', v_prev, 'to', p_slot, 'requeued', v_requeued,
                               'note', p_note));
    RETURN jsonb_build_object('slot', p_slot, 'previous', v_prev, 'requeued', v_requeued);
END $$;
REVOKE ALL     ON FUNCTION public.set_gemini_key(text, text) FROM public;
GRANT  EXECUTE ON FUNCTION public.set_gemini_key(text, text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0025','claude-cloud (0025 Gemini 예비 키 슬롯 + 자동 폴백)')
ON CONFLICT DO NOTHING;
