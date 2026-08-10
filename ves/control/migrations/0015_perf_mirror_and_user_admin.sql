-- 0015: 성과 미러(laeebly youtube_*_snapshot → 관제 직결) + 사용자 권한 관리(admin 전용)
-- (2026-08-10 사용자 요청: "성과 페이지는 youtube_video_snapshot 및 관련 테이블들을 통해",
--  "권한 설정 변경 기능은 어드민한테만")
-- laeebly 는 계속 읽기 전용 — perf_sync(스케줄러, 매시간)가 우리 채널분만 여기로 복사한다.

-- ① 성과 미러 3종
CREATE TABLE IF NOT EXISTS public.perf_video_map (
    content_id   text PRIMARY KEY,
    channel_id   text NOT NULL,
    title        text,
    work_title   text,                -- licensed_video_title
    published_at timestamptz,
    dead_at      timestamptz,
    synced_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS perf_video_map_channel ON public.perf_video_map (channel_id);

CREATE TABLE IF NOT EXISTS public.perf_video_snapshot (
    content_id    text NOT NULL,
    snapshot_date date NOT NULL,
    view_count    bigint,
    like_count    bigint,
    comment_count bigint,
    PRIMARY KEY (content_id, snapshot_date)
);
CREATE INDEX IF NOT EXISTS perf_video_snapshot_date ON public.perf_video_snapshot (snapshot_date);

CREATE TABLE IF NOT EXISTS public.perf_channel_snapshot (
    channel_id       text NOT NULL,
    snapshot_date    date NOT NULL,
    subscriber_count bigint,
    view_count       bigint,
    video_count      bigint,
    PRIMARY KEY (channel_id, snapshot_date)
);

ALTER TABLE public.perf_video_map      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.perf_video_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.perf_channel_snapshot ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS pvm_read ON public.perf_video_map;
DROP POLICY IF EXISTS pvs_read ON public.perf_video_snapshot;
DROP POLICY IF EXISTS pcs_read ON public.perf_channel_snapshot;
CREATE POLICY pvm_read ON public.perf_video_map      FOR SELECT TO authenticated USING (true);
CREATE POLICY pvs_read ON public.perf_video_snapshot FOR SELECT TO authenticated USING (true);
CREATE POLICY pcs_read ON public.perf_channel_snapshot FOR SELECT TO authenticated USING (true);
-- 쓰기는 service key(perf_sync)만 — authenticated 정책 없음

-- ② 사용자 권한 관리 (admin 전용) — 목록·변경 모두 RPC 로만
CREATE OR REPLACE FUNCTION public.list_user_roles()
RETURNS TABLE(user_id uuid, email text, role text, note text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text;
BEGIN
    SELECT r.role INTO v_role FROM public.user_roles r WHERE r.user_id = auth.uid();
    IF v_role IS DISTINCT FROM 'admin' THEN
        RAISE EXCEPTION 'admin 권한 필요';
    END IF;
    RETURN QUERY
    SELECT u.id, u.email::text, coalesce(r.role, 'viewer'), r.note
      FROM auth.users u LEFT JOIN public.user_roles r ON r.user_id = u.id
     ORDER BY u.email;
END $$;
REVOKE ALL ON FUNCTION public.list_user_roles() FROM public;
GRANT EXECUTE ON FUNCTION public.list_user_roles() TO authenticated;

CREATE OR REPLACE FUNCTION public.set_user_role(p_email text, p_role text, p_note text DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_role text; v_target uuid;
BEGIN
    SELECT r.role INTO v_role FROM public.user_roles r WHERE r.user_id = auth.uid();
    IF v_role IS DISTINCT FROM 'admin' THEN
        RAISE EXCEPTION 'admin 권한 필요';
    END IF;
    IF p_role NOT IN ('viewer','reviewer','operator','admin') THEN
        RAISE EXCEPTION '허용 역할: viewer/reviewer/operator/admin';
    END IF;
    SELECT id INTO v_target FROM auth.users WHERE lower(email) = lower(p_email);
    IF v_target IS NULL THEN
        RAISE EXCEPTION '없는 사용자: % (먼저 Supabase Auth 에 가입돼 있어야 합니다)', p_email;
    END IF;
    IF v_target = auth.uid() THEN
        RAISE EXCEPTION '자기 자신의 권한은 여기서 바꿀 수 없습니다(잠금 사고 방지)';
    END IF;
    INSERT INTO public.user_roles (user_id, role, note)
    VALUES (v_target, p_role, p_note)
    ON CONFLICT (user_id) DO UPDATE SET role = EXCLUDED.role,
        note = coalesce(EXCLUDED.note, public.user_roles.note);
    RETURN jsonb_build_object('email', p_email, 'role', p_role);
END $$;
REVOKE ALL ON FUNCTION public.set_user_role(text, text, text) FROM public;
GRANT EXECUTE ON FUNCTION public.set_user_role(text, text, text) TO authenticated;
