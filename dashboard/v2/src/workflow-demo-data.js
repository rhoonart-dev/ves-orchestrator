// Local examples; channel assignments and states are simulated.
export const scenarios = [
  {
    "id": "required",
    "label": "검수 필수",
    "work": "로또 1등도 출근합니다",
    "channel": "재미쇼츠",
    "policy": "required",
    "revision": false,
    "missing": false,
    "media": {
      "id": "2c04da7e7c9f097c",
      "title": "참고 배려해 줬더니 / 선 넘은 선배에게",
      "filename": "선_넘은_선배에게_최종수정.mp4",
      "src": "assets/local-media/2c04da7e7c9f097c.mp4",
      "poster": "assets/local-media/2c04da7e7c9f097c.jpg",
      "sourceKind": "export",
      "width": 1080,
      "height": 1920,
      "duration": 65.866667
    }
  },
  {
    "id": "direct",
    "label": "검수 없이 예약",
    "work": "신병",
    "channel": "락커룸",
    "policy": "none",
    "revision": false,
    "missing": false,
    "media": {
      "id": "1ddba18292e3dae3",
      "title": "﻿35도 넘으면 낮잠 잔다 / 온도계 조작에 목숨 건 / 군대",
      "filename": "final_1080x1920.mp4",
      "src": "assets/local-media/1ddba18292e3dae3.mp4",
      "poster": "assets/local-media/1ddba18292e3dae3.jpg",
      "sourceKind": "render",
      "width": 1080,
      "height": 1920,
      "duration": 64.564583
    }
  },
  {
    "id": "revision",
    "label": "수정 요청부터",
    "work": "지금 불륜이 문제가 아닙니다(c)",
    "channel": "부먹?찍먹?",
    "policy": "required",
    "revision": true,
    "missing": false,
    "media": {
      "id": "0f6d8b5a55407ed0",
      "title": "지금 불륜이 문제가 아닙니다(c) · 완성본 01",
      "filename": "jigeum_ep04_1.mp4",
      "src": "assets/local-media/0f6d8b5a55407ed0.mp4",
      "poster": "assets/local-media/0f6d8b5a55407ed0.jpg",
      "sourceKind": "render",
      "width": 1080,
      "height": 1920,
      "duration": 55.221866
    }
  },
  {
    "id": "missing",
    "label": "파일 누락 체험",
    "work": "가왕쇼",
    "channel": "한 입 주막",
    "policy": "required",
    "revision": false,
    "missing": true,
    "media": {
      "id": "38dcf31987ca392c",
      "title": "노래로 관객 모았더니 / 대놓고 표 뺏는 가왕들",
      "filename": "shorts_v1.mp4",
      "src": "assets/local-media/38dcf31987ca392c.mp4",
      "poster": "assets/local-media/38dcf31987ca392c.jpg",
      "sourceKind": "render",
      "width": 1080,
      "height": 1920,
      "duration": 57.666667
    }
  }
];
