-- =====================================================================
-- 0070_editor_baselines.sql — 편집실 'AI 원안' 스냅샷 보존 (2026-08-21)
--
-- 왜: editor_assets.timeline 은 "지금 화면이 그릴 타임라인"이라 편집 재렌더 뒤 재워밍
-- (0043 ⑦ → editor_assets 잡) 이 돌면 **편집된 구간으로 덮어쓴다**. 그래서 "AI 가 처음에
-- 무엇을 골랐고 사람이 무엇을 고쳤나"를 사후에 복원할 수 없다 — 8/21 편집 기록 분석에서
-- 첫 편집 7/21 건의 원안이 이미 유실돼 있었다. 사람 수정 패턴(새 장면 추가·중간 삭제·
-- 경계 확장)은 AI 편집 제안 기능의 설계 근거이자 채택률 측정 기준이므로 원안을 따로 남긴다.
--
-- 어떻게: 별도 표 editor_baselines(run_id 당 1행) + editor_assets 트리거.
--   · editor_assets.timeline 이 쓰일 때마다, 그 작업지시의 **마지막으로 성공한 generate 잡**에
--     edit_overrides 가 없으면 → 이 타임라인은 AI 원안이다 → 스냅샷을 쓴다(덮어씀 포함:
--     재생성(regen)으로 원안 자체가 바뀌면 새 원안이 정본이다).
--   · edit_overrides 가 있으면 → 편집된 상태다 → 스냅샷을 건드리지 않는다. 스냅샷이 아직
--     없더라도 편집본을 원안으로 적지 않는다(잘못 라벨된 기준선은 없는 것보다 나쁘다).
--   · 순수 SQL 이라 어댑터·노드 배포가 필요 없다(editor_assets.py 의 UPSERT 는 그대로).
--
-- 백필: 지금 editor_assets 에 남은 timeline 중 **첫 편집 이전에 만들어진 것**만 옮긴다.
--   판정 = 그 작업지시에 edit_overrides 달린 generate 잡이 editor_assets.updated_at 보다
--   먼저 만들어진 적이 없음. submit_editor_render 는 잡 INSERT 와 editor_assets.updated_at
--   갱신을 같은 트랜잭션(now() 동일)에서 하므로 '같은 시각' 은 '편집 이전' 으로 본다 — 1초 여유.
--
-- 읽기: 대시보드는 아직 안 읽는다(분석용). RLS 는 editor_assets 와 같은 규율(읽기 authenticated,
-- 쓰기는 service_role/트리거).
-- 짝: ves/adapters/editor_assets.py(UPSERT 발화점) · 0043 submit_editor_render(⑦ pending 전환).
-- =====================================================================

CREATE TABLE IF NOT EXISTS public.editor_baselines (
    run_id               text PRIMARY KEY,
    work_order_id        uuid REFERENCES public.work_orders(id) ON DELETE CASCADE,
    review_id            uuid,
    -- editor_assets.timeline 을 그대로 복사(editor_timeline/v1: clips·subtitles·tts·top_title …)
    timeline             jsonb NOT NULL,
    duration_sec         double precision,
    -- 이 원안을 만든 generate 잡(edit_overrides 없는 마지막 성공 잡). 백필 행은 NULL 일 수 있다.
    source_generate_job  uuid,
    captured_via         text NOT NULL DEFAULT 'trigger'
                         CHECK (captured_via IN ('trigger','backfill')),
    captured_at          timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.editor_baselines IS
  '편집실 AI 원안 타임라인 스냅샷(run_id 당 1행). editor_assets.timeline 이 편집 재렌더로 덮어써지기 전 상태. '
  '편집 기록(job_queue.params.edit_overrides)과 대조해 사람 수정 패턴을 계산하는 기준선.';

CREATE INDEX IF NOT EXISTS editor_baselines_wo_idx ON public.editor_baselines(work_order_id);

ALTER TABLE public.editor_baselines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS ves_dash_read ON public.editor_baselines;
CREATE POLICY ves_dash_read ON public.editor_baselines
  FOR SELECT TO authenticated USING (true);

-- ── 트리거: editor_assets.timeline 이 쓰일 때 원안이면 스냅샷 ─────────────────────
CREATE OR REPLACE FUNCTION public.editor_baseline_capture()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_job record;
BEGIN
    IF NEW.timeline IS NULL OR NEW.work_order_id IS NULL THEN
        RETURN NEW;
    END IF;
    -- 이 타임라인의 출처 = 작업지시의 마지막 성공 generate 잡(0043 ④ 와 같은 선택 기준)
    SELECT j.id, (j.params ? 'edit_overrides') AS edited
      INTO v_job
      FROM public.job_queue j
     WHERE j.work_order_id = NEW.work_order_id
       AND j.kind = 'generate' AND j.status = 'succeeded'
     ORDER BY coalesce(j.finished_at, j.updated_at) DESC
     LIMIT 1;
    IF NOT FOUND OR v_job.edited THEN
        -- 편집된 상태(또는 출처 불명) — 원안으로 적지 않는다
        RETURN NEW;
    END IF;
    INSERT INTO public.editor_baselines
        (run_id, work_order_id, review_id, timeline, duration_sec,
         source_generate_job, captured_via, captured_at, updated_at)
    VALUES (NEW.run_id, NEW.work_order_id, NEW.review_id, NEW.timeline, NEW.duration_sec,
            v_job.id, 'trigger', now(), now())
    ON CONFLICT (run_id) DO UPDATE SET
        work_order_id = excluded.work_order_id,
        review_id     = excluded.review_id,
        timeline      = excluded.timeline,
        duration_sec  = excluded.duration_sec,
        source_generate_job = excluded.source_generate_job,
        captured_via  = 'trigger',
        updated_at    = now();
    RETURN NEW;
END $$;

REVOKE ALL ON FUNCTION public.editor_baseline_capture() FROM public, anon, authenticated;

DROP TRIGGER IF EXISTS editor_baseline_capture ON public.editor_assets;
CREATE TRIGGER editor_baseline_capture
    AFTER INSERT OR UPDATE OF timeline ON public.editor_assets
    FOR EACH ROW
    WHEN (NEW.timeline IS NOT NULL)
    EXECUTE FUNCTION public.editor_baseline_capture();

-- ── 백필: 첫 편집 이전에 만들어진 timeline 만 ───────────────────────────────────
INSERT INTO public.editor_baselines
    (run_id, work_order_id, review_id, timeline, duration_sec,
     source_generate_job, captured_via, captured_at, updated_at)
SELECT ea.run_id, ea.work_order_id, ea.review_id, ea.timeline, ea.duration_sec,
       (SELECT j.id FROM public.job_queue j
         WHERE j.work_order_id = ea.work_order_id
           AND j.kind = 'generate' AND j.status = 'succeeded'
           AND NOT (j.params ? 'edit_overrides')
         ORDER BY coalesce(j.finished_at, j.updated_at) DESC LIMIT 1),
       'backfill', ea.updated_at, now()
  FROM public.editor_assets ea
 WHERE ea.timeline IS NOT NULL
   AND ea.work_order_id IS NOT NULL
   AND NOT EXISTS (
         SELECT 1 FROM public.job_queue j
          WHERE j.work_order_id = ea.work_order_id
            AND j.kind = 'generate'
            AND j.params ? 'edit_overrides'
            AND j.created_at < ea.updated_at - interval '1 second')
ON CONFLICT (run_id) DO NOTHING;

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0070','claude (편집실 AI 원안 스냅샷 editor_baselines + 트리거 + 백필)');
