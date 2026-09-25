-- 작품(원작 드라마·예능) 공개 일정 — VES Workspace 발행 일정 화면에서 사람이 입력한다.
-- 우리가 만든 쇼츠의 예약 발행과는 별개다. 작품은 레이블리 licensed_video.id(별도 DB라 FK 없음)와
-- 입력 시점 제목을 함께 남긴다(제목 유사도로 작품을 추정하지 않는다).
-- 매주 반복으로 여러 회차를 한 번에 만들면 같은 series_id 를 공유한다 — 회차마다 따로 고칠 수 있다.
CREATE TABLE public.work_release_schedule (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_id text NOT NULL CHECK (length(work_id) BETWEEN 1 AND 100),
 work_title text NOT NULL CHECK (length(work_title) BETWEEN 1 AND 300),
 episode_label text CHECK (episode_label IS NULL OR length(episode_label) BETWEEN 1 AND 40),
 episode_no integer CHECK (episode_no IS NULL OR episode_no BETWEEN 0 AND 10000),
 release_at timestamptz NOT NULL,
 platform text CHECK (platform IS NULL OR length(platform) BETWEEN 1 AND 60),
 status text NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','delayed','cancelled','released')),
 note text CHECK (note IS NULL OR length(note) <= 1000),
 series_id uuid,
 created_by uuid NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_by uuid REFERENCES auth.users(id),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX work_release_schedule_release_at ON public.work_release_schedule(release_at);
CREATE INDEX work_release_schedule_work ON public.work_release_schedule(work_id,release_at);
CREATE INDEX work_release_schedule_series ON public.work_release_schedule(series_id) WHERE series_id IS NOT NULL;

-- 누가·언제는 서버가 찍는다(브라우저가 보낸 값은 쓰지 않는다). service_role 은 auth.uid() 가 없어 보낸 값을 둔다.
CREATE FUNCTION public.work_release_schedule_stamp() RETURNS trigger
 LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
 IF TG_OP = 'INSERT' THEN
  NEW.created_by := COALESCE(auth.uid(), NEW.created_by);
  NEW.created_at := now();
  NEW.updated_by := NULL;
 ELSE
  NEW.created_by := OLD.created_by;
  NEW.created_at := OLD.created_at;
  NEW.updated_by := COALESCE(auth.uid(), NEW.updated_by);
 END IF;
 NEW.updated_at := now();
 RETURN NEW;
END $$;
CREATE TRIGGER work_release_schedule_stamp BEFORE INSERT OR UPDATE ON public.work_release_schedule
 FOR EACH ROW EXECUTE FUNCTION public.work_release_schedule_stamp();

ALTER TABLE public.work_release_schedule ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.work_release_schedule FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.work_release_schedule TO authenticated;
GRANT ALL ON public.work_release_schedule TO service_role;
-- 읽기: VES 역할이 등록된 사람 전부. 쓰기: 운영자·관리자(작품 에셋 업로드와 같은 기준).
CREATE POLICY work_release_read ON public.work_release_schedule FOR SELECT TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('viewer','reviewer','operator','admin')));
CREATE POLICY work_release_insert ON public.work_release_schedule FOR INSERT TO authenticated
 WITH CHECK (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')));
CREATE POLICY work_release_update ON public.work_release_schedule FOR UPDATE TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')))
 WITH CHECK (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')));
CREATE POLICY work_release_delete ON public.work_release_schedule FOR DELETE TO authenticated
 USING (EXISTS (SELECT 1 FROM public.user_roles WHERE user_id=(SELECT auth.uid()) AND role IN ('operator','admin')));
