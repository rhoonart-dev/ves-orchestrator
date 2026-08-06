-- 0006_seed.sql — 초기 데이터 (0006/0007 적용 후 1회. ⚠ TODO 값 채워서 실행)

-- 배포 대상 4엔진 (repo_url 은 조직 실제 값으로)
INSERT INTO public.deployments(engine, repo_url, track_ref, auto_update) VALUES
  ('ai_video',     'https://github.com/rht-22/ai-video.git',                        'main', true),
  ('brain',        'https://github.com/rhoonart-dev/ai-improvement-edit-video.git', 'main', true),
  ('localization', 'https://github.com/rhoonart-dev/video-localization-project.git','main', true),
  ('orchestrator', 'https://github.com/rhoonart-dev/ves-orchestrator.git',          'main', true)
ON CONFLICT (engine) DO NOTHING;

-- 자원 상한 (§7 — Phase 2 실측 후 튜닝)
INSERT INTO public.resource_limits(resource, max_active, note) VALUES
  ('gemini:SEAN',2,NULL),('gemini:VES01',2,NULL),('gemini:VES03',2,NULL),
  ('gemini:VES04',2,NULL),('gemini:CJENM',2,NULL),('gemini:JMLP',1,NULL),
  ('yt_upload:_global',3,'YouTube 업로드 동시 상한'),
  ('storage_dl',3,'마스터 동시 다운로드')
ON CONFLICT (resource) DO NOTHING;

-- ★③ 마이그레이션 원장 소급 기록 — brain 0001~0005 는 이미 적용됨(CLAUDE.md §1)
INSERT INTO public.applied_migrations(engine, version, applied_by) VALUES
  ('brain','0001','backfill'),('brain','0002','backfill'),('brain','0003','backfill'),
  ('brain','0004','backfill'),('brain','0005','backfill'),
  ('orchestrator','0006','backfill'),('orchestrator','0007','backfill')
ON CONFLICT DO NOTHING;

-- 대시보드 역할 시드 (auth.users 의 uuid 로 교체)
-- INSERT INTO public.user_roles(user_id, role) VALUES ('<uuid>','admin');
