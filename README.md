# Image Collector 2.0.1

네이버·구글에서 블로그·영상 제작용 이미지를 수집하는 Python 데스크톱 도구입니다.
단일 검색과 CSV/XLSX 일괄 검색, 두 엔진 통합 실행, 선택 다운로드, 이어받기, 결과 갤러리를 지원합니다.

## 설치와 실행

Python 3.10 이상과 Google Chrome이 필요합니다.

~~~powershell
git clone https://github.com/DS-8305/ImageCollector.git
cd ImageCollector
git switch codex/google-image-collector
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\naver_image_collector.py
~~~

위 설치 예제는 [검토용 PR #2](https://github.com/DS-8305/ImageCollector/pull/2)의 구현 브랜치를 사용합니다. PR이 master에 반영되면 브랜치 전환 없이 설치할 수 있습니다.

프로젝트 폴더에서 다음 실행 스크립트도 사용할 수 있습니다.

~~~powershell
.\run_collector.ps1
~~~

macOS/Linux에서는 가상 환경의 실행 경로가 .venv/bin/python입니다.
최초 브라우저 실행 시 ChromeDriver 다운로드를 위해 인터넷 연결이 필요합니다.

## GUI 사용

1. 검색엔진을 네이버, 구글, 네이버 + 구글 중에서 선택합니다.
2. 검색어를 입력하거나 keyword 열이 있는 CSV/XLSX를 선택합니다.
3. 이미지 수, 제작 용도 프리셋, 저장 방식을 선택합니다.
4. 수집 시작을 누릅니다. 진행 중에는 중단할 수 있습니다.
5. 결과 목록에서 이미지·출처·라이선스 링크를 확인하고 선택 이미지를 다른 폴더로 내보냅니다.

창 제목에서 버전 2.0.1을 확인할 수 있습니다. 코드 업데이트 후에는 수집기 메인 창을 완전히 닫고 다시 실행해야 합니다.
Chrome 창만 닫거나 수집 시작을 다시 눌러도 실행 중인 수집기가 이미 불러온 코드는 갱신되지 않습니다.

구글의 기본값은 고해상도 이미지 저장(original-only)과 블로그 프리셋입니다.
네이버는 기존 썸네일 저장과 가로·세로 최소 150px 기본값을 유지합니다.
통합 실행은 각 검색엔진에 목표 수를 적용합니다. 50장이라면 네이버 50장, 구글 50장이 목표입니다.

프리셋은 실제 이미지의 픽셀 크기를 검사합니다. 작은 이미지를 확대하거나 자동으로 자르지 않습니다.

| 프리셋 | 검사 기준 |
| --- | --- |
| 블로그 | 긴 변 1200px 이상, 가로·세로 각각 150px 이상 |
| 가로 영상 | 가로 1920px, 세로 1080px 이상 |
| 세로 영상 | 가로 1080px, 세로 1920px 이상 |
| 기존 썸네일 | 가로·세로 각각 150px 이상 |
| 직접 지정 | 입력한 최소 가로·세로·긴 변 |

크기 입력란이 비어 있으면 프리셋을 사용합니다. 명시적으로 수정한 값은 기존 프리셋의 해당 기준을 덮어씁니다.
네이버는 현재 썸네일만 지원하므로 고해상도 전용 저장 방식은 구글에서 선택합니다.

검색 미리보기는 단일 검색어·단일 엔진의 브라우저 방식에서 최대 20개 후보를 표시합니다.
후보를 체크한 뒤 선택한 후보 다운로드를 누르면 그 후보만 크기 기준에 맞춰 저장합니다.
선택 후보의 URL과 출처를 실행 기록에 보존하므로 이어받아도 새 검색의 다른 이미지로 바뀌지 않습니다.

## CLI

기존 실행 파일과 python -m image_collector를 모두 사용할 수 있습니다.

~~~powershell
# 기존 네이버 검색
.\.venv\Scripts\python.exe .\naver_image_collector.py --keyword "수면안대" --limit 50

# 구글 제작용 이미지
.\.venv\Scripts\python.exe -m image_collector --engine google --keyword "서울 한강" --profile blog --limit 20 --show-browser

# 구글 가로 영상용 이미지
.\.venv\Scripts\python.exe -m image_collector --engine google --keyword "mountain landscape" --profile video-landscape --limit 10

# 두 엔진 일괄 검색: 각 엔진 20장 목표
.\.venv\Scripts\python.exe -m image_collector --engine both --batch-file .\sample_keywords_300.csv --limit 20

# 작은 구글 썸네일 자료
.\.venv\Scripts\python.exe -m image_collector --engine google --keyword "apple" --download-mode thumbnail

# 고해상도 실패 시 썸네일 대체 허용 (크기 기준은 그대로 적용)
.\.venv\Scripts\python.exe -m image_collector --engine google --keyword "apple" --download-mode original-preferred

# 구글 검색 기간·사용 권한 필터
.\.venv\Scripts\python.exe -m image_collector --engine google --keyword "apple" --period month --usage-rights creative-commons

# 출력 폴더와 기존 크기 옵션
.\.venv\Scripts\python.exe -m image_collector --keyword "hand cream" --output-dir .\images --min-thumbnail-size 150

# 기존 실행 이어받기 / 실패 작업 재실행
.\.venv\Scripts\python.exe -m image_collector --resume .\downloaded_images\run_<실행식별자>
.\.venv\Scripts\python.exe -m image_collector --resume .\downloaded_images\run_<실행식별자> --retry-failed

# 저장 결과 갤러리
.\.venv\Scripts\python.exe -m image_collector --gallery .\downloaded_images\run_<실행식별자>
~~~

이어받기는 저장된 검색어와 옵션을 불러옵니다. 다른 옵션을 지정해 기존 실행과 달라지면 수정 전에 거절합니다.
완료 작업은 건너뛰고, 손상·누락 파일을 검증하며, 선택 다운로드는 원래 선택한 후보만 다시 시도합니다.
오래된 다운로드 URL이 만료된 경우 새로운 실행에서 다시 검색합니다.

전체 옵션은 --help로 확인합니다.
기본 제한은 키워드 300초, 스크롤 30회, 후보 max(100, 목표 수 × 5)입니다.
다운로드는 20MB, 디코딩 이미지는 40MP까지 검사하고 JPEG/PNG/WebP를 PNG로 저장합니다.
사용자 중단은 브라우저/네트워크/이미지 처리의 확인 지점에서 적용되므로 진행 중인 네이티브 호출이 끝날 때까지 짧은 대기가 생길 수 있습니다.

## 구글 확인 화면과 외부 API

표시 브라우저에서 동의 또는 확인 화면이 나타나면 로그에 안내하고 같은 세션에서 사용자가 처리하기를 기다립니다.
중단하거나 키워드 제한 시간이 끝나면 현재 결과와 확인 필요 상태를 남깁니다.
숨김 모드에서 확인 화면을 만나면 요청을 반복하지 않고 needs_attention으로 종료합니다.

구글 검색 화면의 구조와 접근 상태는 외부 서비스에 따라 달라집니다.
2026-10-13 별도의 자동 Google 접속에서는 비정상 트래픽 확인 화면을 관찰했습니다.
같은 날 사용자 표시 브라우저의 새 실행에서 고해상도 URL 이미지 3장을 PNG로 저장하고, 메타데이터·실제 크기·픽셀 해시를 검증했습니다.
구글 기간·사용 권한 필터의 실서비스 결과와 일괄 실검색은 아직 검증하지 않았습니다.

후보는 이동하지만 저장 수가 0장인 문제를 조사해 다른 상세 이미지 형태의 주소 추출과 실패 이유 로그를 보완했습니다.
이전 프로그램 창은 완전히 닫고 다시 실행해야 합니다. [수정·검증 기록](docs/google-download-fix.md)에 원인과 실제 검증 범위를 정리했습니다.

선택적으로 SerpApi를 사용할 수 있습니다. 구글을 선택하고 외부 검색 API 방식을 명시적으로 선택해야 합니다.
본인의 API 키와 이용 조건이 필요하며 기본 브라우저 방식에서 자동으로 전환하지 않습니다.

~~~powershell
$env:SERPAPI_API_KEY = '본인의 API 키'
.\.venv\Scripts\python.exe -m image_collector --engine google --backend api --keyword "apple" --limit 10
~~~

API 키는 실행 기록에 저장하거나 오류 메시지에 출력하지 않습니다.
API 연동은 응답 계약과 페이지·오류 처리 테스트를 통과했으며 실제 계정 호출은 키가 없어 수행하지 않았습니다.
Google Custom Search JSON API는 신규 고객에게 닫혀 있고 2027-01-01 종료 예정이므로 신규 연동에 사용하지 않습니다.
[Google 공식 안내](https://developers.google.com/custom-search/v1/overview)

검색에서 제공된 이미지 URL을 고해상도 후보로 사용하며 업로더의 최초 원본·최대 해상도를 보장하지 않습니다.
사용 권한 필터와 라이선스 링크는 출처 확인을 돕는 정보입니다.
[Google 이미지 사용 권한 안내](https://support.google.com/websearch/answer/29508?hl=ko)

## 입력 파일

CSV/XLSX에 keyword 헤더가 필요합니다. CSV는 첫 열, XLSX는 활성 시트의 keyword 열을 사용합니다.

~~~csv
keyword
수면안대
핸드크림
~~~

빈 값과 중복 키워드는 제외하고 순서를 유지합니다. CSV UTF-8/BOM·CP949를 지원합니다.
GUI는 실행할 때 파일을 다시 검증하므로 같은 경로의 파일 내용이 바뀌어도 새 데이터를 사용합니다.

## 출력과 이전 버전 호환

~~~text
downloaded_images/
  run_<UTC시각>_<식별자>/
    run.json
    run.lock
    batch_summary.csv
    kw_<검색어>_<해시>/
      naver/ 또는 google/
        image_01.png
        metadata.csv
        metadata.json
~~~

새 실행은 새 폴더에 저장합니다. 이전 버전의 downloaded_images/<검색어> 결과도 그대로 보존합니다.
run.lock은 OS 잠금용 파일이며 실행이 종료되거나 프로세스가 종료되면 잠금은 자동으로 해제됩니다. 남아 있는 파일 자체를 지울 필요는 없습니다.
네트워크 드라이브·여러 컴퓨터에서 OneDrive로 동시에 같은 run 폴더를 이어받는 사용은 지원 범위에 포함하지 않습니다.

메타데이터에는 실제 저장 크기·방식, 이미지 URL, 출처 페이지, 라이선스 링크, 고해상도 실패 시 대체 사유와 오류가 포함됩니다.
라이선스 미제공은 unknown, 제공된 링크는 provided로 표시합니다.
JSON은 복구 기준이며 CSV는 JSON에서 다시 만들 수 있습니다. CSV의 수식 형태 문자열은 Excel에서 수식으로 실행되지 않게 처리합니다.

작업 상태는 success, partial, empty, failed, needs_attention, cancelled로 구분합니다.
0장 다운로드를 성공으로 집계하지 않습니다.
CLI는 failed/needs_attention에 1, 잘못된 설정에 2, 사용자 중단에 130을 반환합니다.
partial/empty는 정상 종료하되 수량 부족과 상태를 표시합니다.

기존 명령과 주요 Python import는 compatibility adapter로 유지했습니다.
자동 수집은 clear_generated_images를 호출하지 않습니다. 기존 수동 정리 helper는 명시적 호출에서만 동작합니다.

## 테스트와 구조

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -v
.\.venv\Scripts\python.exe -m compileall -q image_collector naver_image_collector.py
~~~

테스트는 생성 이미지·로컬 HTTP 서버·로컬 DOM과 Chrome·숨김 Tk를 사용하며 실검색에 의존하지 않습니다.
ChromeDriver가 없으면 테스트 브라우저 초기 설치에 인터넷 연결이 필요합니다.

132개 테스트 통과, 네이버·구글 실제 이미지 각 3장 저장, 구글 확인 화면 감지 결과는 [검증 기록](docs/verification.md)에 정리했습니다.

- image_collector/models.py: 옵션·크기 프리셋·결과 계약
- image_collector/providers/: 네이버·구글·선택적 외부 API 수집기
- image_collector/downloader.py: 다운로드·품질 검사·중복 판별
- image_collector/storage.py: 실행 기록·복구·파일 보호
- image_collector/runner.py: 일괄 실행·중단·이어받기
- image_collector/gui.py / gallery.py / cli.py: 사용자 인터페이스
- naver_image_collector.py: 기존 실행 명령 호환 진입점

유사 이미지 판별과 워터마크 인식은 구현 범위에 포함하지 않았습니다. 현재 중복 제거는 동일 크기의 정확히 동일한 픽셀만 판별합니다.
