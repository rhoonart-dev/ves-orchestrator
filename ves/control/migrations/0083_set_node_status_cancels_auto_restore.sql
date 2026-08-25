-- ─────────────────────────────────────────────────────────────────────────────
-- 0083_set_node_status_cancels_auto_restore.sql — 사람이 정한 노드 상태가 갱신 복귀를 이긴다
--
-- 8/25 실측: 디스크가 차 큐를 독식하던 mm-06 을 사람이 draining 으로 내렸는데 엔진 갱신
-- 한 번에 조용히 active 로 돌아왔다. 갱신이 직전 상태를 기억하지 않아서였고, 그 절반은
-- 엔진 쪽(PR #63 _begin_update / _restore_after_self_drain)에서 닫았다 — 이제 갱신은
-- '갱신 **전** 상태'로 되돌린다.
--
-- 남은 창이 이 파일이 닫는 것이다: 갱신이 **도중일 때** 사람이 상태를 바꾸면, 갱신이
-- 끝나며 하는 복귀가 그 값을 덮어쓴다(창 = 갱신 1회 길이). 사람이 방금 정한 값이
-- 몇 분 전 상태에 지는 것은 앞뒤가 안 맞는다.
--
-- 방식: 사람이 상태를 정하면 **대기 중인 자동 복귀를 취소한다** — updating_since 를
-- 비우고 meta.pre_update_status 를 버린다. 복귀는 `WHERE updating_since IS NOT NULL`
-- 로 걸려 있으므로(updater._restore_after_self_drain) 이 한 줄로 무효가 된다.
--   · 갱신 중이 아니면 둘 다 이미 비어 있어 아무 일도 안 일어난다(회귀 0).
--   · 갱신이 실패하면 그 뒤 _set_node(disabled) 가 이긴다 — 검증 안 된 venv 로 도는 것을
--     막는 쪽이 우선이라 의도된 순서다.
--
-- ⚠ updating_since 는 원 주석에 '경보 제외용'으로도 적혀 있다(0006). 지금 그걸 읽는
--    코드는 없고(grep: updater.py 뿐), 사람이 방금 만진 노드라 경보가 떠도 오해가 아니다.
--
-- 본문은 적용 시점 라이브 정의(pg_get_functiondef, 2026-08-25 확인 — 0007 원본과 동일,
-- 드리프트 없음) 베이스 + UPDATE 문 델타.
--
-- 적용 순서: **DB 먼저, 코드는 그 다음**. 이 파일이 main 에 먼저 들어가면 마이그레이션
-- 게이트(updater.gate_blocks)가 적용될 때까지 6대 갱신을 통째로 막는다. RPC 는 대시보드만
-- 부르고 노드 코드는 안 부르므로 DB 를 먼저 올려도 구 노드에 영향이 없다.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.set_node_status(p_node text, p_status text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'permission denied'; END IF;
    IF p_status NOT IN ('active','draining','disabled') THEN
        RAISE EXCEPTION 'invalid status %', p_status; END IF;
    -- 0083: 사람이 정한 값이 갱신의 자동 복귀를 이긴다 — 대기 중인 복귀를 취소한다.
    UPDATE public.node_registry
       SET status = p_status,
           updating_since = NULL,
           meta = coalesce(meta,'{}'::jsonb) - 'pre_update_status'
     WHERE node_id = p_node;
    IF NOT FOUND THEN RAISE EXCEPTION 'unknown node %', p_node; END IF;
    PERFORM public._audit('set_node_status','node_registry',p_node,
                          jsonb_build_object('status',p_status));
END $function$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0083','claude (사람이 정한 노드 상태가 갱신 자동 복귀를 이긴다 — 8/25 mm-06)');
