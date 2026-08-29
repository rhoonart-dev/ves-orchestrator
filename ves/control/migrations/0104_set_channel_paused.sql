-- 0104 — 채널 일시정지를 관제에서 켜고 끄기 (2026-08-30, 운영자 요청)
--
-- 0103 은 `ops_config.paused_channels` 라는 값 하나를 만들었고, 켜고 끄려면 사람이 SQL 을
-- 쳐야 했다. 재개가 값 하나 고치기여야 한다는 것이 0103 의 전제인데, 그 '하나'를 칠 수
-- 있는 사람이 몇 안 되면 전제가 무너진다 — 그래서 화면에 붙인다.
--
-- 규율(R15): 규칙은 DB 안에 산다. 화면은 이 RPC 만 부르고, 배열을 화면에서 만들어
-- 통째로 덮어쓰지 않는다 — 둘이 동시에 누르면 나중 사람이 앞사람의 변경을 지운다.
-- 여기서는 **슬러그 하나만** 넣고 뺀다(읽기-수정-쓰기를 한 트랜잭션 안에서).
--
-- 값의 모양은 planner.paused_slugs 가 읽는 그대로 — 슬러그 문자열 JSON 배열.
-- 마지막 하나를 빼면 빈 배열 '[]' 이다(NULL 이 아니다 — planner 는 둘 다 '정지 없음'
-- 으로 읽지만, 값이 비어 사라진 것과 '아무도 안 쉰다'는 다른 뜻이라 형태를 지킨다).

CREATE OR REPLACE FUNCTION public.set_channel_paused(p_slug text, p_on boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_cur jsonb; v_new jsonb;
BEGIN
    IF NOT public.has_role(auth.uid(),'operator') THEN
        RAISE EXCEPTION 'operator 권한 필요';
    END IF;
    IF p_slug IS NULL OR btrim(p_slug) = '' THEN
        RAISE EXCEPTION '채널 슬러그가 비어 있습니다';
    END IF;
    -- 없는 채널을 정지 목록에 넣으면 아무도 눈치 못 챈 채 남는다(오타 방어).
    -- 재개(p_on=false)는 검사하지 않는다 — 채널이 정본에서 빠진 뒤에도 뺄 수 있어야 한다.
    IF coalesce(p_on,false)
       AND NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN
        RAISE EXCEPTION '없는 채널: %', p_slug;
    END IF;
    -- 🛑 전용 파이프라인(잔망루피 zanmang_autopilot)은 planner 가 애초에 건드리지 않는다.
    -- 여기 넣으면 목록에는 '정지'로 보이는데 실제로는 계속 만든다 — 조용한 거짓말이라
    -- 값이 들어가는 것 자체를 막는다. 그 채널을 멈추려면 ops_config.zanmang_pipeline
    -- (일일 잡)과 loopy_picker.enabled(자동 선별)를 내린다.
    IF coalesce(p_on,false) AND EXISTS (SELECT 1 FROM public.channels_mirror
                                         WHERE token_slug = p_slug AND pipeline IS NOT NULL) THEN
        RAISE EXCEPTION '전용 파이프라인 채널은 이 스위치로 멈추지 않습니다: % — zanmang_pipeline·loopy_picker 를 내리세요', p_slug;
    END IF;

    -- 한 트랜잭션 안에서 읽고 고친다. 행이 없으면 만든다(0103 이전 DB 호환).
    INSERT INTO public.ops_config(key, value, note)
    VALUES ('paused_channels','[]','일시정지 채널 — planner 가 계획에서 건너뛴다(0103)')
    ON CONFLICT (key) DO NOTHING;

    SELECT coalesce(nullif(value,'')::jsonb,'[]'::jsonb) INTO v_cur
      FROM public.ops_config WHERE key = 'paused_channels' FOR UPDATE;
    IF jsonb_typeof(v_cur) <> 'array' THEN v_cur := '[]'::jsonb; END IF;

    v_new := CASE WHEN coalesce(p_on,false)
        THEN (SELECT coalesce(jsonb_agg(DISTINCT x),'[]'::jsonb)
                FROM jsonb_array_elements_text(v_cur || to_jsonb(ARRAY[p_slug])) x)
        ELSE (SELECT coalesce(jsonb_agg(x),'[]'::jsonb)
                FROM jsonb_array_elements_text(v_cur) x WHERE x <> p_slug)
        END;

    UPDATE public.ops_config SET value = v_new::text, updated_at = now()
     WHERE key = 'paused_channels';

    PERFORM public._audit(CASE WHEN coalesce(p_on,false) THEN 'channel_pause'
                               ELSE 'channel_resume' END,
                          'channel', p_slug, jsonb_build_object('paused', v_new));
    RETURN jsonb_build_object('slug', p_slug, 'paused', coalesce(p_on,false),
                              'paused_channels', v_new);
END $$;
REVOKE ALL ON FUNCTION public.set_channel_paused(text, boolean) FROM public;
GRANT EXECUTE ON FUNCTION public.set_channel_paused(text, boolean) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0104','claude (채널 일시정지 관제 스위치 — 운영자 요청)')
ON CONFLICT DO NOTHING;
