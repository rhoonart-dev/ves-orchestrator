# TREND_REPORT — 일일 트렌드·성과 리포트 (기획 v2, 2026-08-26 · 구현 2026-08-27)

> **구현 현황(2026-08-27)**: C1(0097 `perf_studio_daily`, perf_sync 자기치유 포함) ·
> C2(`trend_scout`, 03:00) · P2(0098 `trend_report` + `trend_report.py`, 05:00) ·
> P3(`get_trend_report` RPC + 대시보드 '트렌드' 탭) · C3(`algo_watch`, 주 1회) 전부 배포.
> 운영자 지시로 수집·생성 모두 켠 채 시작. Gemini 는 `gemini_key` 슬롯 체계(0025)에
> 합류 — 소진 시 failover, 해설 실패 시 facts 만으로 성립.

관제 사이트에 **화면 1개 + 수집기 3개 + 리포트 생성기 1개**를 더한다. 매일 아침 한 장을
읽으면 "밖에서 뭐가 뜨는가 · 우리는 어디서 끊기는가 · 왜 되는 건 되는가"가 나온다.

**분석 축은 작품(work)이다.** 한 작품이 여러 채널에 가고 한 채널이 여러 작품을 받는 것은
정상이다. 성과를 작품에 귀속시켜 본 뒤 채널·영상 데이터와 교차한다.

---

## 1. 계측은 이미 있다 — laeebly 를 쓴다

Analytics API 는 쓰지 않는다. **laeebly(`mehvzxzajydffflqcuuk`) `youtube_studio`** 가
우리 채널 20/21 을 이미 매일 수집하고 있다(LOOPY 만 밖 — laeebly MCN 소속이 아님).

`youtube_studio` 는 **일 단위 증분**이다(누적 아님 — 영상 생애 합산해서 읽어야 한다).
`upload_at` RANGE 월별 파티션(`youtube_studio_YYYY_MM_part`).

> ⚠ **날짜 축은 `upload_at`** 이다. `created_at` 은 수집 시각일 뿐이라 하루에 여러
> 날짜분이 몰려 들어온다(8/15 06:19 수집=8/10 자, 16:35 수집=8/11 자). `created_at` 으로
> 거르면 파티션 프루닝도 안 돼 전 파티션을 훑는다 — 실측에서 질의가 응답하지 못했다.
> `(content_id, upload_at)` 은 유일하다(B급 순삭 8월 1,779행 = 1,779키).

쓸 컬럼:

| 컬럼 | 뜻 |
|---|---|
| `impressions` · `impression_click_rate` | 노출 · CTR |
| `average_view_percentage` · `kept_watching_rate` | 완주율 · 유지율 |
| `views` · `valid_views` · `watch_time_hours` | 조회 · 시청시간 |
| `video_length` | 길이(초) |
| `licensed_video_title` · `identification_code` | **작품 축** |
| `subscribers` · `likes` · `shares` · `comments_added` | 참여 |
| `channel_id` · `content_id` · `publish_time` | 키 |

### 2026-08-26 실측 — 이미 답이 나왔다

| 채널 | 노출(중앙) | CTR | 조회(중앙) | 길이 |
|---|---:|---:|---:|---:|
| B급 순삭 | 1,840 | 4.42% | 12,630 | **38초** |
| 한 입 주막 | 1,453 | 10.75% | 2,304 | 60초 |
| 재미쇼츠 | 514 | 9.94% | 1,267 | 54초 |
| 나머지 17채널 | **0~21** | 대부분 0 | 0~3 | 48~51초 |

**깔때기 1단에서 끊긴다.** 죽은 채널의 완주율은 오히려 높다(너굴안방 92.4 · 이불 속
극장 81.7 · 명장면 세탁소 74.0) — 노출된 소수는 끝까지 봤다. 콘텐츠가 아니라 배포다.

> ⚠ 노출이 한 자리면 CTR·완주율은 통계적으로 무의미하다. 리포트는 **노출 하한(N≥100)을
> 넘긴 영상만** 2·3단 판정에 넣는다. 그 아래는 "판정 보류"로 표시한다.

---

## 2. 데이터 배선 — laeebly → 관제로 미러

두 프로젝트는 별개 DB다. 조인할 수 없으므로 **미러**를 뜬다. 새 수집기가 아니라
**기존 `perf_sync` 확장**이다 — laeebly 접속(`cfg.laeebly_url`)·채널 목록·창 관리가
이미 거기 있다. 테이블은 `perf_studio_daily`(0097).

- 매시간(perf_sync 주기). 첫 회전은 보존 창 120일, 이후로는 최근 7일만 다시 읽는다
- `perf_video_snapshot`(누적)과 **테이블을 따로 둔다** — 알갱이가 다르다.
  한 테이블에 섞으면 같은 컬럼을 어떤 행은 누적, 어떤 행은 증분으로 읽게 된다
- `view_pct` 는 100 을 넘을 수 있다(재시청) — 상한을 가정하지 말 것
- LOOPY 는 laeebly MCN 밖이라 여기 없다. `loopy_ledger` 로 별도 — 리포트에서
  합류시키되 출처를 표시한다

---

## 3. 수집기 3개

### C1 · 스튜디오 미러 — 매시간(perf_sync 주기)
위 §2. laeebly 읽기 전용 접속. 원천이 4일쯤 지연되므로(최신 upload_at 이 8/22)
하루 한 번이면 놓치는 갱신이 있다 — perf_sync 주기를 그대로 탄다.

### C2 · 외부 트렌드 — 03:00 KST

```sql
-- 0097
create table public.trend_snapshot (
  collected_date date, region text, source text, rank int,
  title text, video_id text, channel_title text, category_id text,
  view_count bigint, published_at timestamptz, raw jsonb,
  primary key (collected_date, region, source, rank)
);
```

| 소스 | 방법 | 쿼터 |
|---|---|---|
| YouTube 급상승 | `videos.list` `chart=mostPopular` × KR/JP/US | **지역당 1유닛** |
| 카테고리 분포 | 위 응답 `categoryId` 집계 | 0 |
| 검색 이슈 | Google Trends 일일 트렌드 KR/JP/US | 0 |

> `chart=mostPopular` 는 2025-07-21 이후 통합 "Trending Now" 가 아니라 Music/Movies/
> Gaming 카테고리 차트를 반환한다. 전량 급상승이 아님을 전제로 읽는다.

### C3 · 알고리즘 상수 조사 — 주 1회(월 05:00 KST)

임계값은 유튜브가 공표하지 않는다. 크리에이터 매체의 역추론이라 **주기적으로 다시
확인**해야 하고, 우리 실측이 쌓이면 그 값으로 교정한다.

- Gemini API + Google Search grounding 으로 "YouTube Shorts 알고리즘 변경" 조사
- 결과를 `ops_config.key='algo_constants'` 에 **제안값**으로 기록 (자동 반영 안 함)
- 현행값과 다르면 리포트 상단에 배지로 띄운다 — **바꾸는 것은 사람이다**

```json
{ "sweet_spot_sec": [30,45], "retention_min": {"lt30": 0.65, "30to60": 0.50},
  "impression_floor": 100, "ctr_floor": 2.0,
  "source": "…", "checked_at": "2026-08-26", "confidence": "역추론" }
```

---

## 4. 리포트 생성 — Gemini

`trend_report` 한 행 = 하루. 05:30 KST, C1·C2 뒤.

```sql
-- 0098
create table public.trend_report (
  report_date  date primary key,
  facts        jsonb not null,        -- SQL 이 만든 숫자 (검증 가능)
  narrative    jsonb not null,        -- Gemini 가 쓴 해설
  model        text, prompt_sha text,
  generated_at timestamptz default now()
);
```

**숫자와 해설을 분리한다.** `facts` 는 SQL 집계 결과이고 Gemini 는 그것을 **설명만** 한다 —
수치를 지어내면 대조로 잡힌다. 프롬프트에 "facts 밖의 숫자를 쓰지 말 것"을 명시한다.

- 키: 기존 `resource_limits` 의 `gemini:*` 슬롯 재사용(0025 키 슬롯 구조)
- 실패 시 `narrative` 없이 `facts` 만으로 리포트가 성립해야 한다 — 화면이 죽지 않는다

### 섹션 5개 — 이 이상 늘리지 않는다

1. **밖** — KR/JP/US 급상승 + 카테고리 분포 + 어제 대비 변동
2. **안** — 작품별 성과(어제 · 누적), 채널·영상은 그 아래 접힘
3. **왜 안 되나** — 깔때기 3단 진단
4. **왜 되나** — 성공 요인 분석 (§5)
5. **오늘 할 것** — 위에서 도출된 액션 후보

---

## 5. 판정 규칙

임계값은 `ops_config.key='algo_constants'` 한 곳에서만 고친다.

### 실패 진단 (깔때기 순서대로, 먼저 걸리는 데서 멈춘다)

| 조건 | 판정 | 처방 |
|---|---|---|
| `impressions` < 100 | **배포 안 됨** | 채널·계정 문제. 썸네일/훅 손대지 말 것 |
| `ctr` < 2% | **안 눌림** | 제목·썸네일 |
| 길이 < 30초 & `view_pct` < 65% | **이탈** | 훅 3초 |
| 길이 30~60초 & `view_pct` < 50% | **이탈** | 훅 3초 + 길이가 45초 초과면 재단부터 |
| 위 전부 통과 | **정상** | 길이가 얼마든 건드리지 않는다 |

> ⚠ **길이는 독립 판정이 아니다 — '이탈'의 처방 힌트일 뿐이다.**
> 초안에서는 `길이 > 45초`를 독립 규칙으로 뒀는데, 실데이터를 미러에 넣어보니
> 한 입 주막 7편(노출 813~4,324 · CTR 9~14.5% · 완주율 66~100%)이 **전부 '길이 경고'**
> 로 찍혔다. 지금 가장 잘 되는 영상들이다. 완주율 100% 인 60초 영상에 "30~45초로
> 자르라"는 건 해로운 처방이다. 깔때기가 새지 않으면 길이는 문제가 아니다.
>
> 스윗스팟(30~45초)은 **무엇을 만들지 정할 때의 기본값**이지 이미 잘 되는 것을
> 되돌리는 근거가 아니다. 성공 요인 분석(§5 후반)에서 축으로만 쓴다.

### 성공 요인 분석

잘 되는 것도 왜 되는지 모르면 재현할 수 없다. **상위 10% 영상**(작품별·전체별)을 뽑아
아래를 대조하고, 하위군과 **유의하게 다른 축만** 리포트에 올린다.

| 축 | 재료 |
|---|---|
| 길이 | `video_length` — 지금 유일한 성공 채널 B급 순삭이 38초, 죽은 군은 48~51초 |
| 작품 | `work_title` 별 노출·CTR·완주율 |
| 게시 시각 | `publish_time` 요일·시간대 |
| 제목 | `video_title` 패턴(길이·숫자·의문형·인물명) |
| 참여 | `shares`/`views`, `subscribers`/`views` — 공유율이 노출을 끄는 신호인지 |
| 외부 연동 | 그날 `trend_snapshot` 에 작품·인물이 올랐는지 |

시작은 **기술통계 대조**로 한다. 표본이 쌓이기 전 회귀·모델은 과적합이다.

## 6. 연관 분석 (밖 ↔ 안)

**작품·인물 키워드 문자열 매칭**으로 시작한다. 우리 `work_title` 과 출연자명을
`trend_snapshot.title` 과 대조해 겹치면 표시. 카테고리 분포는 우리 작품의
`categoryId` 와 비교. 임베딩·LLM 매칭은 신호가 잡히는 걸 본 뒤에.

---

## 7. 화면

`dashboard/index.html` 에 탭 하나. 규칙은 RPC 에 두고 SPA 는 표시만 한다(R12·R15).

```
get_trend_report(p_date date) → jsonb
```

## 8. 순서 — 전부 구현됨

```
C1 미러(perf_sync, 매시간) ──┐
C2 트렌드(trend_scout, 03시) ─┼──→ P2 생성(trend_report, 05시) ──→ P3 화면(트렌드 탭)
C3 상수(algo_watch, 주 1회) ──┘
```

마이그레이션 `0097`(perf_studio_daily + trend_snapshot) · `0098`(trend_report + RPC).
스위치는 전부 `ops_config`: `trend_scout` · `trend_report` · `algo_watch`.
2026-08-27 운영자 지시로 켠 채 시작 — 끄는 것도 같은 자리다.

## 9. 비용

| 항목 | 일일 |
|---|---|
| YouTube Data API (3지역) | 3 유닛 (무료 한도의 0.03%) |
| laeebly 읽기 | 0 |
| Gemini (리포트 1회) | 소액 |
| Gemini (상수 조사, 주 1회) | 소액 |

## 10. 미결

- **LOOPY 합류** — laeebly 밖이라 `loopy_ledger` 경로가 따로다. 리포트에서 어떻게 한 장에 담을지

## 11. 노출 0 의 원인 — 판정 (2026-08-27 실측)

120일 깔때기로 "처음부터 0이었나, 받다가 꺼졌나"를 갈랐다. **처음부터 0이다.**

| 채널 | 개설 방식 | 첫 발행 | 첫 주 노출 |
|---|---|---|---:|
| 한 입 주막 | 개별 | 8/18 | **27,881** |
| 일괄 개설 17채널 | 7/24~8/04 몰아서 | — | **0~200** (중앙 ~7) |

유튜브는 갓 만든 채널에도 즉시 테스트 배포를 준다 — 한 입 주막이 그 증거다(첫 주
27,881). 일괄 개설군은 **첫 주부터 그 테스트 풀 자체를 받지 못했다.** 콘텐츠를 보고
내린 강등이 아니라 **채널 출생 시점의 억제**다. 따라서:

- 썸네일·훅·길이 수정으로는 **못 고친다** — 배포 이전 단계의 문제다
- 억제 채널에 계속 발행하는 건 제작비 소모다(배포 0 이 보장된 지출)
- 회복 징후 없음: 4주 추적에서 유의미한 상승 전환이 없다(락커룸 소량 누적이 최대)

**결정 실험(권고)**: 새 채널 1~2개를 **개별로**(한 입 주막 방식) 만들어 현재 죽은
작품(예: SNL 시즌8)을 같은 파이프라인으로 발행. 첫 주 노출이 서면 → 채널 정체성
문제 확정, 작품들을 개별 개설 채널로 점진 이관. 안 서면 → 소재 문제(한 입 주막
반례가 있어 가능성 낮음). **대체 채널을 다시 일괄로 만들지 말 것** — 그게 용의자다.

⚠ B급 순삭·재미쇼츠의 첫 주가 표에 없는 건 억제가 아니라 **데이터 창**이다 — 미러
보존 120일 앞이라(각 3/18·5/2 개설) 첫 주 구간이 창 밖이다. 오독 주의.
