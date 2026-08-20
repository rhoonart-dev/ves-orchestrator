-- =====================================================================
-- 0062_wo_match_sha_or_url.sql — 소스 매칭을 'sha 또는 URL' 로 (2026-08-20)
--
-- 왜: 0027 의 매칭은 소스 행에 sha 가 **있으면 sha 로만** 물린다. 유튜브 행은 sha 가
-- 없다는 전제였다 — 그 전제가 8/18 에 깨졌다.
--
--   091725c(8/18) deploy/backfill_youtube_masters.py — 8/18 유튜브 403 사태 대응으로
--   URL 소스를 Storage 에 올리고 **그 행에** sha256 을 채운다. 그 커밋은 "행이 바뀌면
--   그 행에 걸린 사용 이력이 끊긴다"며 일부러 기존 행을 갱신했는데, 이력을 끊은 것은
--   행 교체가 아니라 이 함수였다. 과거 작업지시는 URL 로만 물려 있는데(당시 소스에
--   sha 가 없었다) 백필이 sha 를 채우는 순간 매칭이 sha 쪽으로 넘어가 URL 이력이
--   통째로 안 보인다. 행은 그대로인데 이력만 사라진다.
--
-- 실측(8/20): 고아가 된 과거 작업지시 45건(숏나우저 10 · 숏테토칩 10 · 커리어데이 9 ·
-- 흥행수집 9 · 너굴안방 7). 이미 쓴 소스가 '미사용' 으로 되살아나 같은 원본을 다시
-- 집는다 — 커리어데이가 8/14 에 쓴 5회차(한도 1편)를 8/20 에 또 집었고, 한도를 넘겨
-- 만든 소스가 8건 있다(도깨비 1회 한도3·실사용5 등).
--
-- 고침: sha 가 맞거나 URL 이 맞으면 같은 영상으로 본다. 백필 전(URL만)·후(sha)
-- 작업지시가 한 행에서 이어진다.
--
-- 영향(적용 전 실측): 활성 소스×채널 528조합 중 판정이 바뀌는 것 15건, 전부
-- '가용→소진' 한 방향이다(소진→가용 0건 — 잠긴 소스가 잘못 풀리는 일은 없다).
-- 남은 소스가 0 이 되는 채널 없음(엔딩순삭은 이 변경과 무관하게 이미 0).
-- 한 작업지시가 소스 두 행에 물리는 이중 차감: 0건(URL 중복 행 없음, sha 중복 없음).
--
-- 되돌리기: 이 함수를 0027 정의로 다시 CREATE OR REPLACE 하면 끝(데이터 무변경).
-- =====================================================================
CREATE OR REPLACE FUNCTION public.wo_matches_source(
    w_work text, w_sha text, w_url text,
    s_work text, s_sha text, s_url text)
RETURNS boolean LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
    SELECT w_work = s_work
       AND ((nullif(s_sha,'') IS NOT NULL AND w_sha = s_sha)
         OR (nullif(s_url,'') IS NOT NULL AND w_url = s_url));
$$;
COMMENT ON FUNCTION public.wo_matches_source(text,text,text,text,text,text) IS
  '작업지시가 이 소스 행을 쓴 것인가 — sha 또는 URL 이 맞으면 같은 영상(0062). '
  '0027 은 sha 가 있으면 sha 로만 봤는데, 유튜브 소스 Storage 백필(8/18)로 sha 가 '
  '뒤늦게 생기면서 URL 로만 물린 과거 이력이 끊겼다.';

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0062','claude (소스 매칭 sha 또는 URL — 유튜브 Storage 백필로 끊긴 사용 이력 복구)')
ON CONFLICT DO NOTHING;
