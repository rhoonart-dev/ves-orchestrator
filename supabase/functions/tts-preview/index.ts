// ─────────────────────────────────────────────────────────────────────────────
// tts-preview — 편집실 내레이션 **온디맨드 미리듣기** (사용자 요청 2026-08-22)
//
// 왜 있나: 편집실 ▶ 버튼은 지금까지 **직전 렌더 때 합성된 mp3**(tts[].key)만 틀어
// 줬다. 목소리를 바꾸면 그 파일은 옛 목소리라 '▶·구본'으로 바뀌고, 새로 추가한 줄은
// key 자체가 없어 버튼이 아예 안 뜬다. 그래서 일레븐랩스 목소리 20종을 열어 놓고도
// **고르기 전에 들어 볼 방법이 없었다** — 안내문은 "한 줄로 먼저 들어보고 정하세요"
// 라고 말하는데 그럴 수가 없었다. 이 함수가 그 구멍을 메운다.
//
// 왜 엣지 함수인가: ElevenLabs 키를 브라우저에 둘 수 없다. 노드(엔진)를 거치면
// claim→실행→업로드라 '미리듣기'가 아니다. 키가 서버에만 있고 즉시 응답하는 자리는
// 여기뿐이다.
//
// ⚠ 합성 파라미터는 엔진(app/modules/tts.py `_synthesize_elevenlabs`)과 **같아야 한다** —
// 미리듣기와 완성본이 다르면 미리듣기가 거짓말이 된다. 아래 상수는 그 복제본이고,
// 엔진이 바꾸면 여기도 바꿔야 한다(tests/test_pure.py 가 값 일치를 검사한다).
//
// 범위: `elevenlabs:{voice_id}` 값만 합성한다. 라벨(ko_female 등)은 엔진이 든
// EL_VOICE_PRESETS 매핑을 거쳐야 하는데, 그 표를 여기 복제하면 정본이 둘이 된다
// (registry 원칙). 라벨 목소리는 종전대로 저장된 mp3 를 튼다.
//
// 짝: dashboard/index.html(edTtsPreview) · ops_config.editor_tts_elevenlabs 게이트
// ─────────────────────────────────────────────────────────────────────────────
import { createClient } from "jsr:@supabase/supabase-js@2";

// ── 엔진 복제 상수 (app/modules/tts.py) ──────────────────────────────────────
const EL_SPEED: Record<string, number> = {
  very_slow: 0.7, slow: 0.85, normal: 1.0, fast: 1.1, very_fast: 1.2,
};
const DEFAULT_SPEED = "normal";
const EL_MODEL_ID = Deno.env.get("ELEVENLABS_MODEL_ID") ?? "eleven_multilingual_v2";
const EL_OUTPUT_FORMAT = "mp3_44100_128";
const EL_STABILITY = 0.5;
const EL_SIMILARITY = 0.75;

// 미리듣기는 **한 줄**이다. 긴 텍스트로 크레딧이 새지 않게 자른다(자르면 알린다).
const MAX_CHARS = 300;
const VOICE_PREFIX = "elevenlabs:";
// 0073·엔진 _EL_VOICE_ID_RE 와 같은 형태 검증.
const VOICE_ID_RE = /^[A-Za-z0-9]{16,32}$/;
// 편집실을 고칠 수 있는 사람이면 들어볼 수 있어야 한다(대시보드 can("reviewer") 와 동일).
const ALLOWED_ROLES = ["reviewer", "operator", "admin"];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json; charset=utf-8" },
  });

Deno.serve(async (req) => {
  if (req.method !== "POST") return json({ error: "POST 만 받습니다" }, 405);

  const apiKey = Deno.env.get("ELEVENLABS_API_KEY");
  if (!apiKey) {
    return json({ error:
      "이 함수의 시크릿에 ELEVENLABS_API_KEY 가 없습니다 — Supabase 프로젝트 " +
      "Settings → Edge Functions → Secrets 에 넣으세요. 키 없이 조용히 넘어가지 않습니다."
    }, 503);
  }

  // ── 인증·권한 ──────────────────────────────────────────────────────────────
  // 호출자의 JWT 로 본다. service_role 로는 auth.uid() 가 NULL 이라 통과하지 못한다.
  const authHeader = req.headers.get("Authorization") ?? "";
  const sb = createClient(
    Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_ANON_KEY")!,
    { global: { headers: { Authorization: authHeader } } },
  );
  const { data: { user } } = await sb.auth.getUser();
  if (!user) return json({ error: "로그인이 필요합니다" }, 401);

  const { data: roleRow } = await sb.from("user_roles").select("role").maybeSingle();
  const role = roleRow?.role ?? "viewer";
  if (!ALLOWED_ROLES.includes(role)) {
    return json({ error: `미리듣기는 reviewer 이상입니다(현재: ${role})` }, 403);
  }

  // ── 게이트 ────────────────────────────────────────────────────────────────
  // 목소리 선택칸을 닫아 둔 동안에는 합성도 하지 않는다 — 화면에 없는 기능에
  // 돈이 나가면 안 된다.
  const { data: gate } = await sb.from("ops_config")
    .select("value").eq("key", "editor_tts_elevenlabs").maybeSingle();
  if ((gate?.value ?? "off") !== "on") {
    return json({ error: "일레븐랩스 목소리 게이트가 꺼져 있습니다(ops_config.editor_tts_elevenlabs)" }, 409);
  }

  // ── 입력 ──────────────────────────────────────────────────────────────────
  let body: { text?: string; voice?: string; speed?: string };
  try { body = await req.json(); }
  catch { return json({ error: "JSON 본문이 아닙니다" }, 400); }

  const raw = String(body.text ?? "").trim();
  if (!raw) return json({ error: "문구가 비어 있습니다" }, 400);
  const truncated = raw.length > MAX_CHARS;
  const text = truncated ? raw.slice(0, MAX_CHARS) : raw;

  const voice = String(body.voice ?? "");
  if (!voice.startsWith(VOICE_PREFIX)) {
    return json({ error:
      "온디맨드 미리듣기는 일레븐랩스 목소리만 됩니다 — 기본(edge-tts) 목소리는 " +
      "라벨→voice_id 매핑을 엔진이 들고 있어 재렌더 후에만 들을 수 있습니다."
    }, 400);
  }
  const voiceId = voice.slice(VOICE_PREFIX.length).trim();
  if (!VOICE_ID_RE.test(voiceId)) {
    return json({ error: `voice_id 형태가 아닙니다: ${voiceId} (영숫자 16~32자)` }, 400);
  }

  const speedLabel = String(body.speed ?? DEFAULT_SPEED);
  const speed = EL_SPEED[speedLabel] ?? EL_SPEED[DEFAULT_SPEED];

  // ── 합성 (엔진과 같은 계약) ────────────────────────────────────────────────
  const url = `https://api.elevenlabs.io/v1/text-to-speech/${voiceId}` +
              `?output_format=${EL_OUTPUT_FORMAT}`;
  let resp: Response;
  try {
    resp = await fetch(url, {
      method: "POST",
      headers: { "xi-api-key": apiKey, "content-type": "application/json" },
      body: JSON.stringify({
        text,
        model_id: EL_MODEL_ID,
        voice_settings: {
          stability: EL_STABILITY,
          similarity_boost: EL_SIMILARITY,
          speed,
        },
      }),
    });
  } catch (e) {
    return json({ error: `일레븐랩스에 닿지 못했습니다: ${e}` }, 502);
  }

  if (!resp.ok) {
    const detail = (await resp.text()).slice(0, 300);
    // 404 = 계정에 없는 voice_id(라이브러리에서 담지 않았거나 만료). 흔한 실수라 따로 짚는다.
    const hint = resp.status === 404
      ? " — 이 voice_id 가 계정에 없습니다. 일레븐랩스 보이스 라이브러리에서 담았는지 확인하세요."
      : "";
    return json({ error: `일레븐랩스 ${resp.status}: ${detail}${hint}` }, 502);
  }

  // base64 로 돌려준다 — functions.invoke 의 바이너리 처리에 기대지 않는다(예측 가능).
  const buf = new Uint8Array(await resp.arrayBuffer());
  let bin = "";
  for (let i = 0; i < buf.length; i += 0x8000) {
    bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
  }
  return json({
    audio: btoa(bin),
    mime: "audio/mpeg",
    chars: text.length,
    truncated,
    voice_id: voiceId,
    model_id: EL_MODEL_ID,
    speed,
  });
});
