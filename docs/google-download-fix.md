# Google 후보 이동 후 저장되지 않는 문제

2026-10-13 사용자 실행 기록을 읽어 진단했다. 두 실행의 후보 30개와 55개가 모두
`Missing or invalid HTTP(S) image URL`로 건너뛰어졌고 `original_url`이 비어 있었다.
이 기록에서 크기 검사나 PNG 파일 저장 실패는 관찰되지 않았다.

기존 상세 추출기는 `img.sFlh5c.pT0Scc`와 `img.n3VNCb`만 읽었다.
공개된 [Google 검색 캡처 메타데이터](https://huggingface.co/datasets/horde-research/kaz-vision-50k/blob/f9a938505da72e2cf8fd5094a0eeb7f2e918e2b6/branding_symbolism/kazakh_company_logos/%D0%BB%D0%BE%D0%B3%D0%BE%D1%82%D0%B8%D0%BF%20%D0%9A%D0%B0%D0%B7%D0%B0%D1%85%D0%BC%D1%8B%D1%81/metadata.json)에는
다른 상세 이미지 속성 `sFlh5c FyHeAf iPVvYb`, `jsname=kn3ccd`가 있다.
이 형태의 지원 누락을 합성 fixture에서 재현했다. fixture의 URL·텍스트는 가상 데이터이며 실제 Google 페이지 전체를 복사하지 않았다.

사용자의 실제 상세 DOM은 확보하지 못했다. 별도 숨김·표시 Chrome의 Google 접속은
확인 화면에 막혔고 표시 모드는 수동 확인을 기다리다 제한 시간에 도달했다.
따라서 특정 DOM 차이가 사용자의 실패를 일으켰다는 판단은 기록과 재현 결과에 기반한 추론이며,
사용자 환경에서 수정 후 실제 저장 수를 다시 확인해야 한다.

## 수정

- `kn3ccd`, `iPVvYb`, `FyHeAf` 상세 이미지를 지원하고 기존 상세 형태도 유지한다.
- Google 캐시 썸네일 URL과 숨김·비활성 이미지를 원본 후보에서 제외한다.
- 카드 변경 뒤 상세 주소 변경을 기다리는 기존 보호를 유지한다.
- 건너뜀·중복·다운로드 실패 이유를 GUI/CLI 진행 로그로 즉시 전달한다.
- 원본 전용 모드와 블로그 크기 기준은 유지한다. 주소 누락을 작은 썸네일 저장으로 감추지 않는다.

## 검증

- 기존 코드에서 새로운 상세 형태의 원본 주소가 빈 값으로 나오는 실패를 확인했다.
- 실패 이유 로그도 기존 코드에서 누락되는 실패를 확인했다.
- 수정 후 실제 Chrome에서 상세 원본 2개의 주소와 출처 대응을 검증했다.
- Chrome 상세 추출 → 실제 로컬 HTTP 다운로드 → 1200×800 PNG 2장 및 메타데이터 저장을 통합 검증했다.
- 전체 unittest 132개 통과(26.851초), compileall 및 diff 검사를 통과했다.

이미 열려 있는 프로그램은 변경 전 모듈을 사용한다. 프로그램을 완전히 닫고 다시 실행해야 한다.
0장이 계속되면 진행 로그의 첫 실패 이유와 `run.json`의 이미지별 기록으로 다음 원인을 구분한다.
