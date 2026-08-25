# rclone 인증을 전 노드에 (2026-08-25, 사용자 지시 · **완료**)

> "rclone 인증을 모든 노드에서 가지고 있게 해줘."

## 왜

드라이브 소재를 받는 잡이 인증 있는 노드로 **묶여 있었다**(0090). 인증은 `mm-01`·`mm-02`
뿐이고 현지화 스택은 `mm-06` 이라 다른 기계였다. 전 노드에 깔면 그 고정을 풀 수 있고
(0091), 한 노드가 병목이 되거나 그 노드가 죽어 드라이브 소재가 통째로 멈추는 일이 없다.

## 결과 (2026-08-25 19:27~19:34 KST)

6대 전부 `/opt/ves/secrets/rclone.conf` 527B `-rw-------` · `rclone listremotes` → `gdrive:`.
`ops_config.rclone_everywhere='on'` 켰다. 확인 시점에 노드 핀이 박힌 대기 잡은 **0건**
이었다(중간 상태에서 갈아탄 잡 없음).

## 노드 ↔ ssh 주소 (실측)

⚠ **계정 번호와 노드 번호가 한 칸 어긋난다.** `mm-03` 의 로그인 계정이 `lunaleuteumaeg4`
다 — 계정 이름만 보고 노드를 짐작하면 틀린다. 정본은 각 기계의 `VES_NODE_ID` 다.

| 노드 | ssh 주소 |
|---|---|
| mm-01 | `lunaleuteumaeg1@lunaleuteumaeg1ui-Macmini.local` |
| mm-02 | `lunaleuteumaeg2@lunaleuteumaeg2ui-Macmini.local` |
| mm-03 | `lunaleuteumaeg4@3-Mac-mini.local` |
| mm-04 | `lunaleuteumaeg4@192.168.0.80` — ⚠ 아래 참조 |
| mm-05 | `lunaleuteumaeg5@lunaleuteumaeg5s-Mac-mini.local` |
| mm-06 | `lunaleuteumaeg6@lunaleuteumaeg6ui-Macmini.local` |

⚠ **mm-04 의 `.local` 이름이 mm-01 에서 안 풀린다**(`lunaleuteumaeg4ui-Macmini.local`).
기계는 살아 있고 **다른 4대에서는 그 이름이 정상으로 풀린다** — mm-01 쪽 mDNS 문제다.
IP(`192.168.0.80`)로 붙으면 된다. IP 가 바뀌었으면 닿는 노드에서 이름을 ping 해 다시 얻는다:

```zsh
ssh lunaleuteumaeg2@lunaleuteumaeg2ui-Macmini.local 'ping -c1 -t2 lunaleuteumaeg4ui-Macmini.local | head -2'
```

노드 ID 확인(다른 시크릿은 안 나온다):

```zsh
ssh <주소> 'grep -h "^VES_NODE_ID=" /etc/ves/node.env /opt/ves/secrets/ves.env 2>/dev/null | head -1'
```

## 파일

    /opt/ves/secrets/rclone.conf        (VES_HOME=/opt/ves — 6대 동일)

⚠ **자격증명이다**(구글 OAuth 토큰). 내용을 화면에 찍거나 채팅·이슈에 붙여넣지 말 것.
이 문서의 명령은 어느 것도 내용을 출력하지 않는다.
✅ **sudo 가 필요 없다** — `/opt/ves/secrets` 소유자가 각 노드의 로그인 계정이다.

## 배포 절차 (다시 할 일이 있으면)

인증이 있는 노드(mm-01)에서, stdin 으로 밀어 넣는다. ssh 비밀번호는 터미널이 따로 묻는다:

```zsh
for h in lunaleuteumaeg4@3-Mac-mini.local \
         lunaleuteumaeg4@192.168.0.80 \
         lunaleuteumaeg5@lunaleuteumaeg5s-Mac-mini.local \
         lunaleuteumaeg6@lunaleuteumaeg6ui-Macmini.local; do
  echo "== $h"
  ssh "$h" 'umask 077; mkdir -p /opt/ves/secrets && cat > /opt/ves/secrets/rclone.conf && chmod 600 /opt/ves/secrets/rclone.conf && ls -l /opt/ves/secrets/rclone.conf' < /opt/ves/secrets/rclone.conf
done
```

확인 — **원격 이름만** 나온다(토큰은 안 나온다):

```zsh
ssh <주소> 'RC=""; for p in /opt/homebrew/bin/rclone /usr/local/bin/rclone; do [ -x "$p" ] && RC="$p"; done; if [ -z "$RC" ]; then echo "rclone 없음 - brew install rclone"; else echo "$RC"; "$RC" --config /opt/ves/secrets/rclone.conf listremotes; fi'
```

⚠ **`command -v rclone` 로 확인하지 마라 — 6대 전부 '미설치'로 나온다.** 비대화형 ssh 의
PATH 에 `/opt/homebrew/bin` 이 없어서 그렇고, 실제로는 6대 다 `/opt/homebrew/bin/rclone`
에 있다. 엔진(`register_drive._rclone_bin`)도 PATH 다음에 그 절대경로 두 곳을 본다.
⚠ zsh 노드는 `interactive_comments` 가 꺼져 있다 — 붙여넣는 명령에 `#` 주석을 넣지 말 것.

## 🛑 순서가 계약이다 — 배포가 먼저, 스위치가 나중

`ops_config.rclone_everywhere='on'` 을 먼저 켜면 인증 없는 노드가 잡을 집어 죽는다.
재시도해도 같은 노드 후보군이라 같은 자리다. 그래서 0091 은 스위치를 **켜지 않는다**.

```sql
INSERT INTO public.ops_config (key, value) VALUES ('rclone_everywhere','on')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```

⚠ **이미 큐에 서 있는 잡은 그대로다**(캡은 잡을 만들 때 박힌다). 급하면 그 잡을 취소하고
다시 걸면 된다.

## 되돌리기

```sql
UPDATE public.ops_config SET value='off' WHERE key='rclone_everywhere';
```

다음 잡부터 다시 `drive_sync_node` 로 묶인다. 파일을 지울 필요는 없다.

## 곁다리 — 인입(`drive_sync_nodes`)은 별개 스위치다

`rclone_everywhere` 는 **드라이브 소재 acquire**(잔망루피 쇼츠) 하나만 푼다.
KR 소재 인입(`drive_watch`·`source_watch`·`drive_balance`)은 여전히
`ops_config.drive_sync_nodes = 'mm-01,mm-02'` 두 대에 라운드로빈으로 몰려 있다
(`docs/HANDOFF-2026-08-12.md` §165 가 "rclone.conf 배포 필요" 로 남겨 둔 그 항목).

이제 파일은 6대에 다 있으니 넓힐 수 있다 — **다만 별건이라 같이 켜지 않았다**(인입은
디스크·대역을 많이 쓰고, 현지화 노드에 인입까지 얹으면 겹친다). 넓힐 때:

```sql
UPDATE public.ops_config SET value='mm-01,mm-02,mm-03,mm-04,mm-05'
 WHERE key='drive_sync_nodes';
```

⚠ `mm-06` 은 뺐다 — 현지화(인페인팅 5~10시간)가 도는 유일한 노드다.
