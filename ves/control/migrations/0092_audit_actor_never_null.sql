-- 0092 — 감사 기록의 actor 가 NULL 이면 안 된다 (2026-08-25, 첫 실전 왕복이 잡았다)
--
-- `_audit` 은 actor 를 `auth.uid()` 로만 적었다. 그 값은 **PostgREST 요청 안에서만**
-- 채워진다 — 대시보드(사람 손)는 늘 값이 있어서 아무도 몰랐다.
--
-- 스케줄러가 같은 함수를 부르면(loopy_picker.auto_select → _select_external_short_impl)
-- 요청 컨텍스트가 없어 NULL 이고, `dashboard_actions.actor` 의 NOT NULL 에 걸린다.
-- 감사 INSERT 는 함수 **끝**에 있으므로 그때까지 만든 작업지시·잡이 통째로 롤백된다:
--
--     null value in column "actor" of relation "dashboard_actions"
--
-- 실측: 자동 선별이 매 후보마다 이 예외로 죽어(그 자리에서 잡아 다음 후보로 넘어간다)
-- LOOPY 작업지시가 **0건**이었다. 로그에만 남아 DB 만 봐서는 '아무 일도 안 일어난'
-- 것처럼 보였다 — 조용한 전량 실패다.
--
-- 사람 경로의 기록은 그대로다(auth.uid() 가 이긴다). 없을 때만 누가 했는지 적는다.
-- 감사를 못 남긴다고 정당한 선택을 죽이지 않는다 — 다만 '누구'를 잃지도 않는다.

CREATE OR REPLACE FUNCTION public._audit(p_action text, p_kind text, p_id text,
                                         p_payload jsonb)
 RETURNS void
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  INSERT INTO public.dashboard_actions(actor, action, target_kind, target_id, payload)
  VALUES (coalesce(nullif(auth.uid()::text, ''), 'system:' || session_user),
          p_action, p_kind, p_id, coalesce(p_payload,'{}'::jsonb));
$function$;
