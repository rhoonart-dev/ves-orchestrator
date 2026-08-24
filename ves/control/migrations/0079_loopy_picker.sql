-- =====================================================================
-- 0079_loopy_picker.sql — 소재 선별기 설정·RPC (L-P3b, 2026-08-23)
--
-- 발주서: docs/LOCALIZE_UNIFY.md §5-6. 판정 열은 0078 이 이미 열어 뒀다
-- (score·scores·flags·block_reason·allowed_by·dup_of). 여기서 더하는 것은
-- ① 차단 목록·선별기 설정 ② 대시보드가 쓸 조회·기록 RPC 다.
--
-- 🛑 발행은 어느 자동화 수준에서도 사람이다. 폐기한 auto_approve 는 **발행 승인**
--    자동화였고, 되살아나는 것은 **선별**뿐이다(§5-6 자동화 수준 표).
-- =====================================================================

INSERT INTO public.ops_config(key, value, note) VALUES
 ('loopy_picker',
  '{"enabled": false, "channel_slug": "LOOPY", "per_day": 1, "top_n": 5, "automation": "auto"}',
  '소재 선별기(L-P3b) — automation: manual(추천만) | assist(제안) | auto(체인까지). '
  '어느 값이든 발행 승인은 사람. enabled=false 면 추천을 만들지 않는다'),
 ('loopy_denylist', '[]',
  '사람이 관리하는 차단 목록(JSON 배열) — 제목에 이 문구가 있으면 후보에서 뺀다. '
  '가장 신뢰도가 높은 규칙이라 LLM 이 못 푼다')
ON CONFLICT (key) DO NOTHING;

-- ── 아카이브 조회 (대시보드) ────────────────────────────────────────────
-- 추천(위)과 전량 아카이브(아래)를 한 화면이 쓴다. 제외된 편도 **사유와 함께**
-- 볼 수 있어야 한다 — '왜 이 편은 안 뜨지'가 답변 가능해야 한다(§5-6).
CREATE OR REPLACE FUNCTION public.list_external_shorts(
    p_channel text DEFAULT 'LOOPY',
    p_kind    text DEFAULT 'short',
    p_filter  text DEFAULT 'all',      -- all | available | blocked | published | recommended
    p_sort    text DEFAULT 'score',    -- score | views | newest | oldest
    p_limit   int  DEFAULT 60,
    p_offset  int  DEFAULT 0)
 RETURNS TABLE (video_id text, title text, url text, thumbnail_url text,
                duration_sec double precision, view_count bigint, like_count bigint,
                published_at timestamptz, state text, score double precision,
                scores jsonb, flags jsonb, block_reason text, allowed_by text,
                dup_of text, youtube_id text, total bigint)
 LANGUAGE sql STABLE SECURITY DEFINER SET search_path TO 'public'
AS $function$
    WITH base AS (
        SELECT e.* FROM public.external_shorts e
         WHERE e.channel_slug = p_channel
           AND e.kind = coalesce(p_kind, 'short')
           AND CASE coalesce(p_filter,'all')
                 -- 'scored'(오늘의 추천)도 고를 수 있는 편이다 — 빼면 추천이
                 -- '고를 수 있는' 목록에서 사라져 두 탭이 서로를 부정한다.
                 WHEN 'available' THEN e.state IN ('discovered','scored') AND e.dup_of IS NULL
                                       AND e.youtube_id IS NULL
                                       AND (e.block_reason IS NULL OR e.allowed_by IS NOT NULL)
                 WHEN 'blocked'   THEN e.block_reason IS NOT NULL AND e.allowed_by IS NULL
                 WHEN 'published' THEN e.youtube_id IS NOT NULL OR e.state = 'uploaded'
                 WHEN 'recommended' THEN e.score IS NOT NULL AND e.state = 'scored'
                 ELSE true END
    )
    SELECT b.video_id, b.title, b.url, b.thumbnail_url, b.duration_sec,
           b.view_count, b.like_count, b.published_at, b.state, b.score,
           b.scores, b.flags, b.block_reason, b.allowed_by, b.dup_of, b.youtube_id,
           count(*) OVER () AS total
      FROM base b
     ORDER BY CASE WHEN p_sort = 'views'  THEN b.view_count END DESC NULLS LAST,
              CASE WHEN p_sort = 'newest' THEN b.published_at END DESC NULLS LAST,
              CASE WHEN p_sort = 'oldest' THEN b.published_at END ASC NULLS LAST,
              CASE WHEN p_sort = 'score'  THEN b.score END DESC NULLS LAST,
              b.video_id
     LIMIT greatest(1, least(coalesce(p_limit, 60), 200)) OFFSET greatest(0, coalesce(p_offset, 0));
$function$;

-- ── 사람이 차단을 뒤집거나 직접 제외한다 ────────────────────────────────
-- ⚠ 게이트 0(이미 발행·내용 중복)은 **뒤집을 수 없다** — 이미 올린 것을 또 올릴 수는 없다.
--   내용 중복은 오탐일 수 있으므로 dup_of 해제만 따로 허용한다(p_clear_dup).
CREATE OR REPLACE FUNCTION public.set_external_short_allow(
    p_video_id text, p_allow boolean, p_note text DEFAULT NULL,
    p_clear_dup boolean DEFAULT false)
 RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path TO 'public'
AS $function$
DECLARE v_row record;
BEGIN
    IF NOT public.has_role(auth.uid(),'reviewer') THEN
        RAISE EXCEPTION 'reviewer 권한 필요';
    END IF;
    SELECT * INTO v_row FROM public.external_shorts WHERE video_id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION '아카이브에 없는 영상입니다: %', p_video_id; END IF;
    IF v_row.state = 'uploaded' OR v_row.youtube_id IS NOT NULL THEN
        RAISE EXCEPTION '이미 발행된 영상입니다 — 되살릴 수 없습니다 (%)', p_video_id;
    END IF;

    UPDATE public.external_shorts
       SET allowed_by = CASE WHEN p_allow THEN coalesce(auth.email(), auth.uid()::text) END,
           state      = CASE WHEN p_allow THEN state ELSE 'skipped' END,
           dup_of     = CASE WHEN p_clear_dup THEN NULL ELSE dup_of END,
           notes      = coalesce(p_note, notes)
     WHERE video_id = p_video_id;

    PERFORM public._audit('external_short_allow','external_shorts', p_video_id,
        jsonb_build_object('allow', p_allow, 'clear_dup', p_clear_dup, 'note', p_note));
    RETURN jsonb_build_object('video_id', p_video_id, 'allow', p_allow,
                              'dup_cleared', p_clear_dup);
END $function$;

REVOKE ALL     ON FUNCTION public.list_external_shorts(text,text,text,text,int,int) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.list_external_shorts(text,text,text,text,int,int) TO authenticated;
REVOKE ALL     ON FUNCTION public.set_external_short_allow(text,boolean,text,boolean) FROM public, anon;
GRANT  EXECUTE ON FUNCTION public.set_external_short_allow(text,boolean,text,boolean) TO authenticated;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0079','claude (0079 소재 선별기 설정·RPC — L-P3b)')
ON CONFLICT DO NOTHING;
