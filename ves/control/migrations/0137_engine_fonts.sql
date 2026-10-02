-- 0137 새 엔진 폰트(2026-10-02) — 와구리체 · 페이퍼로지 · 프리젠테이션 · 에이투지체(굵기마다 따로)을 템플릿 값으로 받는다.
-- 함수 본문은 0135 그대로, 폰트 목록(c_fonts)만 넓힌다. 엔진 ai-video app/config.py FONT_NAME_MAP 과 같은 이름.
-- 파일 배포가 금지된 폰트(잘난체 · 잘난체 고딕 · 그리운 공정체 · 와구리체)의 웹용 파일은 공개 저장소 대신 비공개 저장소 ves-fonts 에 둔다
-- (로그인한 사람만 서명 링크로 — ves-workspace src/engine-fonts.js).
INSERT INTO storage.buckets(id, name, public, allowed_mime_types, file_size_limit)
VALUES ('ves-fonts', 'ves-fonts', false, ARRAY['font/ttf','font/otf','font/woff','font/woff2','application/octet-stream'], 20971520)
ON CONFLICT (id) DO NOTHING;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects' AND policyname = 'ves_fonts_read') THEN
    CREATE POLICY ves_fonts_read ON storage.objects FOR SELECT TO authenticated
      USING (bucket_id = 'ves-fonts' AND public.has_role((SELECT auth.uid()), 'viewer'));
  END IF;
END $$;

CREATE OR REPLACE FUNCTION public._render_template_design(p jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
DECLARE k text; v text;
  c_fonts constant text[] := ARRAY['JalnanGothic','Jalnan','NotoSansCJKkr-Black','mulmaru','Griun','WAGURI',
    'Paperlogy-9Black','Paperlogy-8ExtraBold','Paperlogy-7Bold','Paperlogy-6SemiBold',
    'Freesentation-9Black','Freesentation-8ExtraBold','Freesentation-7Bold','Freesentation-6SemiBold',
    'A2Z-9Black','A2Z-8ExtraBold','A2Z-7Bold','A2Z-6SemiBold'];
  c_colors constant text[] := ARRAY['title_color','title_color2','subtitle_color','tts_color','work_caption_color','platform_color'];
  c_logos constant text[] := ARRAY['tving_logo','coupangplay_icon','coupangplay_logo'];
  out jsonb := '{}'::jsonb;
BEGIN
  p := coalesce(p, '{}'::jsonb);
  IF jsonb_typeof(p) <> 'object' THEN RAISE EXCEPTION '템플릿 값이 이상해요'; END IF;
  FOR k, v IN SELECT key, value #>> '{}' FROM jsonb_each(p) LOOP
    v := nullif(btrim(coalesce(v, '')), '');
    CONTINUE WHEN v IS NULL;
    IF k IN ('title_font','subtitle_font','tts_font') THEN
      IF NOT v = ANY (c_fonts) THEN RAISE EXCEPTION '없는 폰트예요: %', v; END IF;
    ELSIF k = ANY (c_colors) THEN
      IF v !~ '^#[0-9A-Fa-f]{6}$' THEN RAISE EXCEPTION '색은 #RRGGBB 형식이어야 해요: %', v; END IF;
      v := upper(v);
    ELSIF k = 'platform_image' THEN
      IF NOT v = ANY (c_logos) THEN RAISE EXCEPTION '없는 권리사 로고예요: %', v; END IF;
    ELSIF k = 'platform_asset_id' THEN
      IF v !~ '^[0-9a-fA-F-]{36}$' OR NOT EXISTS (SELECT 1 FROM public.work_asset_versions WHERE id = v::uuid AND role = 'platform_logo') THEN
        RAISE EXCEPTION '작품 관리에 없는 권리사 로고예요';
      END IF;
    ELSIF k IN ('work_caption','platform_text') THEN
      IF length(v) > 60 THEN RAISE EXCEPTION '문구는 60자까지 쓸 수 있어요'; END IF;
    ELSE
      RAISE EXCEPTION '템플릿에서 다루지 않는 값이에요: %', k;
    END IF;
    out := out || jsonb_build_object(k, v);
  END LOOP;
  IF out ? 'platform_asset_id' THEN out := out - 'platform_image'; END IF;   -- 올린 로고가 이긴다
  RETURN out;
END $function$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0137','claude (새 엔진 폰트 · 비공개 폰트 저장소)');
