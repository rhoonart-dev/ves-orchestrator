-- 0103 — 채널 일시정지 (2026-08-30, 운영자 지시)
--
-- > "당분간 커리어데이 숏츠, 잔망루피, 숏콘, 한 입 주막, 락커룸, 재미쇼츠만 운영할 거야.
-- >  나머지 작품들/채널들은 작업 일시정지 시켜주라"
--
-- 운영 6채널: CAREERDAY · LOOPY(まいにちじゃんまんるぴー) · SHOTCONE(ショトコン) ·
--            HANIPJUMAK · LOCKERROOM · JAEMISHOTS
-- 멈추는 것: planner(매일 09:00 KST)의 **하루치 work_order 생성**. 그것뿐이다.
-- 그대로인 것: 채널↔작품 매핑(channels.json 정본 · 권리 관계)·소스 등록·이미 만든
--   산출물의 검수/승인/발행, 그리고 관제 '작업 실행'(사람이 직접 부르는 경로).
--   → 재개는 이 값에서 슬러그를 빼는 것 하나다. 배정을 지우면 되돌릴 때 근거가 사라진다.
-- 되돌리기(전체 재개): UPDATE public.ops_config SET value='[]' WHERE key='paused_channels';

INSERT INTO public.ops_config(key, value, note)
VALUES ('paused_channels',
        '["CINEMAINBED","DARAMJI","NEOGULBANG","TETOCHIP","KIKKIK","HEUNGHAENG","SHOTNOW","YEOWOON","MOLIPDODUK","SCENELAUNDRY","REWINDPOCHA","ENDINGSUNSAK","SHORTSSUNSHINE","BGSUNSAK","IGEOBOGOJA"]',
        '2026-08-30 운영자 지시 — 커리어데이·잔망루피·숏콘·한 입 주막·락커룸·재미쇼츠 6채널만 운영')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, note = EXCLUDED.note, updated_at = now();

INSERT INTO public.applied_migrations(engine, version, applied_by)
VALUES ('orchestrator','0103','claude (채널 일시정지 — 운영자 지시로 15채널 계획 중지)')
ON CONFLICT DO NOTHING;
