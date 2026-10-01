-- 0121 유튜브 원천 여러 채널 · 합본 · 작업 번호(2026-10-01)
-- 유튜브 클립으로 만드는 작품(로또 1등도 출근합니다 · 놀라운 토요일 등)을 소스 창고에서 같은 규칙으로 다룬다.
--  · work_youtube_sources: 작품마다 클립을 모을 채널·재생목록 여러 개. rank 1 이 먼저(티빙 우선) — 아래 채널 클립은
--    위 채널과 같은 장면을 잘라내고 남은 부분만 합본에 들어간다(맥미니 youtube_overlap 이 sources.overlap 에 적는다).
--  · sources 에 클립 종류(본편 클립 · 선공개 · 몰아보기 · 합본)와 회차 표기('5-6')를 더한다.
--  · source_compilations: 합본 하나 = 구성 기록(어떤 클립을 어느 구간 · 어떤 순서로) + 만든 원본(sources 한 줄).
--    합본은 원본이라 번호가 없다. 맥미니 build_compilation 잡이 만든다.
--  · tikitaka_tasks: 작업 하나 = 원본 하나 + 채널 하나. 번호(work_no)는 작품 + 회차 안에서 1, 2, 3… 지운 번호는 다시 안 쓴다.
--    '저장'은 시작 전(draft)으로 남기고, 시작하면 work_orders + 잡 체인을 건다(0111 order_tikitaka_run 과 같은 체인).

-- ── 작품별 유튜브 원천 ─────────────────────────────────────────────
CREATE TABLE public.work_youtube_sources (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_title text NOT NULL CHECK (length(work_title) BETWEEN 1 AND 200),
 rank smallint NOT NULL CHECK (rank BETWEEN 1 AND 20),
 channel_id uuid REFERENCES public.source_channels(id) ON DELETE SET NULL,
 url text NOT NULL CHECK (url ~ '^https://(www\.)?youtube\.com/'),
 label text CHECK (label IS NULL OR length(label) <= 100),
 title_filter text CHECK (title_filter IS NULL OR length(title_filter) <= 200),
 episode_regex text CHECK (episode_regex IS NULL OR length(episode_regex) <= 300),
 exclude_regex text CHECK (exclude_regex IS NULL OR length(exclude_regex) <= 300),
 is_active boolean NOT NULL DEFAULT true,
 last_checked_at timestamptz, last_found integer, last_error text,
 updated_by uuid DEFAULT auth.uid(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (work_title, url),
 UNIQUE (work_title, rank) DEFERRABLE INITIALLY DEFERRED
);
COMMENT ON COLUMN public.work_youtube_sources.label IS '채널 목록에 없는 원천(재생목록 등)의 표시 이름 — 클립 모으기가 올린 채널 이름으로 채운다';
COMMENT ON TABLE public.work_youtube_sources IS '작품별 유튜브 원천(채널 /videos · 재생목록) — rank 1 이 먼저. 맥미니가 하루 한 번 새 클립을 sources 로 모은다';
ALTER TABLE public.work_youtube_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY work_youtube_sources_read ON public.work_youtube_sources FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.work_youtube_sources TO authenticated;

-- 종전 작품 카드의 원천 하나를 1순위로 옮긴다(채널 목록에 있으면 그 채널로 묶는다)
INSERT INTO public.work_youtube_sources(work_title, rank, channel_id, url, title_filter, episode_regex, exclude_regex, updated_by)
SELECT wc.work_title, 1,
       (SELECT sc.id FROM public.source_channels sc
         WHERE wc.playlist_url = sc.url OR wc.playlist_url LIKE sc.url || '/%' LIMIT 1),
       wc.playlist_url, nullif(wc.title_filter, ''), nullif(wc.title_episode_regex, ''), nullif(wc.title_exclude_regex, ''), NULL
  FROM public.work_cards wc
 WHERE wc.playlist_url ~ '^https://(www\.)?youtube\.com/';

-- ── 작품 카드: 회차 단위 글자 · 합본/작업 기본값 ──────────────────────
ALTER TABLE public.work_cards
 ADD COLUMN episode_unit text NOT NULL DEFAULT '화' CHECK (episode_unit IN ('화','회','회차')),
 ADD COLUMN compile_group smallint NOT NULL DEFAULT 1 CHECK (compile_group IN (1, 2)),
 ADD COLUMN compile_recap boolean NOT NULL DEFAULT false,
 ADD COLUMN task_prev_ref boolean NOT NULL DEFAULT false;
COMMENT ON COLUMN public.work_cards.compile_group IS '한 합본에 넣을 회차 — 1회씩 · 2회씩(티빙에서 두 편씩 나오는 드라마)';
COMMENT ON COLUMN public.work_cards.compile_recap IS '합본에 앞 회차 몰아보기를 넣는다(밑 화면 전용)';
COMMENT ON COLUMN public.work_cards.task_prev_ref IS '작업할 때 앞 회차 작업의 대본 요약을 같이 넘긴다';
UPDATE public.work_cards SET episode_unit = '회' WHERE work_title = '놀라운 토요일';
UPDATE public.work_cards SET compile_group = 2, compile_recap = true, task_prev_ref = true WHERE work_title = '로또 1등도 출근합니다';

-- ── 클립 종류 · 회차 표기 · 겹침 ─────────────────────────────────────
ALTER TABLE public.sources
 ADD COLUMN clip_kind text NOT NULL DEFAULT 'clip' CHECK (clip_kind IN ('clip','prerelease','recap','extra','compilation')),
 ADD COLUMN episode_label text CHECK (episode_label IS NULL OR episode_label ~ '^\d{1,4}(-\d{1,4})?$'),
 ADD COLUMN yt_source_id uuid REFERENCES public.work_youtube_sources(id) ON DELETE SET NULL,
 ADD COLUMN overlap jsonb;
COMMENT ON COLUMN public.sources.clip_kind IS 'clip 본편 클립 · prerelease 선공개 · recap 몰아보기 · extra 비하인드·예고 등 · compilation 합본(맥미니가 만든 원본)';
COMMENT ON COLUMN public.sources.episode_label IS '여러 회차를 덮는 것의 회차 표기 — 선공개·몰아보기 제목의 5-6화, 합본의 5-6. 한 회차면 비워 두고 episode 를 쓴다';
COMMENT ON COLUMN public.sources.overlap IS '위 순위 채널 클립과 겹치는 구간 {checked_at, covered:[{start,end,by}], keep:[[s,e]], skip, reason} — youtube_overlap 이 적는다';

-- ── 합본 ──────────────────────────────────────────────────────────
CREATE TABLE public.source_compilations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_title text NOT NULL,
 episode_key text NOT NULL CHECK (episode_key ~ '^\d{1,4}(-\d{1,4})?$'),
 name text NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
 recipe jsonb NOT NULL,
 notes text,
 status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','building','ready','failed','deleted')),
 progress text, error text,
 source_id uuid REFERENCES public.sources(id) ON DELETE SET NULL,
 duration_sec numeric, clip_count integer,
 job_id uuid,
 created_by uuid DEFAULT auth.uid() REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 done_at timestamptz
);
CREATE INDEX source_compilations_work ON public.source_compilations(work_title, episode_key);
COMMENT ON TABLE public.source_compilations IS '합본 — recipe{items:[{source_id, video_id, kind, episode, label, start, end}], options{group, recap}} 대로 맥미니가 이어 붙여 sources(clip_kind=compilation)로 등록';
ALTER TABLE public.source_compilations ENABLE ROW LEVEL SECURITY;
CREATE POLICY source_compilations_read ON public.source_compilations FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.source_compilations TO authenticated;
ALTER TABLE public.sources ADD COLUMN compilation_id uuid REFERENCES public.source_compilations(id) ON DELETE SET NULL;

-- ── 작업(번호) ─────────────────────────────────────────────────────
CREATE TABLE public.tikitaka_tasks (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 work_title text NOT NULL,
 episode_key text NOT NULL CHECK (episode_key ~ '^\d{1,4}(-\d{1,4})?$'),
 work_no integer NOT NULL CHECK (work_no BETWEEN 1 AND 9999),
 source_id uuid NOT NULL REFERENCES public.sources(id),
 compilation_id uuid REFERENCES public.source_compilations(id) ON DELETE SET NULL,
 channel_slug text NOT NULL,
 options jsonb NOT NULL DEFAULT '{}'::jsonb,
 status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','queued','deleted')),
 work_order_id uuid REFERENCES public.work_orders(id) ON DELETE SET NULL,
 after_task uuid REFERENCES public.tikitaka_tasks(id) ON DELETE SET NULL,
 created_by uuid DEFAULT auth.uid() REFERENCES auth.users(id),
 created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE (work_title, episode_key, work_no)
);
CREATE INDEX tikitaka_tasks_source ON public.tikitaka_tasks(source_id);
CREATE UNIQUE INDEX tikitaka_tasks_wo ON public.tikitaka_tasks(work_order_id) WHERE work_order_id IS NOT NULL;
COMMENT ON TABLE public.tikitaka_tasks IS '작업 — 원본 하나 + 채널 하나. 번호는 작품 + 회차 안에서 차례로(지운 번호는 다시 안 씀). options{count, prev_ref, avoid_other, memo, args}';
ALTER TABLE public.tikitaka_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tikitaka_tasks_read ON public.tikitaka_tasks FOR SELECT TO authenticated
 USING (public.has_role((SELECT auth.uid()), 'viewer'));
GRANT SELECT ON public.tikitaka_tasks TO authenticated;

-- 이미 건 새 방식 작업은 번호를 매겨 둔다(회차 = 작업지시의 회차)
INSERT INTO public.tikitaka_tasks(work_title, episode_key, work_no, source_id, channel_slug, options, status,
                                  work_order_id, created_by, created_at, started_at)
SELECT w.work_title, w.episode::text,
       row_number() OVER (PARTITION BY w.work_title, w.episode ORDER BY w.created_at),
       s.id, w.channel_slug,
       jsonb_strip_nulls(jsonb_build_object('count', w.knob_config->'count', 'args', w.knob_config->'args',
                                            'memo', w.knob_config->>'note')),
       'queued', w.id, NULL, w.created_at, w.created_at
  FROM public.work_orders w
  JOIN LATERAL (SELECT id FROM public.sources s
                 WHERE (w.source_sha256 IS NOT NULL AND s.sha256 = w.source_sha256)
                    OR (w.source_sha256 IS NULL AND s.source_url = w.source_url)
                 ORDER BY s.created_at LIMIT 1) s ON true
 WHERE w.pipeline = 'tikitaka_grid' AND w.episode IS NOT NULL;

-- ── 쓰기 RPC ──────────────────────────────────────────────────────
-- 작품의 유튜브 원천 목록을 통째로 바꾼다. p_items 순서가 곧 순위. 정규식은 여기서 한 번 돌려 본다(틀리면 저장 안 됨).
CREATE OR REPLACE FUNCTION public.set_work_youtube_sources(p_work text, p_items jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_it jsonb; v_rank int := 0; v_url text; v_keep text[] := '{}'; v_ch uuid; v_re text;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF coalesce(btrim(p_work), '') = '' THEN RAISE EXCEPTION '작품을 골라 주세요'; END IF;
  IF jsonb_typeof(coalesce(p_items, '[]'::jsonb)) <> 'array' THEN RAISE EXCEPTION '원천 목록이 이상해요'; END IF;
  IF jsonb_array_length(coalesce(p_items, '[]'::jsonb)) > 20 THEN RAISE EXCEPTION '원천은 20개까지 둘 수 있어요'; END IF;
  FOR v_it IN SELECT * FROM jsonb_array_elements(coalesce(p_items, '[]'::jsonb)) LOOP
    v_rank := v_rank + 1;
    v_url := btrim(coalesce(v_it->>'url', ''));
    v_ch := nullif(v_it->>'channel_id', '')::uuid;
    IF v_url = '' AND v_ch IS NOT NULL THEN
      SELECT url || '/videos' INTO v_url FROM public.source_channels WHERE id = v_ch;
    END IF;
    IF v_url !~ '^https://(www\.)?youtube\.com/' THEN RAISE EXCEPTION '유튜브 주소가 아니에요: %', v_url; END IF;
    FOREACH v_re IN ARRAY ARRAY[v_it->>'episode_regex', v_it->>'exclude_regex'] LOOP
      IF coalesce(v_re, '') <> '' THEN
        BEGIN PERFORM 'x' ~ v_re; EXCEPTION WHEN others THEN RAISE EXCEPTION '회차 읽는 규칙이 이상해요: %', v_re; END;
      END IF;
    END LOOP;
    INSERT INTO public.work_youtube_sources AS w (work_title, rank, channel_id, url, label, title_filter, episode_regex, exclude_regex, updated_by, updated_at)
    VALUES (p_work, v_rank, v_ch, v_url, nullif(btrim(v_it->>'label'), ''), nullif(btrim(v_it->>'title_filter'), ''), nullif(v_it->>'episode_regex', ''),
            nullif(v_it->>'exclude_regex', ''), auth.uid(), now())
    ON CONFLICT (work_title, url) DO UPDATE SET rank = EXCLUDED.rank, channel_id = EXCLUDED.channel_id,
      label = coalesce(EXCLUDED.label, w.label),
      title_filter = EXCLUDED.title_filter, episode_regex = EXCLUDED.episode_regex, exclude_regex = EXCLUDED.exclude_regex,
      is_active = true, updated_by = auth.uid(), updated_at = now();
    v_keep := v_keep || v_url;
  END LOOP;
  DELETE FROM public.work_youtube_sources WHERE work_title = p_work AND NOT (url = ANY (v_keep));
  PERFORM public._audit('set_work_youtube_sources', 'work_cards', p_work, jsonb_build_object('items', p_items));
  RETURN v_rank;
END $$;

-- 작품 기본값(회차 단위 글자 · 한 합본에 넣을 회차 · 몰아보기 · 앞 회차 참고). 넘기지 않은 값은 그대로.
CREATE OR REPLACE FUNCTION public.set_work_compile_defaults(p_work text, p_unit text DEFAULT NULL,
  p_group integer DEFAULT NULL, p_recap boolean DEFAULT NULL, p_prev_ref boolean DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  INSERT INTO public.work_cards(work_title, updated_by, updated_at) VALUES (p_work, auth.uid()::text, now())
  ON CONFLICT (work_title) DO NOTHING;
  UPDATE public.work_cards SET
    episode_unit = coalesce(p_unit, episode_unit), compile_group = coalesce(p_group, compile_group),
    compile_recap = coalesce(p_recap, compile_recap), task_prev_ref = coalesce(p_prev_ref, task_prev_ref),
    updated_by = auth.uid()::text, updated_at = now()
  WHERE work_title = p_work;
  PERFORM public._audit('set_work_compile_defaults', 'work_cards', p_work,
          jsonb_build_object('unit', p_unit, 'group', p_group, 'recap', p_recap, 'prev_ref', p_prev_ref));
END $$;

-- 합본 만들기 — 구성(recipe)을 적고 맥미니 build_compilation 잡을 건다.
-- recipe.items: [{source_id, start, end}] 순서대로. 구간은 클립 안 초(비우면 통째). 나머지 표시용 값(kind·label)은 서버가 채운다.
CREATE OR REPLACE FUNCTION public.request_source_compilation(p_work text, p_episode_key text, p_name text,
  p_items jsonb, p_options jsonb DEFAULT '{}'::jsonb)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_id uuid; v_it jsonb; v_src record; v_items jsonb := '[]'::jsonb; v_job uuid; v_s numeric; v_e numeric;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF p_episode_key !~ '^\d{1,4}(-\d{1,4})?$' THEN RAISE EXCEPTION '회차 표기가 이상해요: %', p_episode_key; END IF;
  IF jsonb_typeof(coalesce(p_items, 'null')) <> 'array' OR jsonb_array_length(p_items) = 0 THEN
    RAISE EXCEPTION '합본에 넣을 클립을 골라 주세요';
  END IF;
  IF jsonb_array_length(p_items) > 60 THEN RAISE EXCEPTION '클립은 60개까지 넣을 수 있어요'; END IF;
  FOR v_it IN SELECT * FROM jsonb_array_elements(p_items) LOOP
    SELECT s.*, w.rank AS yt_rank INTO v_src FROM public.sources s
      LEFT JOIN public.work_youtube_sources w ON w.id = s.yt_source_id
     WHERE s.id = (v_it->>'source_id')::uuid;
    IF NOT FOUND OR v_src.work_title <> p_work THEN RAISE EXCEPTION '이 작품의 클립이 아니에요: %', v_it->>'source_id'; END IF;
    IF v_src.clip_kind = 'compilation' THEN RAISE EXCEPTION '합본을 다시 합본에 넣을 수는 없어요'; END IF;
    IF v_src.source_url IS NULL AND v_src.object_key IS NULL THEN RAISE EXCEPTION '받을 곳이 없는 클립이에요: %', v_src.title; END IF;
    v_s := nullif(v_it->>'start', '')::numeric; v_e := nullif(v_it->>'end', '')::numeric;
    IF v_s IS NOT NULL AND v_e IS NOT NULL AND v_e - v_s < 1 THEN RAISE EXCEPTION '구간이 너무 짧아요: %', v_src.title; END IF;
    v_items := v_items || jsonb_build_object('source_id', v_src.id, 'source_url', v_src.source_url, 'sha256', v_src.sha256,
               'object_key', v_src.object_key, 'title', v_src.title, 'kind', v_src.clip_kind, 'episode', v_src.episode,
               'label', v_src.episode_label, 'duration', v_src.duration_sec, 'published', v_src.published_ts,
               'rank', v_src.yt_rank, 'start', v_s, 'end', v_e);
  END LOOP;
  INSERT INTO public.source_compilations(work_title, episode_key, name, recipe, clip_count, created_by)
  VALUES (p_work, p_episode_key, btrim(p_name), jsonb_build_object('items', v_items, 'options', coalesce(p_options, '{}'::jsonb)),
          jsonb_array_length(v_items), auth.uid())
  RETURNING id INTO v_id;
  INSERT INTO public.job_queue(kind, params, idempotency_key, required_caps, lease_ttl_sec, priority)
  VALUES ('build_compilation', jsonb_build_object('compilation_id', v_id, 'work_title', p_work, 'episode_key', p_episode_key),
          'compile:' || v_id::text, ARRAY['network','analyze'], 300, 160)
  RETURNING id INTO v_job;
  UPDATE public.source_compilations SET job_id = v_job WHERE id = v_id;
  PERFORM public._audit('request_source_compilation', 'source_compilations', v_id::text,
          jsonb_build_object('work', p_work, 'episode', p_episode_key, 'name', p_name, 'clips', jsonb_array_length(v_items)));
  RETURN v_id;
END $$;

-- 작업 설정 확인 — 모르는 키 거절, 값 모양 확인. 반환은 정리한 options.
CREATE OR REPLACE FUNCTION public._tikitaka_task_options(p jsonb) RETURNS jsonb LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_bad text; v_cnt int;
  c_keys constant text[] := ARRAY['count','prev_ref','avoid_other','memo','args'];
  c_args constant text[] := ARRAY['design_preset','style_preset','script_flow','voice','speed','copy',
                                  'copy_pos','logo_width','range','pov','cover_cut_guard','stt'];
BEGIN
  p := coalesce(p, '{}'::jsonb);
  IF jsonb_typeof(p) <> 'object' THEN RAISE EXCEPTION '작업 설정이 이상해요'; END IF;
  SELECT k INTO v_bad FROM jsonb_object_keys(p) k WHERE NOT (k = ANY (c_keys)) LIMIT 1;
  IF v_bad IS NOT NULL THEN RAISE EXCEPTION '모르는 작업 설정: %', v_bad; END IF;
  IF p ? 'args' THEN
    IF jsonb_typeof(p->'args') <> 'object' THEN RAISE EXCEPTION '엔진 설정은 JSON 객체여야 해요'; END IF;
    SELECT k INTO v_bad FROM jsonb_object_keys(p->'args') k WHERE NOT (k = ANY (c_args)) LIMIT 1;
    IF v_bad IS NOT NULL THEN RAISE EXCEPTION '모르는 엔진 설정: %', v_bad; END IF;
  END IF;
  v_cnt := coalesce((p->>'count')::int, 10);
  IF v_cnt < 1 OR v_cnt > 14 THEN RAISE EXCEPTION '편수는 1~14 사이여야 해요 (받은 값: %)', v_cnt; END IF;
  IF length(coalesce(p->>'memo', '')) > 2000 THEN RAISE EXCEPTION '메모는 2000자까지 쓸 수 있어요'; END IF;
  RETURN jsonb_strip_nulls(jsonb_build_object('count', v_cnt,
           'prev_ref', coalesce((p->>'prev_ref')::boolean, false),
           'avoid_other', coalesce((p->>'avoid_other')::boolean, false),
           'memo', nullif(btrim(coalesce(p->>'memo', '')), ''),
           'args', CASE WHEN p ? 'args' AND p->'args' <> '{}'::jsonb THEN p->'args' END));
END $$;

-- 채널이 그 작품을 쓰는지 · 채널 정보
CREATE OR REPLACE FUNCTION public._tikitaka_channel(p_slug text, p_work text)
RETURNS record LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
DECLARE v record;
BEGIN
  SELECT m.token_slug, m.name, m.gcp_project, coalesce(o.works, m.works) AS works INTO v
    FROM public.channels_mirror m LEFT JOIN public.channel_works_overrides o ON o.token_slug = m.token_slug
   WHERE m.token_slug = p_slug;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 채널이에요: %', p_slug; END IF;
  IF NOT (p_work = ANY (v.works)) THEN RAISE EXCEPTION '이 채널의 작품이 아니에요: % (%)', p_work, v.name; END IF;
  RETURN v;
END $$;

-- 시작 — work_orders + acquire → tikitaka_generate → tikitaka_upload. p_after_job 이 있으면 그 잡이 끝난 뒤에 시작한다
-- (다른 채널이 쓴 장면 피하기: 앞 채널 작업이 올라온 뒤에야 그 장면을 알 수 있다). 반환: 이 작업의 마지막(업로드) 잡 id.
CREATE OR REPLACE FUNCTION public._tikitaka_task_enqueue(p_task uuid, p_after_job uuid)
RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_t record; v_src record; v_ch record; v_wc record; v_wo uuid; v_prev uuid; v_common jsonb; v_gen jsonb;
  v_step record; v_label text; v_ep int;
BEGIN
  SELECT * INTO v_t FROM public.tikitaka_tasks WHERE id = p_task FOR UPDATE;
  IF v_t.status <> 'draft' THEN RAISE EXCEPTION '#% 은 이미 시작했거나 지운 작업이에요', v_t.work_no; END IF;
  SELECT * INTO v_src FROM public.sources WHERE id = v_t.source_id;
  IF v_src.sha256 IS NULL THEN RAISE EXCEPTION '원본 파일이 아직 없어요 — 합본이 다 만들어진 뒤에 시작해 주세요'; END IF;
  SELECT * INTO v_ch FROM public._tikitaka_channel(v_t.channel_slug, v_t.work_title)
    AS (token_slug text, name text, gcp_project text, works text[]);
  SELECT coalesce(episode_unit, '화') AS unit INTO v_wc FROM public.work_cards WHERE work_title = v_t.work_title;
  v_label := v_t.episode_key || coalesce(v_wc.unit, '화');
  v_ep := split_part(v_t.episode_key, '-', 1)::int;

  INSERT INTO public.work_orders
    (service_date, channel_slug, work_title, episode, source_sha256, source_url, pipeline,
     knob_config, geoblock_required, has_subtitle, origin)
  VALUES ((now() AT TIME ZONE 'Asia/Seoul')::date, v_t.channel_slug, v_t.work_title, v_ep, v_src.sha256, v_src.source_url,
          'tikitaka_grid', jsonb_build_object('count', v_t.options->'count', 'args', coalesce(v_t.options->'args', '{}'::jsonb),
                                              'note', v_t.options->>'memo', 'task_id', v_t.id, 'work_no', v_t.work_no),
          false, coalesce(v_src.has_subtitle, false), 'manual')
  RETURNING id INTO v_wo;

  v_common := jsonb_build_object('work_title', v_t.work_title, 'episode', v_ep, 'episode_label', v_label,
                                 'channel_slug', v_t.channel_slug, 'channel_name', v_ch.name);
  v_gen := v_common || jsonb_build_object(
             'source_sha256', v_src.sha256, 'source_url', v_src.source_url,
             'count', v_t.options->'count', 'args', coalesce(v_t.options->'args', '{}'::jsonb),
             'task_id', v_t.id, 'work_no', v_t.work_no, 'episode_key', v_t.episode_key,
             'compilation_id', v_t.compilation_id,
             'prev_ref', coalesce((v_t.options->>'prev_ref')::boolean, false),
             'avoid_other', coalesce((v_t.options->>'avoid_other')::boolean, false),
             'memo', v_t.options->>'memo',
             'resource', 'gemini:' || coalesce(v_ch.gcp_project, 'DEFAULT'));
  v_prev := p_after_job;
  FOR v_step IN
    SELECT * FROM (VALUES
      ('acquire'::text, (v_common || jsonb_build_object('source_url', v_src.source_url, 'source_sha256', v_src.sha256))::jsonb,
       ARRAY['network']::text[], 120::int, 1::int),
      ('tikitaka_generate', v_gen,    ARRAY['generate'], 300, 2),
      ('tikitaka_upload',   v_common, ARRAY['analyze'],  300, 3)
    ) AS t(kind, params, caps, ttl, ord)
    ORDER BY t.ord
  LOOP
    INSERT INTO public.job_queue
      (work_order_id, kind, params, idempotency_key, depends_on, required_caps, lease_ttl_sec, priority)
    VALUES (v_wo, v_step.kind, v_step.params, 'tikitaka:' || v_wo::text || ':' || v_step.kind,
            CASE WHEN v_prev IS NULL THEN '{}'::uuid[] ELSE ARRAY[v_prev] END, v_step.caps, v_step.ttl, 150)
    RETURNING id INTO v_prev;
  END LOOP;
  UPDATE public.tikitaka_tasks SET status = 'queued', work_order_id = v_wo, started_at = now(), updated_at = now()
   WHERE id = p_task;
  PERFORM public._audit('start_tikitaka_task', 'tikitaka_tasks', p_task::text,
          jsonb_build_object('work', v_t.work_title, 'episode', v_t.episode_key, 'no', v_t.work_no,
                             'channel', v_t.channel_slug, 'work_order_id', v_wo, 'after_job', p_after_job));
  RETURN v_prev;
END $$;

-- 여러 작업 시작 — 다른 채널이 쓴 장면 피하기가 켜진 작업은 같은 원본의 앞 작업이 끝난 뒤에 차례로.
CREATE OR REPLACE FUNCTION public.start_tikitaka_tasks(p_tasks uuid[])
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_t record; v_last jsonb := '{}'::jsonb; v_after uuid; v_job uuid; v_out jsonb := '[]'::jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  FOR v_t IN SELECT * FROM public.tikitaka_tasks WHERE id = ANY (p_tasks) AND status = 'draft' ORDER BY work_no LOOP
    v_after := NULL;
    IF coalesce((v_t.options->>'avoid_other')::boolean, false) THEN
      v_after := nullif(v_last->>v_t.source_id::text, '')::uuid;
      IF v_after IS NULL THEN
        -- 이미 돌고 있는 같은 원본의 다른 채널 작업이 있으면 그 업로드 뒤로
        SELECT j.id INTO v_after FROM public.tikitaka_tasks o
          JOIN public.job_queue j ON j.work_order_id = o.work_order_id AND j.kind = 'tikitaka_upload'
         WHERE o.source_id = v_t.source_id AND o.status = 'queued' AND o.channel_slug <> v_t.channel_slug
           AND j.status NOT IN ('succeeded','failed','cancelled','dead')
         ORDER BY o.started_at DESC LIMIT 1;
      END IF;
    END IF;
    v_job := public._tikitaka_task_enqueue(v_t.id, v_after);
    v_last := v_last || jsonb_build_object(v_t.source_id::text, v_job);
    v_out := v_out || jsonb_build_object('task_id', v_t.id, 'work_no', v_t.work_no, 'channel', v_t.channel_slug);
  END LOOP;
  RETURN v_out;
END $$;

-- 저장(+시작) — 채널마다 작업 하나, 번호는 작품 + 회차 안에서 이어서.
CREATE OR REPLACE FUNCTION public.save_tikitaka_tasks(p_source uuid, p_channels text[], p_options jsonb, p_start boolean DEFAULT false)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_src record; v_key text; v_opts jsonb; v_slug text; v_no int; v_ids uuid[] := '{}'; v_id uuid; v_out jsonb := '[]'::jsonb;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  IF coalesce(cardinality(p_channels), 0) = 0 THEN RAISE EXCEPTION '만들 채널을 골라 주세요'; END IF;
  IF cardinality(p_channels) > 10 THEN RAISE EXCEPTION '채널은 한 번에 10개까지 고를 수 있어요'; END IF;
  SELECT * INTO v_src FROM public.sources WHERE id = p_source;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 원본이에요'; END IF;
  v_key := coalesce(v_src.episode_label, v_src.episode::text);
  IF v_key IS NULL THEN RAISE EXCEPTION '회차를 모르는 원본이에요 — 회차가 있는 원본으로 작업해 주세요'; END IF;
  v_opts := public._tikitaka_task_options(p_options);
  PERFORM pg_advisory_xact_lock(hashtext('tikitaka_tasks:' || v_src.work_title || ':' || v_key));
  SELECT coalesce(max(work_no), 0) INTO v_no FROM public.tikitaka_tasks WHERE work_title = v_src.work_title AND episode_key = v_key;
  FOREACH v_slug IN ARRAY (SELECT array_agg(DISTINCT s) FROM unnest(p_channels) s) LOOP
    PERFORM public._tikitaka_channel(v_slug, v_src.work_title);
    v_no := v_no + 1;
    INSERT INTO public.tikitaka_tasks(work_title, episode_key, work_no, source_id, compilation_id, channel_slug, options, created_by)
    VALUES (v_src.work_title, v_key, v_no, v_src.id, v_src.compilation_id, v_slug, v_opts, auth.uid())
    RETURNING id INTO v_id;
    v_ids := v_ids || v_id;
    v_out := v_out || jsonb_build_object('task_id', v_id, 'work_no', v_no, 'channel', v_slug);
    PERFORM public._audit('save_tikitaka_task', 'tikitaka_tasks', v_id::text,
            jsonb_build_object('work', v_src.work_title, 'episode', v_key, 'no', v_no, 'channel', v_slug, 'options', v_opts));
  END LOOP;
  IF p_start THEN PERFORM public.start_tikitaka_tasks(v_ids); END IF;
  RETURN v_out;
END $$;

-- 시작 전 작업 고치기 · 지우기(번호는 남는다)
CREATE OR REPLACE FUNCTION public.update_tikitaka_task(p_task uuid, p_channel text, p_options jsonb)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v_t record;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  SELECT * INTO v_t FROM public.tikitaka_tasks WHERE id = p_task FOR UPDATE;
  IF NOT FOUND OR v_t.status <> 'draft' THEN RAISE EXCEPTION '시작 전 작업만 고칠 수 있어요'; END IF;
  IF p_channel IS NOT NULL THEN PERFORM public._tikitaka_channel(p_channel, v_t.work_title); END IF;
  UPDATE public.tikitaka_tasks SET channel_slug = coalesce(p_channel, channel_slug),
         options = public._tikitaka_task_options(p_options), updated_at = now()
   WHERE id = p_task;
  PERFORM public._audit('update_tikitaka_task', 'tikitaka_tasks', p_task::text,
          jsonb_build_object('channel', p_channel, 'options', p_options));
END $$;

CREATE OR REPLACE FUNCTION public.delete_tikitaka_task(p_task uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  UPDATE public.tikitaka_tasks SET status = 'deleted', updated_at = now() WHERE id = p_task AND status = 'draft';
  IF NOT FOUND THEN RAISE EXCEPTION '시작 전 작업만 지울 수 있어요'; END IF;
  PERFORM public._audit('delete_tikitaka_task', 'tikitaka_tasks', p_task::text, '{}'::jsonb);
END $$;

-- 합본 지우기(만든 원본은 쉬게 둔다 — 그 원본으로 한 작업이 있으면 못 지운다)
CREATE OR REPLACE FUNCTION public.delete_source_compilation(p_id uuid)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE v record;
BEGIN
  IF NOT public.has_role(auth.uid(), 'operator') THEN RAISE EXCEPTION '운영자 권한이 필요해요'; END IF;
  SELECT * INTO v FROM public.source_compilations WHERE id = p_id FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION '없는 합본이에요'; END IF;
  IF v.status IN ('queued','building') THEN RAISE EXCEPTION '만드는 중인 합본은 지울 수 없어요'; END IF;
  IF EXISTS (SELECT 1 FROM public.tikitaka_tasks WHERE compilation_id = p_id AND status <> 'deleted') THEN
    RAISE EXCEPTION '이 합본으로 한 작업이 있어서 지울 수 없어요';
  END IF;
  UPDATE public.source_compilations SET status = 'deleted' WHERE id = p_id;
  UPDATE public.sources SET is_active = false WHERE compilation_id = p_id;
  PERFORM public._audit('delete_source_compilation', 'source_compilations', p_id::text, '{}'::jsonb);
END $$;

DO $$ DECLARE f text; BEGIN
  FOREACH f IN ARRAY ARRAY[
    'public.set_work_youtube_sources(text, jsonb)',
    'public.set_work_compile_defaults(text, text, integer, boolean, boolean)',
    'public.request_source_compilation(text, text, text, jsonb, jsonb)',
    'public.save_tikitaka_tasks(uuid, text[], jsonb, boolean)',
    'public.start_tikitaka_tasks(uuid[])',
    'public.update_tikitaka_task(uuid, text, jsonb)',
    'public.delete_tikitaka_task(uuid)',
    'public.delete_source_compilation(uuid)'] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM public, anon', f);
    EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO authenticated', f);
  END LOOP;
  FOREACH f IN ARRAY ARRAY[
    'public._tikitaka_task_enqueue(uuid, uuid)', 'public._tikitaka_channel(text, text)'] LOOP
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM public, anon, authenticated', f);
  END LOOP;
END $$;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0121','claude (유튜브 원천 여러 채널 · 합본 · 작업 번호와 시작 전 작업)');
