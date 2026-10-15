# 구현 검증 기록

## 2.1.1 크기 조건 안내 — 2026-10-15

구글에서 최소 가로·세로를 각각 100으로 바꾸고 긴 변을 빈칸으로 두면, 블로그 프리셋의 긴 변 1200px 조건이 남아 1000×1000 이미지가 거절되는 것을 재현했다.
부분 크기 입력의 프리셋 상속 규칙을 유지하며 설정 화면·수집 시작 로그·크기 거절 메시지에 실제 적용 조건을 표시했다. 긴 변 0이 제한 해제라는 안내를 추가했다.

실제 로컬 HTTP의 1000×1000 원본이 긴 변 1200 조건에서는 구체적인 사유와 함께 거절되고, 긴 변 0에서는 PNG로 정상 처리되는 회귀 테스트를 추가했다.
실제 Tk에서 가로·세로 수정, 긴 변 0/빈칸, 직접 지정 프리셋, 두 엔진의 다른 기본값, 잘못된 입력에 따라 안내가 갱신되는 것을 확인했다.
전체 144개 unittest가 통과했다(50.448초). compileall·버전 2.1.1·diff 공백 검사를 통과했고, 독립 코드 리뷰에서 수정이 필요한 문제는 발견되지 않았다.

## 2.1.0 세션 유지 개선 — 2026-10-15

Windows / Python 3.12.14 / 실제 Chrome·Tk·로컬 HTTP에서 검증했다.
기존 133개에서 142개로 늘어난 전체 unittest가 통과했고, compileall과 실행 스크립트의 버전 2.1.0 출력을 확인했다.
독립 코드 리뷰에서 수정이 필요한 문제는 발견되지 않았다.

- GUI에서 검색어를 바꾸어 두 번 실제 수집하고, PNG 저장과 갤러리 표시까지 같은 Chrome 세션·소유 스레드를 사용하는 것을 확인했다.
- Chrome 종료 후 새 BrowserSession에서 영속 쿠키를 읽었다. 창을 직접 닫은 뒤 재시작, 동일 프로필 중복 실행 거절과 잠금 해제를 확인했다.
- ChromeDriver 연결 소실 후 재생성, 브라우저 초기 설정 실패 시 Chrome 정리와 프로필 잠금 해제를 확인했다.
- 키워드 제한 1초보다 긴 확인 화면을 처리하고, 후속 카드 표시를 기다린 다음 실제 HTTP 원본을 다운로드하여 PNG로 저장했다.
- 수동 확인의 별도 시간 제한·취소, 원본 누락 3회 연속 시 엔진 중단과 JSON/PNG 진단 저장, 정상 추출 시 연속 실패 횟수 초기화를 확인했다.

테스트는 로컬 제어 화면을 사용했다. 이 버전으로 Google 실서비스의 캡차 발생 빈도가 감소했는지는 아직 측정하지 않았다.
Google의 캡차를 자동으로 풀거나 기존 블로그 Chrome에 연결하지 않는다.

## 2.0.1 검증 기록

검증일: 2026-10-13 (Asia/Seoul)
기준: codex/google-image-collector, 원격 master 7be44cf에서 시작.
환경: Windows, Python 3.12.14, 설치된 Chrome, 프로젝트 .venv. 최종 표시 버전 2.0.1.
구현 커밋: 4e2e98a. 전달: [검토용 PR #2](https://github.com/DS-8305/ImageCollector/pull/2).

## 결과

| 검사 | 결과 |
| --- | --- |
| 전체 unittest discovery | 133개 통과, 실패·오류 없음 (27.327초, 후속 수정·버전 표시·시간 예산 회귀 포함) |
| Python compileall | image_collector, 기존 진입점, tests, scripts 통과 |
| 기존 네이버 API/CLI 호환 | 기존 20개 테스트 유지; 부족 수량을 partial로 구분하는 기대값 2개 갱신 |
| 실제 로컬 HTTP | JPEG/PNG/WebP, 원본/대체, 잘못된 본문, 크기·전송량, 재시도, 느린 전송 중 중단·시간 제한 |
| 실제 Chrome의 로컬 DOM | 결과 카드·상세 변경·확인·빈 결과·구조 변경·기간/권한 파라미터·취소 |
| Google 상세 추출·저장 통합 | 다른 상세 이미지 형태 → 실제 로컬 HTTP 원본 다운로드 → 1200×800 PNG 2장과 메타데이터 저장 |
| 숨김 실제 Tk | 화면 생성, 입력 스냅샷, 스레드 이벤트, 선택 다운로드, PNG 갤러리 표시, 종료 |
| 저장 복구 | 기존 결과 보존, 이름 충돌·알 수 없는 파일 보호, pending 복구, 누락/손상 처리, 단일 실행 잠금 |
| 이어받기 | 옵션 불일치 거절, 완료 건너뛰기, 부분 작업 이어받기, 원래 선택 후보 유지 |
| 네이버 실검색 | 빨간 사과, 3장 목표: 3장 PNG 저장, success |
| 구글 별도 자동 실접속 | red apple, 1장 목표: needs_attention, 0장. 비정상 트래픽 확인 화면 감지 |
| 구글 사용자 표시 브라우저 실검색 | 3장 목표: 3장 PNG 저장, success. 2328×3160 / 1200×940 / 1200×1842, original URL 방식·픽셀 해시·메타데이터 검증 |
| 수정본 실행 식별 | CLI 2.0.1 및 실제 Tk 창 제목의 2.0.1 표시 확인 |
| 외부 API 실호출 | 수행하지 않음: 사용자 API 키 없음. 응답·페이지·쿼터·인증 오류 계약 테스트 통과 |

네이버 실제 결과는 .live-output/run_20261013T062043Z_3b86b0137154에서 검사했다.
구글 실제 확인 기록은 .live-output/run_20261013T062215Z_366e9319ae93에 보존했다.
구글 실제 저장 결과는 .live-output/user-diagnostic-runs/run_20261013T074756Z_d57cbd4aae03에 보존했다.
.live-output은 Git에 포함하지 않는다.
후속 Google 주소 추출 실패와 수정 검증은 [별도 기록](google-download-fix.md)에 정리했다.

## 독립 검토와 수정

독립 코드 검토는 docs/code-review.md에 기록했다. 처음 검토자는 모델 사용량 제한으로 종료되어 다른 검토자가 검토를 마무리했다.
검토에서 확인한 아래 여섯 가지 문제에 대해 재현 테스트의 실패를 확인하고 구현을 수정했다.

| 문제 | 수정 | 재현·검증 테스트 |
| --- | --- | --- |
| 선택 후보가 이어받기에 사라짐 | 후보 URL·출처를 run 기록에 저장하고 같은 후보만 재사용 | test_selected_candidates_persist_and_resume_never_searches_unselected |
| 미등록·손상 파일 덮어쓰기 | 디스크의 이름도 예약하고 최종 파일을 덮어쓰지 않는 방식으로 확정 | test_new_image_names_preserve_unknown_and_corrupted_prior_files |
| 오래된 잠금 인수 경쟁 | 삭제식 PID 잠금 대신 OS 파일 잠금; 종료·크래시 시 OS가 해제 | test_stale_lock_race_never_grants_two_owners |
| 표시 확인 창이 즉시 닫힘 | 표시 모드에서 중단·시간 제한을 확인하며 같은 브라우저에서 사용자 처리를 기다림 | test_visible_verification_can_be_resolved_in_same_session |
| 느린 전송이 중단·시간 제한을 지연 | urllib3 read1로 도착한 데이터를 읽으며 예산 확인 | test_slow_drip_body_honors_cancel_before_large_chunk_fills / test_slow_drip_body_honors_total_deadline |
| 긴 Retry-After를 5초로 단축 | 실제 서버 대기 지시를 유지하고 남은 시간에 못 맞추면 요청 반복 중지 | test_retry_after_longer_than_keyword_budget_does_not_resubmit |

Windows/OneDrive의 일시적인 파일 교체 거절도 실제 전체 테스트에서 관찰했다.
원자 JSON 교체에 한정된 재시도와 재현 테스트를 추가해 이전 파일을 보존한다.

후속 CI의 Python 3.10에서 `test_deadline_during_stream_is_honored_without_fallback`이 실패했다.
서버 대기·재시도가 남은 시간 안에 들어가지 못해 거절됐지만, 실제 제한 시각 전이면 original-preferred가 썸네일 대체 요청을 시작할 수 있었다.
`test_retry_outside_budget_never_triggers_preferred_thumbnail_fallback`으로 이 경로를 시간 경합 없이 재현했다.
시간 예산 거절을 별도 예외로 구분해 썸네일 대체를 금지했고, 두 회귀 테스트와 전체 133개 테스트가 통과했다.

## 검증 범위

구글 사용자 표시 브라우저 실검색의 결과 카드·고해상도 URL 다운로드·PNG 저장은 검증했다.
기간·사용 권한 필터의 실서비스 결과와 구글 일괄 실검색은 검증하지 못했다.
별도 자동 접속의 확인 화면 제한도 함께 기록했다. 한 번의 성공이 모든 접속 환경의 성공을 보장하는 것은 아니다.
표시 브라우저의 사용자 확인 후 계속 처리하는 수명은 자체 로컬 DOM으로 검증했다.
외부 검색 API를 실제 계정에서 호출하거나 유료 검색을 수행하지 않았다.
사용 권한·최초 원본·최대 해상도는 수집기가 보장하는 사실로 표시하지 않는다.
광범위한 악성 manifest 퍼징, 전원 장애의 모든 파일 시스템 시나리오, 여러 컴퓨터의 동시 OneDrive 실행은 검증 범위에 포함하지 않는다.

## 재실행

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m compileall -q image_collector naver_image_collector.py tests scripts
.\run_collector.ps1 --version
~~~

테스트는 실검색을 하지 않는다. ChromeDriver가 없으면 초기 다운로드가 필요하다.
