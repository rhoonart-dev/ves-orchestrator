-- 0123 VES Workspace 작품 숨기기(2026-10-01) — 레이블리에 같은 이름으로 두 번 등록된 옛것 등을 워크스페이스 화면에서만 뺀다.
-- 목록은 ops_config.workspace_hidden_works(JSON 배열): 레이블리 작품 id, 레이블리에 없는 작품은 'title:<작품명>'. 레이블리 원본은 그대로.
-- 0110 set_workspace_channel_hidden 과 같은 규율(읽기-수정-쓰기를 한 트랜잭션 안에서).
CREATE OR REPLACE FUNCTION public.set_workspace_work_hidden(p_key text, p_hidden boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_cur jsonb; v_new jsonb;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = auth.uid() AND role IN ('operator','admin')) THEN
    RAISE EXCEPTION '운영자 권한이 필요해요';
  END IF;
  IF p_key IS NULL OR btrim(p_key) = '' OR length(p_key) > 300 THEN RAISE EXCEPTION '작품이 비어 있어요'; END IF;
  IF coalesce(p_hidden,false) AND p_key NOT LIKE 'title:%' AND NOT EXISTS (SELECT 1 FROM public.laeebly_works WHERE id = p_key) THEN
    RAISE EXCEPTION '없는 작품이에요: %', p_key;
  END IF;
  INSERT INTO public.ops_config(key, value, note, updated_at)
  VALUES ('workspace_hidden_works', '[]', 'VES Workspace 화면에서 숨길 작품(레이블리 id 또는 title:<작품명> JSON 배열)', now())
  ON CONFLICT (key) DO NOTHING;
  SELECT value::jsonb INTO v_cur FROM public.ops_config WHERE key = 'workspace_hidden_works' FOR UPDATE;
  SELECT coalesce(jsonb_agg(s ORDER BY s), '[]'::jsonb) INTO v_new FROM (
    SELECT DISTINCT s FROM jsonb_array_elements_text(coalesce(v_cur, '[]'::jsonb)) s WHERE s <> p_key
    UNION SELECT p_key WHERE coalesce(p_hidden,false)) t;
  UPDATE public.ops_config SET value = v_new::text, updated_at = now() WHERE key = 'workspace_hidden_works';
  PERFORM public._audit('set_workspace_work_hidden', 'ops_config', p_key, jsonb_build_object('hidden', p_hidden));
  RETURN v_new;
END $$;
REVOKE ALL ON FUNCTION public.set_workspace_work_hidden(text, boolean) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_workspace_work_hidden(text, boolean) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0123','claude (워크스페이스 작품 숨기기)');
