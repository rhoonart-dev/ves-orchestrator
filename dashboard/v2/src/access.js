// 권한 관리 — 예전 VES '권한 관리'(renderAdmin, 0015)를 옮겼다. 관리자만. 읽기·바꾸기 모두 RPC 로만(list_user_roles · set_user_role).
// 자기 권한은 못 바꾼다(잘못 내려서 아무도 관리자가 아니게 되는 사고 방지 — RPC 도 막는다).
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const ROLES = [["viewer","보기만"],["reviewer","검수"],["operator","운영"],["admin","관리자"]];

export function mountAccess(root, {client = null, role = null, email = ""} = {}){
  if (!client){ root.innerHTML = '<p class="acc-note">로그인하면 볼 수 있어요.</p>'; return () => {}; }
  if (role !== "admin"){ root.innerHTML = '<section class="acc-panel"><p class="acc-note">관리자만 볼 수 있어요.</p></section>'; return () => {}; }
  let rows = null, err = "", msg = "", dead = false;
  async function load(){
    const {data, error} = await client.rpc("list_user_roles");
    if (dead) return;
    rows = error ? [] : (data || []).sort((a, b) => ROLES.findIndex(r => r[0] === b.role) - ROLES.findIndex(r => r[0] === a.role) || String(a.email).localeCompare(String(b.email)));
    err = error ? error.message : "";
    // 닉네임(0139 user_profiles) — 계정 창에서 각자 정한 이름
    const ids = (rows || []).map(u => u.user_id).filter(Boolean);
    if (ids.length){ const {data:pf} = await client.from("user_profiles").select("user_id,nickname").in("user_id", ids);
      if (dead) return; const nick = new Map((pf || []).map(p => [p.user_id, p.nickname])); rows.forEach(u => { u.nickname = nick.get(u.user_id) || ""; }); }
    draw();
  }
  function draw(){
    if (dead) return;
    const me = String(email || "").toLowerCase();
    const body = !rows ? '<p class="acc-note">불러오는 중…</p>'
      : err ? `<p class="acc-note acc-err">목록을 불러오지 못했어요. ${esc(err)}</p>`
      : !rows.length ? '<p class="acc-note">사용자가 없어요.</p>'
      : `<div class="acc-table"><table><thead><tr><th>이메일</th><th>닉네임</th><th>권한</th><th>메모</th><th></th></tr></thead><tbody>${rows.map((u, i) => {
          const self = String(u.email).toLowerCase() === me;
          return `<tr data-i="${i}"><td class="acc-mail"><span>${esc(u.email)}</span>${self ? '<small>나</small>' : ""}</td>
            <td class="acc-nick">${esc(u.nickname || "")}</td>
            <td><select aria-label="권한" ${self ? "disabled" : ""}>${ROLES.map(([k, l]) => `<option value="${k}" ${u.role === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
            <td><input type="text" value="${esc(u.note || "")}" placeholder="메모" aria-label="메모" ${self ? "disabled" : ""}></td>
            <td>${self ? "" : '<button type="button" class="acc-save" disabled>저장</button>'}</td></tr>`;
        }).join("")}</tbody></table></div>`;
    root.innerHTML = `<div class="acc-page"><header class="acc-head"><div><h2>사용자 권한</h2>
        <p>보기만 → 검수 → 운영 → 관리자 순으로 할 수 있는 일이 늘어요. 바꾸면 바로 적용돼요.<br>새 팀원은 로그인 계정이 먼저 있어야 여기 보여요. 내 권한은 바꿀 수 없어요.</p></div>
        <button type="button" class="acc-reload">다시 읽기</button></header>
      <p class="acc-msg" role="status">${esc(msg)}</p>
      <section class="acc-panel">${body}</section></div>`;
    root.querySelector(".acc-reload").onclick = () => { msg = ""; rows = null; draw(); load(); };
    root.querySelectorAll("tr[data-i]").forEach(tr => {
      const u = rows[+tr.dataset.i], sel = tr.querySelector("select"), note = tr.querySelector("input"), btn = tr.querySelector(".acc-save");
      if (!btn) return;
      const dirty = () => { btn.disabled = sel.value === u.role && note.value.trim() === (u.note || ""); };
      sel.onchange = dirty; note.oninput = dirty;
      btn.onclick = async () => {
        btn.disabled = true;
        const {error} = await client.rpc("set_user_role", {p_email:u.email, p_role:sel.value, p_note:note.value.trim() || null});
        if (dead) return;
        msg = error ? `안 됐어요. ${error.message}` : `${u.email} 권한을 ${ROLES.find(r => r[0] === sel.value)[1]}(으)로 바꿨어요.`;
        load();
      };
    });
  }
  draw(); load();
  return () => { dead = true; };
}
