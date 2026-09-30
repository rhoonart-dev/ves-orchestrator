// 계정 프로필 로봇 — 사람마다 하나씩(2026-09-29). 맥미니 로봇(node-robots.js)과 같은 흑백 도트 + 코발트 포인트.
// 8개를 미리 그려 두고, 로그인한 사람의 id 로 하나를 고른다 — 같은 사람은 늘 같은 로봇, 사람마다 제각각.
// 칸: 1 진한 몸 · 2 중간 · 3 밝은 · G 코발트 · W 하얀 눈. 색은 styles.css 의 .ar1·.ar2·.ar3·.arg·.arw(토큰 — 다크 모드 자동).
const robots = [
  ['....GG....','.....1....','..111111..','.11111111.','.1WW11WW1.','.1WW11WW1.','.11111111.','.11222211.','..111111..','...1..1...'],   // 안테나 꼬마
  ['.1......1.','..1....1..','.11111111.','.11111111.','11WW11WW11','11WW11WW11','1111111111','1112GG2111','.11111111.','.2......2.'],   // 뿔 인베이더
  ['..333333..','.33333333.','.11111111.','.11111111.','1WWW11WWW1','1111111111','1111111111','11.2222.11','1111111111','.1......1.'],   // 모자 쓴
  ['....11....','...1GG1...','..111111..','.11111111.','.1W1111W1.','.11111111.','..122221..','..111111..','.2.1..1.2.','2..1..1..2'],   // 오징어
  ['1........1','11......11','.11111111.','.1WW11WW1.','.1WW11WW1.','.11111111.','..1GGGG1..','..111111..','.11....11.','.1......1.'],   // 귀 큰
  ['...1111...','..111111..','.1WWWWWW1.','.1W1WW1W1.','.1WWWWWW1.','.11111111.','.11122111.','..111111..','...2..2...','..22..22..'],   // 고글
  ['..G....G..','...1..1...','..111111..','.11111111.','.11W11W11.','.11111111.','.11.22.11.','.11111111.','..1.11.1..','..2....2..'], // 더듬이
  ['.33....33.','.33333333.','.11111111.','.11111111.','11WW11WW11','1111111111','1122222211','.11111111.','..1.GG.1..','..1....1..'],   // 헤드폰
];
const cls = {'1':'ar1','2':'ar2','3':'ar3','G':'arg','W':'arw'};

export function robotIndex(seed) {
  return [...String(seed || '')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7) % robots.length;
}

export const ROBOT_COUNT = robots.length;

// 그 사람이 고른 로봇(계정 정보 user_metadata.avatar_robot)이 있으면 그것, 없으면 id 로 정해진 것
export function userRobotIndex(user) {
  const pick = user?.user_metadata?.avatar_robot;
  return Number.isInteger(pick) && pick >= 0 && pick < robots.length ? pick : robotIndex(user?.id);
}

export function avatarRobot(seed, index = null) {
  const rows = robots[index ?? robotIndex(seed)], h = rows.length, w = 10;
  let rects = '';
  rows.forEach((row, y) => [...row].forEach((ch, x) => {
    if (cls[ch]) rects += `<rect class="${cls[ch]}" x="${x}" y="${y}" width="1" height="1"/>`;
  }));
  // 12×12 칸 한가운데에 10×h 로봇
  return `<svg class="avatar-robot" viewBox="-1 ${-(12 - h) / 2} 12 12" aria-hidden="true" focusable="false" shape-rendering="crispEdges" style="stroke:none">${rects}</svg>`;
}
