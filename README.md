# URL-bot-paddle

상품 URL을 열어 전체 페이지를 캡쳐하고, PaddleOCR로 캡쳐 이미지에서
**상품명**과 **규격/사양**을 추출하는 자동화 도구.

캡쳐 로직(`capture/`)과 OCR/정보추출 로직(`ocr/`)은 서로 독립적으로 동작한다.

## 폴더 구조

```
capture/
  capturer.py     # Playwright로 URL을 열어 전체 페이지 스크린샷 저장
ocr/
  engine.py       # PaddleOCR 래퍼 (이미지 -> 텍스트/좌표)
  tiling.py       # 세로로 매우 긴 상세페이지 이미지를 타일로 나눠 OCR 후 좌표 병합
  table.py        # 좌표 기반 행/열(표) 재구성
  parser.py       # 표에서 상품명 / 규격·사양 파싱
config/
  urls.txt        # 캡쳐할 URL 목록 (한 줄에 하나)
output/
  captures/       # 캡쳐 이미지 + captures.jsonl 메타데이터
  results/        # 상품별 결과 json + summary.csv
main.py           # 캡쳐 -> OCR 파이프라인 실행
```

## 사용법

```powershell
# 1) config/urls.txt 에 캡쳐할 상품 URL을 한 줄에 하나씩 입력

# 2) 가상환경 활성화 후 실행
.\venv\Scripts\python.exe main.py
```

실행하면 `output/captures/`에 캡쳐 이미지가, `output/results/`에
URL별 결과(json)와 전체 요약(`summary.csv`)이 저장된다.

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

## 성능 관련 처리

- 캡쳐 이미지는 이미 똑바로 서 있는 스크린샷이라 문서방향 분류/언워핑/
  텍스트라인 방향보정을 꺼서(`ocr/engine.py`) 불필요한 모델 로딩·추론을
  없앴다.
- 상세페이지 이미지는 세로로 수만 px에 달할 수 있어(예: 2880×44042px) 한
  번에 OCR을 돌리면 처리 시간이 급격히 늘어난다. `ocr/tiling.py`가 3000px
  높이로 겹치게 잘라 타일 단위로 처리하고 좌표를 원본 기준으로 병합한다.

## 알려진 한계 (다음에 다듬을 부분)

- 상품명/규격·사양 추출(`ocr/parser.py`)은 아래 순서의 휴리스틱을 쓴다.
  1. "상품명/제품명/품명/모델명" 라벨이 붙은 2셀(라벨-값) 표 행을 우선 사용
  2. 못 찾으면 페이지 상단 30% 영역에서 글자가 가장 큰 텍스트를 상품명으로 추정
  3. 규격/사양은 2셀(라벨-값) 행 중 가격/상품명 라벨을 제외한 나머지를 사용
- `navimro.com` 실제 상세페이지로 테스트한 결과, OCR 텍스트 인식 자체는
  정확했지만(한글이 깨지지 않고 제대로 인식됨) 파싱 결과는 부정확했다:
  - 이 사이트는 규격/사양이 "라벨-값" 2칸 표가 아니라 **여러 열로 된
    그리드 표**(규격/날장/전장/원산지/모델명/상품코드/판매가 등)라서
    헤더 행이 통째로 값 하나로 묶여버린다.
  - 상품명 폴백(상단 큰 글씨) 휴리스틱이 로고/배너의 엉뚱한 텍스트를
    집어 틀렸다.
  - 또한 네비게이션/로그인/장바구니/푸터 정책 문구 같은, 우연히 2셀
    행처럼 보이는 UI 텍스트가 규격/사양 결과에 노이즈로 섞여 들어간다.
  - 다중 열 그리드 표 대응, 상품명 폴백 개선(상세페이지 본문 영역으로
    범위 한정 등), UI/네비게이션 텍스트 필터링을 다음 개선 대상으로
    남겨둔다.
