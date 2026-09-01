# URL Bot — 상품 URL 자동 크롤링 · OCR · 정보 추출 도구

이커머스·산업용 부품 사이트의 상품 URL을 입력하면 **텍스트(DOM/표) + 이미지를 함께 수집**하고, 이미지에서 PaddleOCR로 규격 정보를 추출한 뒤, Ollama/Qwen LLM으로 상품명·모델번호·사이즈·사양을 자동으로 추출합니다.

---

## 목차

1. [파이프라인 개요](#1-파이프라인-개요)
2. [폴더 구조](#2-폴더-구조)
3. [설치](#3-설치)
4. [사용 방법](#4-사용-방법)
5. [각 단계 상세](#5-각-단계-상세)
6. [주요 설정](#6-주요-설정)
7. [지원 사이트](#7-지원-사이트)
8. [성능 측정](#8-성능-측정)

---

## 1. 파이프라인 개요

```
crawl/urls.txt 에 URL 입력
        │
        ▼
[ 1단계 ] crawl/crawler.py   — Playwright로 상품 페이지 크롤링
        │  · DOM 텍스트 (dom.txt)
        │  · 표 구조 (tables.json / tables.txt)
        │  · 상품 본문 DOM 텍스트 (product_dom.txt)
        │  · 상품 본문 스크린샷 (product.png)
        │  · OCR 대상 이미지/Canvas (assets/*.png)
        │
        ▼   crawl/output/capture_YYYYMMDD_HHMMSS/
        │
        ▼
[ 2단계 ] ocr/paddle_ocr.py  — PaddleOCR로 이미지 텍스트 추출
        │  · assets/*.png, product.png 대상
        │  · 타일 분할 → 다열 레이아웃 분리 → 좌표 기반 행 재조합 → IOU 중복 제거
        │  · 상품별 ocr_asset.txt / product.md 생성
        │
        ▼   ocr/output/capture_YYYYMMDD_HHMMSS/
        │
        ▼
[ 3단계 ] extract/extractor.py  — 상품 정보 추출
           · Qwen(Ollama) LLM으로 상품명·모델번호·사이즈·사양 추출
           · Ollama 미설치 또는 실패 시 규칙 기반(정규식/키워드)으로 자동 폴백
           · products_summary.json / products_summary.txt 생성

           extract/output/capture_YYYYMMDD_HHMMSS/
```

`main.py`를 실행하면 3단계가 순서대로 자동 실행됩니다.  
각 단계의 스크립트를 직접 실행하면 해당 단계만 독립적으로 수행할 수 있습니다.

---

## 2. 폴더 구조

```
URL-bot/
├── main.py                      # 전체 파이프라인 실행 진입점
│
├── crawl/
│   ├── crawler.py               # Playwright 크롤링 (1단계)
│   ├── config.py                # 크롤링 설정 (브라우저, 사이트 선택자 등)
│   ├── urls.txt                 # 캡처 대상 URL 목록
│   ├── chrome_profiles/         # Playwright 영구 Chrome 프로필 (세션 재사용)
│   └── output/
│       └── capture_YYYYMMDD_HHMMSS/
│           └── {index}_{domain}/
│               ├── dom.txt              # 전체 페이지 DOM 텍스트
│               ├── tables.json          # 표 구조 (JSON)
│               ├── tables.txt           # 표 구조 (탭 구분 텍스트)
│               ├── product_dom.txt      # 상품 본문 DOM 텍스트
│               ├── product.png          # 상품 본문 스크린샷
│               ├── assets/              # OCR 대상 이미지·Canvas
│               │   └── asset_001_img.png
│               ├── assets.json          # 에셋 메타데이터
│               └── metadata.json        # URL, 상태, 소요시간 등
│
├── ocr/
│   ├── paddle_ocr.py            # PaddleOCR 추출 (2단계)
│   ├── config.py                # OCR 설정 (타일 크기, 임계값 등)
│   ├── cache/                   # 이미지별 OCR 캐시 (최종 출력물 아님, git 제외)
│   └── output/
│       └── capture_YYYYMMDD_HHMMSS/
│           └── {index}_{domain}/
│               ├── ocr_asset.txt        # 상품별 OCR 텍스트 통합본
│               └── product.md           # crawl/의 context.md + OCR 텍스트 통합 마크다운
│
├── extract/
│   ├── extractor.py             # 상품 정보 추출 — 파이프라인·규칙 기반·LLM 통합 (3단계)
│   ├── config.py                # 추출 설정 (키워드, LLM 파라미터 등)
│   └── output/
│       └── capture_YYYYMMDD_HHMMSS/
│           ├── products_summary.json    # 추출 결과 (JSON)
│           └── products_summary.txt     # 추출 결과 (사람이 읽기 좋은 형식)
│
├── server.py                    # 검증처리자용 웹 GUI 서버 (FastAPI) — 크롤링/OCR 함수를 그대로 호출
├── web/                         # 프론트엔드 (바닐라 HTML/CSS/JS)
│   ├── index.html
│   ├── app.js                   # URL 입력, OCR 토글, SSE 실시간 로그, 결과 뷰어
│   └── style.css
│
├── .env                         # API 키 등 환경변수 (git 제외)
├── requirements.txt
└── .gitignore
```

---

## 3. 설치

```bash
pip install -r requirements.txt
playwright install chrome
```

### Ollama + Qwen 설치 (LLM 추출용)

[Ollama](https://ollama.com) 설치 후 모델을 받습니다:

```bash
ollama pull qwen2.5:3b
```

Ollama가 없거나 꺼져 있으면 LLM 추출을 건너뛰고 규칙 기반 추출로 자동 폴백합니다.

---

## 4. 사용 방법

### 1. URL 설정

`crawl/urls.txt`에 캡처할 URL을 한 줄에 하나씩 입력합니다:

```
https://kr.misumi-ec.com/vona2/detail/110302634310/
https://www.festo.com/kr/ko/a/8001234/
# 주석 처리된 줄은 무시됩니다
```

### 2. 전체 파이프라인 실행

```bash
python main.py
```

크롤링 → OCR → 상품정보 추출이 순서대로 자동 실행됩니다.

### 3. 단계별 개별 실행

```bash
# 크롤링만
python crawl/crawler.py

# OCR만 (crawl/output의 최신 폴더를 자동으로 사용)
python ocr/paddle_ocr.py

# 정보 추출만
python extract/extractor.py
```

### 4. GUI로 실행

검증처리자가 URL을 직접 입력해 진행 상황을 실시간 로그로 확인하며 실행할 수 있는 웹 GUI(FastAPI + 바닐라 HTML/CSS/JS)입니다.

```bash
python server.py
```

`http://localhost:8000` 접속.

- URL을 여러 줄 입력하면 순서대로 일괄 크롤링합니다(Ctrl+Enter로 실행).
- **이미지 OCR 포함** 토글로 OCR 수행 여부를 선택합니다.
- 실행하면 `/api/run`이 백그라운드 스레드로 크롤링(+OCR)을 시작하고, `/api/stream/{job_id}`가 SSE로 진행 로그를 실시간 스트리밍합니다.
- 완료 후 **결과 보기**로 상품별 크롤링 결과(`context.md`)를 확인할 수 있습니다.
- **데이터 추출**(GPT-4o-mini) 단계는 API 키 연동 전까지는 준비 중 상태입니다(`/api/extract`가 스텁으로 응답).
- `crawl/`·`ocr/`의 기존 함수를 그대로 호출만 합니다.
- 크롤링 중에는 `crawl/config.py`의 `HEADLESS` 설정에 따라 실제 Chrome 창이 열릴 수 있습니다.

---

## 5. 각 단계 상세

### 1단계: 크롤링 (crawl/crawler.py)

Playwright로 실제 Chrome 브라우저를 제어해 상품 페이지를 수집합니다.

- **세션 재사용**: `crawl/chrome_profiles/`에 Chrome 영구 프로필을 저장해 로그인·쿠키 상태를 다음 실행에도 유지합니다.
- **봇 차단 대응**: Cloudflare 등 차단 화면 감지 시 브라우저를 화면에 띄우고 수동 확인 완료까지 대기합니다.
- **쿠키 동의 자동 처리**: "동의", "수락" 버튼을 자동으로 클릭합니다.
- **더보기 자동 펼치기**: "상세정보 더보기", "view more" 등의 버튼을 자동으로 클릭합니다.
- **lazy-load 대응**: 스크롤로 지연 로딩 콘텐츠를 완전히 불러온 후 수집합니다.
- **이중 수집**: DOM 텍스트·표는 직접 파싱하고, 텍스트를 담은 이미지·Canvas는 별도 캡처합니다.
- **표 병합 처리**: 열 고정으로 분리 렌더링된 표(MISUMI 등)를 하나로 다시 합칩니다.

설정 파일 `crawl/config.py`에서 사이트별 선택자, 봇 차단 대기 시간, OCR 이미지 최소 크기 등을 조정할 수 있습니다.

### 2단계: OCR (ocr/paddle_ocr.py)

PaddleOCR 3.x (PaddleX 백엔드, PaddlePaddle 3.3.1)로 이미지에서 텍스트를 추출합니다.

**인식 모델**: 검출 `PP-OCRv5_mobile_det` + 인식 `korean_PP-OCRv5_mobile_rec`(한국어 특화, 세대만 v5)로 고정합니다. 이 조합으로 초기화가 실패하면(모델 다운로드 불가 등) `lang="korean"` 기반 자동 선택(`PP-OCRv3`)으로 폴백합니다.

> **왜 예전엔 PaddlePaddle 3.0.0에 묶여 있었는가?**  
> `paddleocr>=3.7.0`이 받는 모델은 최신 포맷(PIR)인데 `paddlepaddle==3.0.0`의 추론 엔진이 이 포맷을 못 읽어 오류가 났었습니다. 원인은 "최신 버전 자체가 안 되는 것"이 아니라 "구버전 PaddlePaddle + 신버전 paddleocr"라는 어긋난 조합이었고, PaddlePaddle도 함께 올리면(3.3.1) 정상 동작합니다. 이 조합으로 예전 `korean_PP-OCRv3_mobile_rec`보다 오독이 크게 줄고(예: "2.4GHZ"→"24GHZz" 같은 오독 해소) 신뢰도도 0.94~1.00으로 올라, 언어별로 모델을 나눠 쓸 필요 없이 이 모델 하나로 한국어 문장과 영문·숫자·코드(모델번호, 규격표 등)를 모두 잘 인식합니다. 이 조합은 `numpy>=2.0.0`도 요구해 `pandas`를 함께 올려야 합니다 (`requirements.txt` 주석 참고).

**처리 방식**

- **대상**: `assets/*.png`(이미지·Canvas) + `product.png`(상품 본문 스크린샷)
- **타일 분할**: 긴 이미지를 일정 높이로 잘라 처리하고 y좌표 오프셋으로 보정합니다.
- **IOU 중복 제거**: 타일 경계에서 중복 인식된 단어를 신뢰도 기준으로 제거합니다.
- **다열(multi-column) 레이아웃 분리**: 제품 카드 + 표처럼 가로로 나란히 배치된 서로 다른 열이 같은 y대에 걸쳐 있으면, 행 그룹핑 전에 이미지 전체 폭 대비 충분히 넓고 상하로 겹치는 빈 세로 구간을 열 경계로 보고 좌/우(3열 이상이면 재귀적으로)로 먼저 나눈 뒤 열마다 따로 행을 재조합합니다.
- **좌표 기반 행 재조합**: 단어별 바운딩 박스 y좌표로 행을 그룹핑하고, x좌표 간격이 넓으면 탭으로 구분합니다.
- **띄어쓰기 복원**: 인식 결과를 `kiwipiepy`(형태소 분석기)로 띄어쓰기를 복원합니다.
- **캐시**: 이미지별 OCR 결과를 `ocr/cache/`(git 제외)에 보관해 재실행 시 건너뜁니다(`config.py`에서 끌 수 있음).
- **프로세스 격리 + 자동 재시도**: 캡처 실행 전체의 미처리 이미지를 모아 프로세스 1개(엔진 1회 로딩)로 처리해 상품마다 엔진을 새로 띄우던 것보다 빠릅니다. 프로세스가 죽거나 타임아웃 나도 아직 캐시가 없는 이미지만 새 프로세스로 재시도합니다.
- **통합 마크다운(`product.md`) 생성**: crawl/이 만든 `context.md`(DOM 표·텍스트) 아래에 이미지별 OCR 결과를 이어붙여, LLM에 바로 넘길 수 있는 상품별 통합 문서를 `ocr/output/`에 생성합니다. `extract/extractor.py`가 이 파일을 우선으로 읽습니다.

### 3단계: 정보 추출 (extract/extractor.py)

크롤링·OCR 결과를 종합해 상품별 핵심 정보를 추출합니다.

**추출 항목**: 상품명, 모델번호, 사이즈, 사양

**추출 방식 (우선순위)**:

1. **Qwen LLM (Ollama)**: DOM·표·OCR 텍스트를 프롬프트로 넘겨 JSON으로 추출. `extract/config.py`에서 모델과 파라미터 조정 가능.
2. **규칙 기반 폴백**: Ollama 미설치·오류·빈 응답 시 자동으로 전환. 정규식 패턴과 키워드 매칭으로 라벨:값 쌍을 찾아 분류.

---

## 6. 주요 설정

각 단계별 `config.py`에서 동작을 조정합니다.

| 파일 | 주요 설정 |
|---|---|
| `crawl/config.py` | `HEADLESS`, `DEFAULT_VIEWPORT`, `EXCLUDE_DOMAINS`, 사이트별 선택자, OCR 이미지 최소 크기 |
| `ocr/config.py` | `OCR_TILE_HEIGHT`, `OCR_CONFIDENCE_THRESHOLD`, `OCR_CACHE_ENABLED`, `OCR_TEXT_DETECTION_MODEL_NAME`/`OCR_TEXT_RECOGNITION_MODEL_NAME`(고정 모델), `OCR_FALLBACK_OCR_VERSION`(초기화 실패 시 폴백), `OCR_COLUMN_GAP_MIN_RATIO`(다열 레이아웃 분리 기준) |
| `extract/config.py` | `EXTRACTION_ENGINE` (`"qwen"` 또는 `"rules"`), `OLLAMA_MODEL`, `SPEC_LABEL_KEYWORDS` |

---

## 7. 지원 사이트

| 사이트 | 크롤링 |
|---|:---:|
| Misumi (kr.misumi-ec.com) | ✅ |
| Festo (www.festo.com) | ✅ |
| Swagelok (products.swagelok.com) | ✅ |
| Siemens Industry Mall | ✅ |
| Navimro (www.navimro.com) | ✅ |
| Danawa (prod.danawa.com) | ✅ |
| 네이버, 쿠팡, Gmarket, Auction | 🚫 자동 제외 (`EXCLUDE_DOMAINS`) |

---

## 8. 성능 측정

> 환경: Windows 11, Chrome (non-headless), Intel i5-1135G7 / RAM 16GB / 내장그래픽(CPU 추론)  
> Extract 모델: qwen3:4b (Ollama, think:false)

| 사이트 | Crawl | OCR | Extract | 총합 |
|---|---:|---:|---:|---:|
| Misumi | 18.6초 | 37.1초 | 78.8초 | 134.5초 |
| Festo | 11.2초 | 25.1초 | 90.4초 | 126.7초 |
| Swagelok | 9.6초 | 167.7초 | 303.7초 | 481.0초 |
| Siemens Industry Mall | 9.5초 | 93.8초 | 52.6초 | 155.9초 |
| Navimro (1) | 36.9초 | 37.3초 | 101.3초 | 175.5초 |
| Danawa | 87.6초 | 177.2초 | 322.0초 | 586.8초 |
| Navimro (2) | 40.9초 | 115.8초 | 280.8초 | 437.5초 |
| **단계 합계** | **218.7초** | **664.6초** | **1229.6초** | **2112.9초** |
