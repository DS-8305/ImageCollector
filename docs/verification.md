# 구현 검증 기록

검증일: 2026-10-13 (Asia/Seoul)
기준: codex/google-image-collector, 원격 master 7be44cf에서 시작.
환경: Windows, Python 3.12.14, 설치된 Chrome, 프로젝트 .venv.
구현 커밋: 4e2e98a. 전달: [검토용 PR #2](https://github.com/DS-8305/ImageCollector/pull/2).

## 결과

| 검사 | 결과 |
| --- | --- |
| 전체 unittest discovery | 129개 통과, 실패·오류 없음 (25.808초) |
| Python compileall | image_collector, 기존 진입점, tests, scripts 통과 |
| 기존 네이버 API/CLI 호환 | 기존 20개 테스트 유지; 부족 수량을 partial로 구분하는 기대값 2개 갱신 |
| 실제 로컬 HTTP | JPEG/PNG/WebP, 원본/대체, 잘못된 본문, 크기·전송량, 재시도, 느린 전송 중 중단·시간 제한 |
| 실제 Chrome의 로컬 DOM | 결과 카드·상세 변경·확인·빈 결과·구조 변경·기간/권한 파라미터·취소 |
| 숨김 실제 Tk | 화면 생성, 입력 스냅샷, 스레드 이벤트, 선택 다운로드, PNG 갤러리 표시, 종료 |
| 저장 복구 | 기존 결과 보존, 이름 충돌·알 수 없는 파일 보호, pending 복구, 누락/손상 처리, 단일 실행 잠금 |
| 이어받기 | 옵션 불일치 거절, 완료 건너뛰기, 부분 작업 이어받기, 원래 선택 후보 유지 |
| 네이버 실검색 | 빨간 사과, 3장 목표: 3장 PNG 저장, success |
| 구글 실검색 | red apple, 1장 목표: needs_attention, 0장. 비정상 트래픽 확인 화면 감지 |
| 외부 API 실호출 | 수행하지 않음: 사용자 API 키 없음. 응답·페이지·쿼터·인증 오류 계약 테스트 통과 |

네이버 실제 결과는 .live-output/run_20261013T062043Z_3b86b0137154에서 검사했다.
구글 실제 확인 기록은 .live-output/run_20261013T062215Z_366e9319ae93에 보존했다.
.live-output은 Git에 포함하지 않는다.

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

## 검증 범위

구글 실검색의 현재 결과 카드·고해상도 URL·고급 필터 결과는 실제 서비스의 확인 화면 때문에 검증하지 못했다.
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
