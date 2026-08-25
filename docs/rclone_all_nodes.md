# rclone 인증을 전 노드에 (2026-08-25, 사용자 지시)

> "rclone 인증을 모든 노드에서 가지고 있게 해줘."

## 왜

드라이브 소재를 받는 잡이 인증 있는 노드로 **묶여 있었다**(0090). 실측상 인증은
`mm-01`·`mm-02` 뿐이고 현지화 스택은 `mm-06` 이라 다른 기계였다. 전 노드에 깔면
그 고정을 풀 수 있고(0091), 한 노드가 병목이 되거나 그 노드가 죽어 드라이브 소재가
통째로 멈추는 일이 없어진다.

## 🛑 순서가 계약이다 — 배포가 먼저, 스위치가 나중

`ops_config.rclone_everywhere='on'` 을 먼저 켜면 인증 없는 노드가 잡을 집어 죽는다.
재시도해도 같은 노드 후보군이라 같은 자리다. 그래서 0091 은 스위치를 **켜지 않는다**.

## 1. 파일이 어디 있나

    $VES_HOME/secrets/rclone.conf        (보통 /opt/ves/secrets/rclone.conf)

⚠ **이 파일은 자격증명이다**(구글 OAuth 토큰). 내용을 화면에 찍거나 채팅·이슈에
붙여넣지 말 것. 아래 명령은 어느 것도 내용을 출력하지 않는다.

## 2. 인증이 있는 노드에서 나머지로 복사

가진 노드(mm-01) 에서:

```zsh
SRC=/opt/ves/secrets/rclone.conf
for n in mm-02 mm-03 mm-04 mm-05 mm-06; do
  echo "== $n"
  ssh $n 'sudo mkdir -p /opt/ves/secrets'
  scp -q "$SRC" "$n:/tmp/rclone.conf" &&
  ssh $n 'sudo install -m 600 -o $(stat -f %Su /opt/ves/secrets) /tmp/rclone.conf /opt/ves/secrets/rclone.conf && rm -f /tmp/rclone.conf && echo ok'
done
```

⚠ 소유자를 `/opt/ves/secrets` 와 맞춘다 — 워커가 못 읽으면 있으나 마나다.
⚠ 권한은 **600**. 다른 사용자가 읽을 수 있으면 토큰이 새는 것과 같다.

ssh 가 안 되면 각 노드에서 직접 만들어도 된다(내용은 1Password 등 비밀 보관소에서):

```zsh
sudo install -m 600 /dev/null /opt/ves/secrets/rclone.conf
sudo -e /opt/ves/secrets/rclone.conf        # 붙여넣고 저장
```

## 3. 6대 확인 — **내용은 안 찍는다**

각 노드에서:

```zsh
ls -l /opt/ves/secrets/rclone.conf
rclone --config /opt/ves/secrets/rclone.conf listremotes
```

`ls` 는 `-rw-------` 여야 하고, `listremotes` 는 원격 이름 한 줄이 나와야 한다
(이름만 나온다 — 토큰은 안 나온다).

한 대라도 안 되면 **스위치를 켜지 말 것.**

## 4. 스위치

6대가 다 통과한 뒤에:

```sql
INSERT INTO public.ops_config (key, value) VALUES ('rclone_everywhere','on')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now();
```

이때부터 새로 서는 드라이브 acquire 잡에 노드 핀이 안 붙는다.
⚠ **이미 큐에 서 있는 잡은 그대로다**(캡은 잡을 만들 때 박힌다). 급하면 그 잡을
취소하고 다시 걸면 된다.

## 되돌리기

```sql
UPDATE public.ops_config SET value='off' WHERE key='rclone_everywhere';
```

다음 잡부터 다시 `drive_sync_node` 로 묶인다. 파일을 지울 필요는 없다.
