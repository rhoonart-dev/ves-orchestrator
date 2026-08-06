# RUNBOOK — 장애 대응

## 1. 악성 커밋 (자동 업데이트의 안전핀 — ARCHITECTURE 부록 C)

증상: dead 잡 급증(지표3) / smoke 실패로 노드 disabled(지표12)

```sql
-- ① 핀 고정 (대시보드 [핀] = pin_engine RPC)
UPDATE deployments SET auto_update=false, pinned_sha='<직전 정상 sha>' WHERE engine='<엔진>';
-- ② 노드들이 다음 claim 경계에서 자동 롤백 (재기동 불필요)
-- ③ disabled 노드 복귀: UPDATE node_registry SET status='active' WHERE node_id='mm-0X';
-- ④ 원인 revert push → 확인 후: UPDATE deployments SET auto_update=true, pinned_sha=NULL …
-- ⑤ 그 시간대 생성분은 job_queue.result->engine_sha 로 식별 — 재생성/코호트 제외 판단
```

## 2. 노드 다운

- 5분 심박 경보 → 큐는 계속 빠진다(동질 풀). lease 만료분은 reaper 가 ~2분 내 재배정.
- 에이전트만 죽었으면 launchd KeepAlive 가 재기동. 그래도 안 뜨면 → SSH(예외 상황):
  `tail -100 /opt/ves/logs/agent.log` · `launchctl kickstart -k gui/$(id -u)/com.rhoonart.ves-agent`

## 3. 큐 적체 (pending 이 안 빠짐)

체크 순서: ① 노드 심박(전멸이면 Supabase 장애 → 복구 대기, 잡은 안전) ② `required_caps`
를 가진 active 노드가 있는가 ③ `run_after` 미래로 밀려있나(쿼터 대기) ④ `depends_on`
선행이 failed/blocked 로 막혔나 → 원인 잡을 retry/approve.

## 4. 실행 중 잡 강제 중단

대시보드 [취소](`cancel_job` RPC) → 워커의 다음 lease 갱신(≤TTL/4)이 0행 → 서브프로세스 kill.
generate(TTL 300s)는 최대 ~75초 안에 멈춘다.

## 5. Supabase 장애

워커는 claim 실패 시 대기만 한다 — 아무것도 깨지지 않는다. 복구되면 큐 순서대로 재개.
진행 중이던 잡은 lease 만료로 회수(체크포인트 재개 ★⑦ 덕에 재소각 아님).

## 6. 디스크 부족

`disk_free_gb<100` → 자동 draining. `cache/sources` LRU 정리 후 active 복귀.
반복되면 보관 정책(§9-4) 축소 또는 SSD 증설.

## 7. 마이그레이션 대기 경보

"엔진 X 가 마이그레이션 NNNN 적용 대기" → SQL 검토 → 적용(사용자 확인 규율) →
`INSERT INTO applied_migrations(engine,version,applied_by) VALUES('X','NNNN','<이름>')`
→ 다음 claim 경계에서 노드들이 알아서 갱신.
