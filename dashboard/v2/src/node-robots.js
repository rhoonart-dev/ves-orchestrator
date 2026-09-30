// 맥미니 로봇 — 흑백 인베이더 도트(2026-09-28). 몸은 회색 명도만(1 진 · 2 중간 · 3 밝은), 포인트는 코발트(G) 하나, 하얀 눈/알(W).
// mm-01…mm-06 이 순서대로 자기 로봇을 갖는다. 색은 home.css 의 .nb1·.nb2·.nb3·.nbg·.nbw(디자인 토큰)라 다크 모드가 저절로 맞는다.
// 상태: awake 대기 · working 작업 중(다리가 움직이거나, 팔 로봇은 팔을 올렸다 내렸다) · sleeping 잠(눈 감고 z) · unknown 응답 없음(흐린 몸에 ?)
const robots = [
  { // mm-01 딱정벌레
   name:'딱정벌레',
   rest:[
    '...3........3...',
    '....3......3....',
    '.....111111.....',
    '...1111111111...',
    '..21WW1111WW12..',
    '..21WW1111WW12..',
    '..211111111112..',
    '..311122221113..',
    '...11.1111.11...',
    '..2..2....2..2..',
  ],
   up:null },
  { // mm-02 뿔 꼬마
   name:'뿔 꼬마',
   rest:[
    '..1..........1..',
    '..11........11..',
    '...1111111111...',
    '..11WW1111WW11..',
    '..11WW1111WW11..',
    '..111111111111..',
    '..111122221111..',
    '...1111111111...',
    '.2..11111111..2.',
    '.22.11....11.22.',
    '....11....11....',
    '...333....333...',
  ],
   up:null },
  { // mm-03 비행접시
   name:'비행접시',
   rest:[
    '.......GG.......',
    '......1111......',
    '....11111111....',
    '...11WW11WW11...',
    '...11WW11WW11...',
    '...1111111111...',
    '.31111111111113.',
    '3333333333333333',
    '.2..2..2..2..2..',
    '................',
  ],
   up:null },
  { // mm-04 팔 인베이더
   name:'팔 인베이더',
   rest:[
    '...2........2...',
    '....2......2....',
    '...1111111111...',
    '..111111111111..',
    '.211GG1111GG112.',
    '2211GG1111GG1122',
    '2.111122221111.2',
    '3..1111111111..3',
    '...2.2....2.2...',
    '..2..2....2..2..',
  ],
   up:[
    '...2........2...',
    '....2......2....',
    '3..1111111111..3',
    '2.111111111111.2',
    '2211GG1111GG1122',
    '.211GG1111GG112.',
    '..111122221111..',
    '...1111111111...',
    '...2.2....2.2...',
    '..2..2....2..2..',
  ] },
  { // mm-05 네모 안테나 둘
   name:'네모 안테나 둘',
   rest:[
    '...G........G...',
    '...2........2...',
    '..111111111111..',
    '..111111111111..',
    '..11WW1111WW11..',
    '..11WW1111WW11..',
    '..111111111111..',
    '..111222222111..',
    '..111111111111..',
    '..3..1....1..3..',
    '..3..1....1..3..',
    '.33.11....11.33.',
  ],
   up:null },
  { // mm-06 외눈 모노클
   name:'외눈 모노클',
   rest:[
    '.......3........',
    '......111.......',
    '....11111111....',
    '...1111111111...',
    '..111GGGGG1111..',
    '..111GWWWG1111..',
    '..111GWWWG1111..',
    '..111GGGGG1111..',
    '..111111111111..',
    '...1122222211...',
    '....11111111....',
    '...2.2....2.2...',
    '..2..2....2..2..',
  ],
   up:null }
];
const CLS = {'1':'nb1','2':'nb2','3':'nb3','G':'nbg','W':'nbw'};
const H = 16;   // 로봇은 16칸 높이 가운데에 세운다 — 옆 글자(mm-01)와 높이가 맞게
const topOf = rows => Math.floor((H - rows.length) / 2);
const rectsFor = (rows) => {
  const top = topOf(rows);
  return rows.flatMap((row, y) => [...row].flatMap((c, x) => CLS[c] ? [`<rect class="${CLS[c]}" x="${x}" y="${y + top}" width="1" height="1"/>`] : [])).join('');
};
// 눈 감기 — 눈(W, 없으면 코발트 눈 G)의 윗줄은 몸색, 아랫줄은 중간 회색 한 줄
function closeEyes(rows) {
  const eye = rows.some(r => r.includes('W')) ? 'W' : 'G';
  return rows.map((row, y) => [...row].map((c, x) => c !== eye ? c : (rows[y + 1]?.[x] === eye ? '1' : '2')).join(''));
}
// 작업 중 두 번째 장면(다리 로봇) — 아래 두 줄(다리)을 한 칸 옆으로
const stepLegs = rows => [...rows.slice(0, -2), ...rows.slice(-2).map(r => r.slice(1) + '.')];
const question = ['.###.','#...#','...#.','..#..','.....','..#..'];
function unknownRows(rows) {
  const out = rows.map(r => [...r].map(c => CLS[c] ? '3' : '.'));
  const y0 = Math.max(0, Math.floor((rows.length - question.length) / 2)), x0 = 5;
  question.forEach((q, y) => [...q].forEach((c, x) => { if (c === '#' && out[y0 + y]?.[x0 + x] !== undefined) out[y0 + y][x0 + x] = '2'; }));
  return out.map(r => r.join(''));
}
const zPath = rows => rows.flatMap((row, y) => [...row].flatMap((c, x) => c === '#' ? [`M${x} ${y}h1v1h-1z`] : [])).join('');
const smallZ = zPath(['###','..#','.#.','#..','###']);
const bigZ = zPath(['####','...#','..#.','.#..','####']);

export function nodeRobotState(node, health, runningCount) {
  if (node.status === 'disabled') return 'sleeping';
  // A missing heartbeat is unknown, even when no running job is recorded.
  if (health.label === '응답 확인 필요') return 'unknown';
  if (health.online && runningCount > 0) return 'working';
  if (health.online && runningCount === 0) return 'sleeping';
  return 'awake';
}

export function nodeRobot(nodeId, state = 'awake') {
  // mm-01…mm-06 keep their own robot even if the node list is reordered.
  const number = String(nodeId).match(/(\d+)$/)?.[1];
  const seed = number ? Math.max(0, Number(number) - 1)
    : [...String(nodeId)].reduce((hash, char) => (hash * 31 + char.charCodeAt(0)) >>> 0, 0);
  const bot = robots[seed % robots.length];
  let body;
  if (state === 'working') {
    const second = bot.up || stepLegs(bot.rest);
    body = `<g class="robot-work-frame robot-work-first">${rectsFor(bot.rest)}</g><g class="robot-work-frame robot-work-second">${rectsFor(second)}</g>`;
  } else if (state === 'sleeping') body = rectsFor(closeEyes(bot.rest));
  else if (state === 'unknown') body = rectsFor(unknownRows(bot.rest));
  else body = rectsFor(bot.rest);
  // z 는 작게, 머리 오른쪽 위에
  const zTop = topOf(bot.rest);
  const sleepMarks = state === 'sleeping' ? `<g class="robot-sleep-marks"><path class="robot-z-small" transform="translate(13 ${zTop - 2}) scale(.35)" d="${smallZ}"/><path class="robot-z-big" transform="translate(14.4 ${zTop - 4}) scale(.5)" d="${bigZ}"/></g>` : '';
  const appearance = ['unknown','sleeping','working'].includes(state) ? state : 'awake';
  return `<svg class="node-robot robot-${appearance}" viewBox="0 0 16 16" aria-hidden="true" focusable="false" shape-rendering="crispEdges" style="stroke:none">${body}${sleepMarks}</svg>`;
}
