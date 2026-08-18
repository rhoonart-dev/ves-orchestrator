# dashboard — Phase 2 (S3 정적 SPA)

규칙은 전부 Postgres 에 있다(0007: RLS + RPC). 이 SPA 는 **표시와 호출만** 한다 —
anon key 는 공개값, 여기서의 검증은 UX 일 뿐(R15). 서버 프로세스 없음(R12 구조 보장).

## 배포

main 에 `index.html` 이 올라가면 `.github/workflows/dashboard-deploy.yml` 이
문법 검사 → S3 업로드 → CloudFront 무효화까지 한다(설정·수동 절차는 HANDOFF §7).

```
node --check(인라인 script) → aws s3 cp index.html s3://<bucket> → CloudFront invalidation
```
- ⚠ S3 웹사이트 엔드포인트는 HTTP 전용 — **CloudFront + ACM 필수**
- ⚠ SPA 라우팅: CloudFront 커스텀 에러 403/404 → /index.html(200)

## 호출 예 (supabase-js)

```js
const sb = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
await sb.auth.signInWithPassword({email, password})          // 인증 주체는 미결정 §17-①
const {data: waiting} = await sb.from('review_queue').select('*').eq('status','waiting')
const {data: url} = await sb.storage.from('ves-outputs')
      .createSignedUrl(`${runId}/preview.mp4`, 900)          // 검수 재생(15분)
await sb.rpc('approve_and_publish', {p_review_id, p_privacy:'unlisted'})   // 승인=RPC
await sb.rpc('cancel_job', {p_job})                          // 실행 중이면 ~lease/4 내 중단
```

화면 5개(§10-4): 오늘 / 검수 / 버전 / 라운드 / 소스(TUS 업로드 — tus-js-client, 6MB 초과 필수)

## 성과 탭 (v3.3)

읽는 것은 `perf_video_snapshot` · `perf_video_map` · `perf_channel_snapshot` 셋 —
perf_sync(스케줄러, 매시간)가 laeebly 에서 복사해 둔 미러다. RPC 없이 RLS 아래에서 직접 SELECT 한다.

- **기간**은 프리셋(7·14·28·90일·전체) 또는 **날짜 직접 지정**. 지정한 구간이 지금 받아 둔
  창보다 과거로 뻗으면 그때 다시 받는다. 상한은 perf_sync 의 보존창 `KEEP_DAYS`(120일)이고,
  보유 범위 밖을 넣으면 가까운 쪽으로 붙는다.
- **지표 셋(조회수·좋아요·구독자)을 한 페이지에** 같은 판형으로 나란히 놓는다 — 카드마다
  왼쪽이 일별 증가, 오른쪽이 누적. 조회수·좋아요는 영상 스냅샷 합, 구독자는 채널 스냅샷
  값이라 "누적"이 아니라 그 시점의 수다(`absolute`).
- **영상 상세**는 표에서 행을 누르면 그 아래로 펼친다(대시보드 관행: `bdetail`). 썸네일·
  좋아요율·하루 평균·첫날/첫 7일 조회와 함께 조회·좋아요 차트 넷을 보여준다. 상세 차트는
  기간 설정과 무관하게 *그 영상의 게시일부터 지금까지*를 그린다 — 발행 직후 급상승이
  구간 밖으로 잘리면 영상을 판단할 수 없다. 첫날/첫 7일은 미러 보유 구간 안에서 발행된
  영상만 낼 수 있다(그 전 스냅샷이 없다).
- **일별 증가**는 날짜별 단순 합산이 아니라 *영상별 스냅샷을 선형 보간한 뒤 차분*한다.
  원천 수집이 하루 빠져도(2026-07 중순 실측) 그날 몫이 다음 날로 몰리지 않는다.
- **수집률**(그날 스냅샷이 찍힌 영상 ÷ 그날 살아 있던 영상)을 같이 계산해, 70% 미만인 날은
  차트에 회색 띠를 깔고 상단에 배지·경고를 띄운다. 보간은 구간 총량은 지키지만 하루하루의
  모양까지 지어내지는 못하므로, 어디까지가 관측인지 화면이 먼저 말해야 한다
  (실측: 2026-06-26~07-22 구간의 원천 수집률이 27~32%대). 영상 상세의 회색 띠는
  *그 영상이* 그날 안 찍혔다는 뜻이다.
- **업로드**는 `perf_video_map.published_at` 기준이라 스냅샷이 아직 없는 갓 발행분도 잡힌다.
- **채널별 영상 개수**는 가로 막대로 본다 — 밝은 칸이 고른 기간에 올린 분이다.
- 영상 표의 조회 열은 둘이다: `N일 조회`(그 기간에 벌어들인 조회수)와 `전체 누적`.
- 차트는 전부 인라인 SVG — 단일 파일 자급자족 원칙대로 차트 라이브러리를 두지 않는다.
