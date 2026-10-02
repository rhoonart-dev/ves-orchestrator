-- 0126 채널 + 작품 권리사 검수 정책(2026-10-02) — 같은 작품도 채널에 따라 권리사 검수가 필요 없을 수 있다.
-- 예: 재미쇼츠 × 로또 1등도 출근합니다 — 내부 승인만 하고 바로 예약해 올린다(사용자 지시). 레이블리 작품 정책(laeebly_works.inspection_policy)을 이 조합에서만 덮는다.
CREATE TABLE public.channel_work_policies (
 token_slug text NOT NULL,
 work_title text NOT NULL,
 inspection_policy text NOT NULL CHECK (inspection_policy IN ('required','none','unaired_only')),
 note text CHECK (note IS NULL OR length(note) <= 300),
 updated_by uuid DEFAULT auth.uid(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY (token_slug, work_title)
);
COMMENT ON TABLE public.channel_work_policies IS '채널 + 작품 권리사 검수 정책 — 있으면 레이블리 작품 정책을 덮는다(검수 흐름 0120 _tikitaka_review_ctx)';
ALTER TABLE public.channel_work_policies ENABLE ROW LEVEL SECURITY;
CREATE POLICY channel_work_policies_read ON public.channel_work_policies FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.channel_work_policies TO authenticated;

INSERT INTO public.channel_work_policies(token_slug, work_title, inspection_policy, note, updated_by)
VALUES ('JAEMISHOTS', '로또 1등도 출근합니다', 'none', '재미쇼츠는 권리사 검수 없이 내부 승인만(2026-10-02 사용자 지시)', NULL);

CREATE OR REPLACE FUNCTION public.set_channel_work_policy(p_slug text, p_work text, p_policy text, p_note text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF p_policy IS NULL OR p_policy = '' THEN
    DELETE FROM public.channel_work_policies WHERE token_slug = p_slug AND work_title = p_work;   -- 작품 정책을 따른다
  ELSE
    IF p_policy NOT IN ('required','none','unaired_only') THEN RAISE EXCEPTION '모르는 검수 정책: %', p_policy; END IF;
    INSERT INTO public.channel_work_policies(token_slug, work_title, inspection_policy, note, updated_by, updated_at)
    VALUES (p_slug, p_work, p_policy, nullif(btrim(coalesce(p_note,'')), ''), auth.uid(), now())
    ON CONFLICT (token_slug, work_title) DO UPDATE SET inspection_policy = EXCLUDED.inspection_policy, note = EXCLUDED.note,
      updated_by = auth.uid(), updated_at = now();
  END IF;
  PERFORM public._audit('set_channel_work_policy', 'channel_work_policies', p_slug || ':' || p_work,
          jsonb_build_object('policy', p_policy, 'note', p_note));
END $$;
REVOKE ALL ON FUNCTION public.set_channel_work_policy(text, text, text, text) FROM public, anon;
GRANT EXECUTE ON FUNCTION public.set_channel_work_policy(text, text, text, text) TO authenticated;

-- 검수 흐름 공용 맥락 — 0120 과 같고 채널 + 작품 정책으로 덮는 세 줄만 더했다
CREATE OR REPLACE FUNCTION public._tikitaka_review_ctx(p_video uuid, p_based_on text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record; ch record; w record; a record; n int; pol text;
BEGIN
 SELECT id, work_order_id, node_id, suffix, channel_slug, work_title, episode, render_fingerprint INTO v
   FROM public.tikitaka_videos WHERE id = p_video FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION '없는 영상이에요'; END IF;
 IF v.render_fingerprint IS DISTINCT FROM p_based_on THEN
  RAISE EXCEPTION '화면을 연 뒤에 영상이 새로 만들어졌어요. 새로고침한 뒤 다시 해 주세요';
 END IF;
 IF EXISTS (SELECT 1 FROM public.job_queue WHERE kind = 'tikitaka_apply_edit' AND params->>'video_id' = p_video::text
              AND status IN ('pending','running')) THEN
  RAISE EXCEPTION '이 영상을 다시 렌더하는 중이에요. 끝나면 새 판에서 검수해 주세요';
 END IF;
 SELECT token_slug, name, channel_id, gcp_project INTO ch FROM public.channels_mirror WHERE token_slug = v.channel_slug;
 IF NOT FOUND OR ch.channel_id IS NULL THEN RAISE EXCEPTION '이 영상의 채널을 찾지 못했어요. 채널 관리에서 채널을 확인해 주세요'; END IF;
 SELECT count(*) INTO n FROM public.laeebly_works WHERE title = v.work_title;
 IF n <> 1 THEN RAISE EXCEPTION '레이블리 작품을 하나로 찾지 못했어요(같은 제목 %개). 작품 관리에서 작품 이름을 확인해 주세요', n; END IF;
 SELECT id, title, inspection_policy, company, geo_block_required INTO w FROM public.laeebly_works WHERE title = v.work_title;
 -- 채널 + 작품 검수 정책(0126)이 있으면 레이블리 작품 정책을 덮는다(예: 재미쇼츠 × 로또 — 권리사 검수 없이 바로 예약)
 SELECT inspection_policy INTO pol FROM public.channel_work_policies WHERE token_slug = ch.token_slug AND work_title = v.work_title;
 IF FOUND THEN w.inspection_policy := pol; END IF;
 SELECT id, status, rejected_bool INTO a FROM public.laeebly_applications
  WHERE video_id = w.id AND youtube_channel_id = ch.channel_id ORDER BY synced_at DESC LIMIT 1;
 RETURN jsonb_build_object('video', to_jsonb(v), 'channel', to_jsonb(ch), 'work', to_jsonb(w), 'application', to_jsonb(a));
END $$;
REVOKE ALL ON FUNCTION public._tikitaka_review_ctx(uuid, text) FROM public, anon, authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0126','claude (채널 + 작품 권리사 검수 정책)');
