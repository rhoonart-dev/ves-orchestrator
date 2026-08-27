# P8 — video-localization-project(vlp) 동결 런북

작성 2026-08-27. P1~P7 이 끝나 vlp 의 일은 전부 ai-video·ves 로 넘어갔다.
이 문서는 **마지막 남은 의존이 무엇이고, 언제·어떻게 동결하는지**를 적는다.

## 지금 남은 vlp 의존 — 딱 하나

**레거시 검수 카드 15장** (`review_queue` kind=localization_qa, `payload.zanmang_video_id`
있음, status=waiting — 8/25~8/26 vlp autopilot 산출). 이 카드를 승인/수정재렌더하면
`zanmang_decision` 잡이 생기고, 그 잡이 mm-06 의 vlp 체크아웃에서 돈다.

그 외에는 없다(2026-08-27 실측):
- vlp 계열 잡(zanmang/zanmang_decision/loopy_*) 대기·실행 **0건**
- autopilot launchd **제거됨**(8/26 컷오버), `zanmang_pipeline` 스위치 꺼짐
- 신규 잔망루피 쇼츠는 우리 overlay 파이프라인, 롱폼은 생성 체인(+L4d 더빙)

## 동결 조건 (drain 판정)

```sql
SELECT count(*) FROM review_queue
 WHERE kind='localization_qa' AND status='waiting'
   AND payload->>'zanmang_video_id' IS NOT NULL;
```
**0 이 되는 날 동결한다.** 카드는 사람이 승인·반려로만 줄어든다(자동 만료 없음).
빨리 닫고 싶으면 15장을 일괄 반려해도 된다 — 반려는 기록만 남기고 vlp 를 부르지
않는다. 같은 소재가 필요하면 우리 overlay 파이프라인으로 다시 돌리면 된다.

## 동결 절차 (조건 충족 후)

1. **정지**: mm-06 vlp 체크아웃은 더 이상 어떤 잡도 받지 않는다 — `zanmang_decision`
   어댑터에 남은 카드가 없음을 확인(위 SQL 0). 어댑터 코드는 지우지 않는다(감사 이력
   재현용) — `ops_config` 에 `vlp_frozen=on` 을 넣고 어댑터 머리에서 거절하게 하는
   마이그레이션 1건이 이 단계의 코드 작업 전부다.
2. **레포 동결**: vlp GitHub 레포 archive (read-only). 노드의
   `/opt/ves/engines/video-localization-project` 는 지우지 않는다 — 과거 산출물
   (`outputs/`)의 대조 근거다. 디스크가 급하면 venv(~3GiB)만 지운다.
3. **가드 은퇴**: ai-video 의 `scripts/localize_port_diff.py`·`scripts/overlay_port_diff.py`
   와 그것을 부르는 테스트를 제거한다 — 두 스크립트의 존재 이유가 "vlp 가 앞서가면
   먼저 운다"인데, 동결되면 앞서갈 일이 없다. EXPECTED_DIFFS 에 쌓인 사유들은
   CLAUDE.md 해당 절에 이미 옮겨져 있다.
4. **문서**: ai-video CLAUDE.md 의 "vlp 동결 시 함께 은퇴" 표기들(port_diff 절)을
   정리하고, 이 문서에 동결 일자를 적는다.

## 동결 후에도 남는 것

- vlp 가 만들어 발행한 영상들의 산출물(mm-06 `outputs/`) — 재렌더가 필요하면
  그 mp4 를 **우리 overlay 파이프라인의 입력**으로 쓴다(vlp 를 되살리지 않는다).
- `zanmang_decision` 어댑터 코드 — frozen 스위치 뒤에서 거절만 한다.

## 동결 일자

- [ ] 미정 — drain 0 확인 후 기입.
