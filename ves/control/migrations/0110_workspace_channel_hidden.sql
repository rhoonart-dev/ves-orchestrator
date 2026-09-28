-- 0110 — VES Workspace 에서 채널 숨기기 스위치 (2026-09-28)
-- 숨긴 채널 목록은 ops_config.workspace_hidden_channels(token_slug JSON 배열). 채널 정보·기록은 그대로 두고 워크스페이스 화면에서만 뺀다.
-- 화면은 이 함수로 슬러그 하나씩 넣고 뺀다(읽기-수정-쓰기를 한 트랜잭션 안에서 — 둘이 동시에 눌러도 서로 덮어쓰지 않는다. 0104 set_channel_paused 와 같은 규율).
CREATE OR REPLACE FUNCTION public.set_workspace_channel_hidden(p_slug text, p_hidden boolean)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_cur jsonb; v_new jsonb;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM public.user_roles WHERE user_id = auth.uid() AND role IN ('operator','admin')) THEN
    RAISE EXCEPTION '운영자 권한이 필요해요';
  END IF;
  IF p_slug IS NULL OR btrim(p_slug) = '' THEN RAISE EXCEPTION '채널이 비어 있어요'; END IF;
  IF coalesce(p_hidden,false) AND NOT EXISTS (SELECT 1 FROM public.channels_mirror WHERE token_slug = p_slug) THEN
    RAISE EXCEPTION '없는 채널이에요: %', p_slug;
  END IF;
  INSERT INTO public.ops_config(key, value, note, updated_at)
  VALUES ('workspace_hidden_channels', '[]', 'VES Workspace 화면에서 숨길 채널(token_slug JSON 배열)', now())
  ON CONFLICT (key) DO NOTHING;
  SELECT value::jsonb INTO v_cur FROM public.ops_config WHERE key = 'workspace_hidden_channels' FOR UPDATE;
  SELECT coalesce(jsonb_agg(s ORDER BY s), '[]'::jsonb) INTO v_new FROM (
    SELECT DISTINCT s FROM jsonb_array_elements_text(coalesce(v_cur, '[]'::jsonb)) s WHERE s <> p_slug
    UNION SELECT p_slug WHERE coalesce(p_hidden,false)) t;
  UPDATE public.ops_config SET value = v_new::text, updated_at = now() WHERE key = 'workspace_hidden_channels';
  RETURN v_new;
END $$;
REVOKE ALL ON FUNCTION public.set_workspace_channel_hidden(text, boolean) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_workspace_channel_hidden(text, boolean) TO authenticated;
