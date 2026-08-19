-- =====================================================================
-- 0060_editor_templates.sql — 쇼츠 템플릿 (F-508)
-- 적용 순서: DB 먼저 무해 — 새 테이블·RPC 추가라 구 코드에 영향 없음.
--
-- 운영 요청(2026-08-20): "영상이 나오는 위치·비율, 제목·자막 등 여러 요소가 기본
-- 설정된 쇼츠 템플릿을 지정·편집해 쓰고 싶다". 템플릿 = 편집실이 편집하는 스타일 키
-- 묶음(aspect_ratio·video_y·title_*·subtitle_*·tts_*·title_y_fixed — 대시보드
-- edTplPick 화이트리스트). platform_*·work_* 같은 채널 정체성 키는 화면에 안 보여
-- 지울 수도 없으므로 저장·적용 양쪽에서 걸러낸다 — 채널 A 의 로고가 템플릿에 실려
-- 채널 B 로 새는 사고 방지.
--   · 저장 = 편집실 화면의 **유효 디자인**(채널 기본 + 이 편 오버라이드 병합) 스냅샷
--   · 적용 = 그 편의 디자인 오버라이드를 템플릿 값으로 **통째 교체**(edit_design 이
--     채널 위에 얹는다) — 우선순위: 채널 < 템플릿(적용 순간의 편당 값) < 자막 줄 style
--   · 키 검증은 제출 경로(adapters.aivideo.channel_design_flags 의 unknown-key
--     fail-loud)가 담당 — 저장은 reviewer 신뢰 범위(화면이 아는 키만 만든다).
--     서버는 크기 상한만 지킨다(고장난 클라이언트가 수 MB jsonb 로 목록 로딩을
--     느리게 만드는 것 방지 — 정상 디자인은 수백 바이트).
-- 읽기는 authenticated RLS(0009 규약), 쓰기는 reviewer RPC 만.
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.editor_templates (
    name        text PRIMARY KEY,
    design      jsonb NOT NULL,
    updated_by  text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.editor_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ves_auth_read_templates ON public.editor_templates;
CREATE POLICY ves_auth_read_templates ON public.editor_templates
  FOR SELECT TO authenticated USING (true);
GRANT SELECT ON public.editor_templates TO authenticated;

CREATE OR REPLACE FUNCTION public.save_editor_template(p_name text, p_design jsonb)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    IF coalesce(btrim(p_name), '') = '' OR length(btrim(p_name)) > 40 THEN
        RAISE EXCEPTION '템플릿 이름은 1~40자여야 합니다';
    END IF;
    IF p_design IS NULL OR jsonb_typeof(p_design) <> 'object'
       OR p_design = '{}'::jsonb THEN
        RAISE EXCEPTION '저장할 디자인 값이 없습니다';
    END IF;
    IF pg_column_size(p_design) > 16384 THEN
        RAISE EXCEPTION '디자인 값이 너무 큽니다(16KB 초과)';
    END IF;
    INSERT INTO public.editor_templates(name, design, updated_by, updated_at)
    VALUES (btrim(p_name), p_design, coalesce(auth.email(), auth.uid()::text), now())
    ON CONFLICT (name) DO UPDATE
      SET design = excluded.design, updated_by = excluded.updated_by, updated_at = now();
    PERFORM public._audit('template_save', 'editor_templates', btrim(p_name),
            jsonb_build_object('keys',
                (SELECT jsonb_agg(k) FROM jsonb_object_keys(p_design) k)));
    RETURN jsonb_build_object('name', btrim(p_name));
END $$;

CREATE OR REPLACE FUNCTION public.delete_editor_template(p_name text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_n int;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    DELETE FROM public.editor_templates WHERE name = btrim(p_name);
    GET DIAGNOSTICS v_n = ROW_COUNT;
    IF v_n = 0 THEN
        RAISE EXCEPTION '없는 템플릿입니다: %', p_name;
    END IF;
    PERFORM public._audit('template_delete', 'editor_templates', btrim(p_name), '{}'::jsonb);
    RETURN jsonb_build_object('name', btrim(p_name), 'deleted', true);
END $$;

REVOKE ALL     ON FUNCTION public.save_editor_template(text, jsonb) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.save_editor_template(text, jsonb) TO authenticated;
REVOKE ALL     ON FUNCTION public.delete_editor_template(text) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.delete_editor_template(text) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0060','claude (0060_editor_templates.sql 쇼츠 템플릿)')
ON CONFLICT DO NOTHING;
