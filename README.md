# URL-bot-paddle

상품 URL을 열어 전체 페이지를 캡쳐하고, PaddleOCR로 텍스트를 추출한 뒤,
로컬 LLM(Qwen2.5, Ollama)으로 **상품명**과 **규격/사양**만 뽑아내는 자동화 도구.

캡쳐(`capture/`) · OCR(`ocr/`) · 정보추출(`llm/`) 로직은 서로 독립적으로 동작하며,
`main.py`가 셋을 순서대로 연결한다.

## 폴더 구조

```
capture/
  capturer.py     # Playwright(headless=False, 실제 Chrome)로 URL을 열어
                   # 전체 페이지 스크린샷 저장. 봇 탐지 회피/팝업 처리/
                   # SPA 렌더링 대기 로직 포함 (아래 "캡쳐" 항목 참고)
ocr/
  engine.py       # PaddleOCR 래퍼 (이미지 -> 텍스트/좌표/신뢰도)
  tiling.py       # 세로로 매우 긴 상세페이지 이미지를 타일로 나눠 OCR 후 좌표 병합
  table.py        # 좌표 기반 행/열(표) 재구성
  spacing.py      # kiwipiepy로 붙어있는 한글 OCR 텍스트에 띄어쓰기 복원
  parser.py       # (레거시) 좌표 기반 휴리스틱 파서. 현재 main.py는 안 쓰고
                   # llm/extractor.py로 대체됨
llm/
  extractor.py    # Ollama + Qwen2.5 로컬 LLM으로 상품명/규격 추출
config/
  urls.txt        # 캡쳐할 URL 목록 (한 줄에 하나, #으로 시작하면 주석)
output/
  captures/       # 캡쳐 이미지 + captures.jsonl 메타데이터
  results/        # URL별 OCR 텍스트(.txt), 결과 json, summary.csv
  chrome-profile/ # 로그인 세션이 필요한 사이트용 Chrome 프로필 (.gitignore 대상)
main.py             # 캡쳐 -> OCR -> LLM 추출 전체 파이프라인 실행
capture_only.py     # 캡쳐 단계만 실행 (URL별 소요시간 측정용)
ocr_only.py         # 저장된 캡쳐 이미지에 OCR만 실행
llm_only.py         # 저장된 OCR 텍스트(.txt)에 LLM 추출만 실행 (--model로 모델 비교)
```

## 사전 준비

1. **Python 가상환경** — `venv/`에 `requirements.txt` 설치
2. **Google Chrome 설치 필요** — Playwright가 번들 Chromium이 아니라 `channel="chrome"`로
   실제 설치된 Chrome을 사용한다 (봇 탐지 회피 목적, 아래 참고).
3. **Ollama 설치 + Qwen2.5 모델 pull**
   ```powershell
   ollama pull qwen2.5:3b
   ```
   Ollama 서비스가 로컬에서 떠 있어야 한다(`http://localhost:11434`). 보통 설치 후
   자동 실행된다.

## 사용법

```powershell
# 1) config/urls.txt 에 캡쳐할 상품 URL을 한 줄에 하나씩 입력

# 2) 가상환경 활성화 후 실행
.\venv\Scripts\python.exe main.py
```

실행하면 URL마다 `[캡쳐] -> [OCR] -> [LLM]` 순서로 진행되며,
`output/captures/`에 캡쳐 이미지가, `output/results/`에 URL별
OCR 원본 텍스트(`.txt`)와 결과(`.json`), 전체 요약(`summary.csv`)이 저장된다.

단계별로 따로 테스트하려면:
```powershell
.\venv\Scripts\python.exe capture_only.py                       # 캡쳐만, 소요시간 측정
.\venv\Scripts\python.exe ocr_only.py <이미지경로...>              # OCR만
.\venv\Scripts\python.exe llm_only.py --model qwen2.5:3b <텍스트경로...>  # LLM 추출만
```

## 캡쳐: 봇 탐지 회피 & SPA 렌더링 대기

일부 사이트(Akamai 등 CDN 레벨 WAF)가 자동화 브라우저를 감지해 "Access Denied"
페이지를 대신 돌려주는 문제가 있어, `capture/capturer.py`는 다음을 적용한다.

- **headless=False + `channel="chrome"`**: Playwright 번들 Chromium을 headless로
  쓰면 가장 흔히 걸리는 패턴이라, 실제 설치된 Chrome을 창을 띄운 채로 사용한다.
- **`navigator.webdriver` 스텔스 처리**: 자동화 브라우저가 표준으로 노출하는 이
  값을 페이지 로드 전에 숨긴다.
- **쿠키 동의 처리**: 동의 완료 쿠키 사전 주입 + CMP 스크립트 네트워크 차단 +
  동의 버튼 클릭(메인 프레임/iframe 전체 탐색) + 실패 시 CSS 강제 숨김(4중 폴백).
- **차단 페이지 감지**: 본문에서 "Access Denied", "captcha" 등 키워드가 보이면
  `ok=False`로 명확히 실패 처리하고 진단용 스크린샷을 남긴다 (스크린샷은 찍혔지만
  내용은 차단 페이지인 경우를 "성공"으로 착각하지 않도록).
- **URL 사이 랜덤 대기(3~7초)**: 일정한 간격의 연속 요청 패턴 자체가 탐지 신호가
  되는 것을 피한다.
- **로그인이 필요하거나 봇 탐지가 특히 공격적인 사이트**(`BOT_SENSITIVE_DOMAINS`,
  현재 쿠팡/네이버)는 로그인 세션이 남는 `output/chrome-profile/`을 재사용하는
  `launch_persistent_context`로 열고, 요청 전 8~15초 랜덤 대기를 추가로 둔다.

SPA(React 등) 사이트는 `networkidle`에 도달해도 실제 데이터가 화면에 그려지기
전일 수 있어(예: MISUMI가 빈 화면으로 캡쳐된 사례), `load`/`networkidle` 대기
후에도 문서 높이의 1/4·2/4·3/4·4/4 지점씩 내려가며 각 지점에서 2초씩 고정
대기하는 방식으로 지연 렌더링 콘텐츠가 그려질 시간을 확보한다. "더보기" 류
버튼은 자동으로 펼치되, 실제 페이지 이동 링크는 클릭하지 않고 클릭 후 URL이
바뀌면 즉시 되돌아가는 안전장치를 둔다 (상세페이지가 아니라 카테고리 목록으로
날아가버린 적이 있었음).

## 버전 고정 이유 (중요)

- `requirements.txt`는 `paddlepaddle==3.0.0` + `paddleocr==3.0.0`으로 **정확히
  고정**되어 있다. 임의로 올리면 아래 두 문제가 재발한다.
  1. **paddlepaddle을 3.0.0보다 올리면(예: 최신 3.3.1)** Windows CPU에서
     PP-OCR 감지/인식 추론 중 `NotImplementedError:
     ConvertPirAttribute2RuntimeAttribute ... onednn_instruction` 크래시가
     재현된다(예외가 아니라 프로세스가 그냥 죽는다). paddlepaddle 3.0.0
     에서는 발생하지 않는다.
  2. **paddleocr 3.0.0의 기본 모델 세대(PP-OCRv5)는 한국어 인식 모델이
     없다.** `lang="korean"`을 줘도 내부적으로 무시되고 중국어/영어 모델로
     인식해 한글이 전부 깨진다. 그래서 `ocr/engine.py`에서
     `ocr_version="PP-OCRv3"`로 강제 지정해 `korean_PP-OCRv3_mobile_rec`
     모델을 쓰도록 했다. (더 최신 paddleocr, 예: 3.7.x는 PP-OCRv5용
     한국어 모델이 추가돼 있지만, 그 버전은 paddlepaddle 최신판을 요구해서
     위 1번 크래시를 다시 만난다.)
  3. **`pykospacing`은 절대 설치하지 말 것.** TensorFlow를 딸려오면서 numpy를
     2.x로 올려버려 paddlex(numpy==1.24.4 고정)와 충돌해 PaddleOCR이 통째로
     깨진다. 띄어쓰기 교정은 TensorFlow 의존성이 없는 `kiwipiepy`를 쓴다.

## OCR 텍스트 품질 처리

- 캡쳐 이미지는 이미 똑바로 서 있는 스크린샷이라 문서방향 분류/언워핑/
  텍스트라인 방향보정을 꺼서(`ocr/engine.py`) 불필요한 모델 로딩·추론을
  없앴다.
- 상세페이지 이미지는 세로로 수만 px에 달할 수 있어(예: 2880×44042px) 한
  번에 OCR을 돌리면 처리 시간이 급격히 늘어난다. `ocr/tiling.py`가 3000px
  높이로 겹치게 잘라 타일 단위로 처리하고 좌표를 원본 기준으로 병합한다.
- 신뢰도(confidence) 0.5 미만인 텍스트 박스는 `filter_by_confidence`로
  걸러낸다. 오인식된 텍스트일수록 신뢰도가 낮게 나오는 경향이 뚜렷해서,
  간단한 임계값만으로도 눈에 띄는 노이즈가 줄어든다.
- 한글 인식 결과는 띄어쓰기가 거의 다 사라진 채로 나오는 경우가 많다
  (예: "스웨즈락튜브피팅용"). `ocr/spacing.py`(kiwipiepy)로 복원해서
  사람이 읽기도, LLM이 문맥을 파악하기도 쉽게 만든다.

## LLM 추출 (`llm/extractor.py`)

`ocr/parser.py`의 좌표 기반 휴리스틱(라벨-값 표 우선, 못 찾으면 상단 큰 글씨를
상품명으로 추정)은 사이트마다 다른 표 구조(다중 열 그리드 등)와 네비게이션/
배너 텍스트 혼입에 취약했다. 지금은 OCR 원본 텍스트를 로컬 LLM(Ollama +
Qwen2.5)에 넘겨 "로그인/장바구니/광고/배송안내 등은 무시하고 실제 상품명과
규격만 뽑아라"라고 지시하는 방식으로 대체했다.

- **모델**: `qwen2.5:3b` (`llm/extractor.py`의 `MODEL` 상수). GPU가 없는
  이 환경(총 RAM 7.7GB) 기준 7b는 메모리 부족으로 크래시, 1.5b는 실제 값을
  못 뽑고 빈 템플릿만 반환하는 경우가 많아 3b로 정착했다.
- **알려진 문제**:
  - **느림**: CPU 추론이라 텍스트가 길수록 급격히 느려진다 (예: 6,400자
    입력에 3b 기준 약 5~6분).
  - **환각(hallucination)**: 원본 텍스트에 없는 값을 지어내는 경우가
    있었다 (예: 규격표에 없는 "재질" 항목을 만들어냄). 3b도 완벽히
    신뢰할 수 있는 수준은 아니라서, 프롬프트 개선이나 더 큰 모델(메모리
    여유가 되면) 검토가 필요하다.
  - `llm_only.py --model <이름>`으로 모델을 바꿔가며 같은 OCR 텍스트에
    대한 결과를 비교해볼 수 있다.

## 알려진 한계 / 다음에 다듬을 부분

- **메모리 제약**: 이 환경은 총 RAM 7.7GB로 넉넉하지 않다. `navimro.com`처럼
  세로로 극단적으로 긴 캡쳐 이미지(2880×44042px)는 OCR 처리 중 메모리 부족으로
  실패하는 경우가 있었다 (Chrome 등 다른 프로그램 종료로 여유 확보 시 해결됨).
  LLM도 7b 모델은 로딩 자체가 이 메모리로는 불가능하다.
- **LLM 정확도**: 위 "알려진 문제" 참고. 특히 긴 텍스트에서 속도/정확도 모두
  아쉽다. 노이즈가 많은 텍스트를 LLM에 넘기기 전에 더 걸러내거나(예: 캡쳐 단계
  에서 상세정보 영역만 스코핑), 마크다운 표 형식으로 재구성해서 LLM이 구조를
  더 명확히 인식하게 하는 방향을 검토 중이다.
- **`ocr/parser.py`는 더 이상 파이프라인에서 쓰이지 않는다.** 코드는 남아있지만
  `main.py`는 `llm/extractor.py`만 사용한다. 완전히 정리할지, 폴백용으로
  유지할지 결정 필요.
