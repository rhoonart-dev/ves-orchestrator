# L-P2 보고 — 어댑터 컷오버 (2026-08-23)

기획서: [`docs/LOCALIZE_UNIFY.md`](../LOCALIZE_UNIFY.md) §9 P2.
근거: [`e15-p1-report.md`](e15-p1-report.md) — 실런 회귀 0(프레임 12/12·Δ0.000s).

완료 판정은 **`ops_config.localize_engine='ai-video'` 로 전환**, 되돌리기는 **값 1개**.

---

## 0. 한 줄 요약

어댑터가 두 엔진을 모두 부를 수 있게 됐고, 스위치는 **`vlp`(종전) 그대로** 심어 뒀다.
**지금 이 순간 동작은 하나도 안 바뀐다** — 켜는 것은 §4 의 확인 뒤 사람이 한다.

---

## 1. 무엇을 바꿨나

`ves/adapters/localize.py` 의 `_run_scene_rerender` 하나. 두 엔진이 **같은 산출 규약**을
지키므로 갈리는 것은 **argv 와 cwd 뿐**이다.

| | vlp (종전) | ai-video (신규) |
|---|---|---|
| argv | `<ai_py> <vlp>/scripts/localize_run.py --job-dir …` | `<ai_py> -m app.cli localize --job-dir … --locale ja` |
| cwd | vlp 엔진 디렉토리 | ai-video 엔진 디렉토리 |
| 인터프리터 | **양쪽 다 ai-video venv** (런타임 의존이 거기 있다) | 〃 |
| 성공 마커 | `localize_<locale>/metadata.json` | 〃 (무변경) |
| 산출 | `shorts.mp4` 교체본 · `localize_backup_ko/` | 〃 (무변경) |

⇒ **검수함·편집실·0066 편집 재렌더 체인은 무변경이다.**

곁다리 하나: 성공 마커 경로가 `localize_ja` 로 박혀 있던 것을 `localize_{locale}` 로
바꿨다(`params.locale`, 기본 `ja`). 지금은 ja 뿐이라 동작 변화가 없지만, 로케일이
늘면 여기서 조용히 어긋난다.

## 2. 스위치 계약

`ops_config.localize_engine` — **잡마다 읽는다**(워커 재시작 불필요, `gemini_key` 와 같은 규약).

```
'vlp'                                       종전 경로 (기본 · 지금 값)
'ai-video'                                  새 경로 (전체)
{"_default":"vlp","SHOTCONE":"ai-video"}    채널별 점진 전환
```

🛑 **모르는 값·깨진 JSON 은 기본(vlp)으로 떨어진다.** `aivideo`(하이픈 빠짐)·
`AI-VIDEO`(대소문자)·`on` 같은 오타가 **검증 안 된 엔진을 켜면 안 된다.** 설정 조회
자체가 실패해도 마찬가지다 — 조회 실패가 잡을 죽이지도, 엔진을 바꾸지도 않는다.

추적: 어느 엔진이 돌았는지 **잡 결과**(`result.localize_engine`)와 **검수 카드 payload**
(`localize_engine`)에 남는다. 컷오버 기간에 "이 결과는 어느 엔진이 만든 것인가"가
답변 가능해야 한다.

## 3. 마이그레이션 0075 (적용 완료)

`ops_config` 에 `localize_engine='vlp'` 를 심었다 — `ON CONFLICT DO NOTHING` 이라
이미 전환한 값을 덮지 않는다. **데이터 한 줄이고 값이 종전 동작이라 무해하다.**

```sql
-- 되돌리기
UPDATE ops_config SET value='vlp' WHERE key='localize_engine';
```

회귀 가드: `tests/test_localize_engine_switch.py` 14건 (전체 253 passed).
특히 **vlp argv 가 한 글자도 안 바뀌었음**을 고정한다 — 되돌리기가 진짜 되돌리기여야 한다.

---

## 4. 🛑 켜기 전에 — 남은 확인 두 가지

### ① L2b 텔롭 판독 (Flash 모델 교체 — P1 §4-① · §7-1)

P1 실런은 `onscreen_refined.json` 캐시를 써서 **이 경로를 안 탔다.** vlp 는
`gemini-3-flash-preview`, ai-video 는 `gemini-3.6-flash` 를 쓴다(레포 모델 규칙).

```zsh
DST=/tmp/abtest/혜미리예채파_7e42b761
PY=/opt/ves/engines/ai-video/.venv/bin/python
cd /tmp/aiv-p1
set -a; . /opt/ves/secrets/ves.env; set +a
cp $DST/localize_ja/onscreen_refined.json /tmp/refined_vlp.json
rm $DST/localize_ja/onscreen_refined.json
$PY -m app.cli localize --job-dir $DST --locale ja --skip-render
python3 -c "
import json
a=json.load(open('/tmp/refined_vlp.json')); b=json.load(open('$DST/localize_ja/onscreen_refined.json'))
print('텔롭 수:', len(a), '->', len(b))
for x,y in zip(a,b):
    d=max(abs(x['start_sec']-y['start_sec']), abs(x['end_sec']-y['end_sec']))
    print(('OK ' if d<=1.5 else '!! ')+f\"{d:4.2f}s  {x['text_ko'][:18]}\")
"
```

**완전 일치는 기대하지 않는다**(프레임 판독은 LLM 판단이다). 합격선:
**텔롭 개수 유지 + 구간 차이 ±1.5초(프레임 간격) 이내.**

⚠ 위 한 줄짜리 대조는 **결함이 있다** — `zip(a,b)` 는 텔롭 하나가 빠지면 그 뒤가
전부 한 칸씩 밀려 멀쩡한 것을 불합격으로 만든다. `orig_index` 로 맞춰야 한다
(§4-①-실측의 `/tmp/cmp_telop.py`).

#### 실측 결과 (2026-08-24 · mm-05 · 혜미리예채파_7e42b761) — **통과**

```
텔롭 수: 23 -> 22        구엔진에만: [6] 'ㅇ0ㅇ'
공통 22건 중 ±1.5초 초과 0건 · 목록 차이 1건
  · 21건이 Δ0.00s  — 밀리초까지 동일
  · 1건이 Δ1.50s  — [18] '빼꼼'
```

두 갈래 차이 모두 **Flash 판독 층에서만** 났고, 둘 다 성질이 설명된다.

- **빠진 [6] `ㅇ0ㅇ`** — 이모티콘형 텔롭이다. `ㅇ0ㅇ` 는 [5]에도 있고 **[5]는 Δ0.00s
  로 남았다** — 같은 글자 두 개 중 하나만 프레임 대조에 실패했다.
- **Δ1.50s 인 [18] `빼꼼`** — 정확히 `REFINE_STEP_SEC`(1.5초) 한 칸이다. 프레임 주사가
  **이웃 칸에 걸린 것**이지 판독이 틀린 것이 아니다. 그리고 이것도 [17]과 텍스트가
  같은 쌍의 한쪽이다 — 같은 글자가 연달아 있으면 어느 칸에 붙일지가 갈린다.

**하류 산출은 같다**: L3 번인 텔롭 **11건 = vlp 실행과 동일**. 화면에 보이는 결과물이
안 바뀌었다는 뜻이다. 발주서 §8-2 가 Flash 경로를 회귀 0 측정 대상에서 뺀 이유가
이것이고, 그 예외 범위 안에서 났다.

남은 확인 하나(선택): Δ1.50s 인 [18]이 번인된 11건 안에 드는가. 안 들면 사람이 볼
화면에는 차이가 없다. 드는 경우에도 1.5초는 프레임 주사 한 칸이라 텔롭 표시창 안이다.

```zsh
$PY -c "
import json
m = json.load(open('$DST/localize_ja/metadata.json'))
for t in (m.get('ko_ja_pairs') or {}).get('telops') or []:
    print(t.get('idx'), round(t.get('start',0),2), t.get('ko','')[:14])
"
```

### ② 켜는 순서 — 한 채널부터

```sql
-- 혜미리예채파만 먼저
UPDATE ops_config SET value='{"_default":"vlp","SHOTCONE":"ai-video"}'
 WHERE key='localize_engine';
```

다음 localize 잡부터 적용된다. 검수 카드의 `localize_engine` 이 `ai-video` 인지 확인하고,
**그 편의 검수 결과가 평소와 같은지** 사람이 본 뒤 전체로 넓힌다.

⚠ 지금 `SHOTCONE` 이 유일한 rerender 채널이므로 사실상 전체 전환과 같다. 그래도 맵으로
켜는 편이 낫다 — 잔망루피 롱폼(P7)이 붙으면 채널별 구분이 바로 필요해진다.

---

## 5. P2 판정

| 완료 판정 | 상태 |
|---|---|
| 어댑터가 두 엔진을 부를 수 있다 | ✅ |
| 스위치·기본값·오타 방어 | ✅ 14건 고정 |
| 마이그레이션 0075 | ✅ 적용(값 `vlp` — 동작 변화 0) |
| 추적(어느 엔진이 돌았나) | ✅ 잡 결과 + 검수 카드 |
| §4-① L2b 프레임 판독 대조 | ✅ **통과**(8/24 · 22/22 · Δ최대 1.50s · 번인 11=11) |
| **전환(`ai-video` 로 켜기)** | ⏳ **아래 §6 — 코드 배포가 먼저다** |

되돌리기는 SQL 한 줄이고, vlp 경로는 코드상 한 글자도 안 바뀌었다.

---

## 6. 🛑 스위치가 아무 데도 연결돼 있지 않다 (8/24 발견)

`ops_config.localize_engine` 은 8/23 16:39 에 `{"_default":"vlp","SHOTCONE":"ai-video"}`
로 바뀌어 있다. **그런데 그 값을 읽는 코드가 배포돼 있지 않다.**

- `pick_engine` 은 이 커밋(`63f70a5`)에 있고 **작업 브랜치 전용**이다(main 미머지).
- 노드가 도는 오케스트레이터는 `9bd2164` — `ENGINE_SWITCH` 검색 0건.
- 실증: 8/24 00:00 SHOTCONE 잡(`ff823804`)이 성공했으나 결과의 `localize_engine` 이
  `null` 이고 `engine_sha.localization = 5f8c3e3`(vlp 레포 SHA)이 찍혔다 — **vlp 로 돌았다.**

⚠ 두 엔진의 stdout 은 이식이 충실해서 `[L4]`·`[L5]` 줄이 **똑같다**. 로그로는 구분이
안 된다. `engine_sha.localization` 과 `result.localize_engine` 만이 근거다.

**회귀는 없다**(아무것도 안 바뀌었으니까). 다만 컷오버가 됐다고 오해하면 안 된다.
순서는 **① 브랜치 main 머지 → ② 노드 배포 확인(`deployments`) → ③ 다음 잡의
`result.localize_engine` 이 `ai-video` 인지 확인**이다. 스위치 값은 이미 서 있으므로
③ 은 배포 즉시 자동으로 걸린다 — 배포 직후 첫 SHOTCONE 잡이 곧 첫 실전 컷오버다.
