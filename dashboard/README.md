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
