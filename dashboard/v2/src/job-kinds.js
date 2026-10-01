// 맥미니 잡 종류(job_queue.kind) → 화면에 쓰는 한국어 이름. 작업 이력 · 홈 · 맥미니 화면이 같이 쓴다.
// 새 잡 종류가 생기면 여기에만 더한다(오케스트레이터 ves/adapters/base.py 의 register 목록과 맞춘다).
export const JOB_KIND={
 acquire:'소스 준비',generate:'영상 제작',upload_artifacts:'결과 업로드',ingest:'기록 적재',evaluate:'자동 검사',publish:'발행',
 publish_external:'외부 영상 발행',localize:'일본어 번역',sync_drive_folder:'드라이브 인입',register_playlist:'유튜브 클립 확인',
 register_sources:'소스 등록',scan_drive_shorts:'드라이브 쇼츠 확인',zanmang_autopilot:'잔망루피 자동화',zanmang_decision:'잔망루피 검수 반영',
 editor_assets:'편집실 준비',scan_work_logos:'로고 찾기',
 tikitaka_generate:'영상 만들기',tikitaka_upload:'영상 올리기',tikitaka_apply_edit:'다시 렌더',tikitaka_publish:'유튜브 올리기',
 youtube_overlap:'겹치는 장면 찾기',build_compilation:'합본 만들기'};
export const jobKindKo=k=>JOB_KIND[k]||k||'?';
