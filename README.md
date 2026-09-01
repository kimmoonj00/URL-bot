# URL Bot — 상품 URL 자동 크롤링 · OCR · 정보 추출 도구

이커머스·산업용 부품 사이트의 상품 URL을 입력하면 **텍스트(DOM/표) + 이미지를 함께 수집**하고, 이미지에서 PaddleOCR로 규격 정보를 추출한 뒤, OpenAI GPT-4o-mini로 상품명·모델번호·사이즈·사양을 자동으로 추출합니다.

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
9. [GUI 파일 자동 정리 (TTL)](#9-gui-파일-자동-정리-ttl)

---

## 1. 파이프라인 개요

```
crawl/urls.txt 에 URL 입력
        │
        ▼
[ 1단계 ] crawl/crawler.py   — Playwright로 상품 페이지 크롤링
        │  · DOM 텍스트 + 표 구조 통합 마크다운 (context.md)
        │  · OCR 대상 이미지/Canvas (assets/*.png, assets.json)
        │  · 메타데이터 (metadata.json)
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
           · OpenAI GPT-4o-mini로 상품명·모델번호·사이즈·사양 추출
           · API 오류·빈 응답 시 규칙 기반(정규식/키워드)으로 자동 폴백
           · products_summary.json / products_summary.txt 생성

           extract/output/capture_YYYYMMDD_HHMMSS/
```

각 단계의 스크립트를 직접 실행하면 해당 단계만 독립적으로 수행할 수 있습니다.  
웹 GUI(`server.py`)를 사용하면 브라우저에서 URL을 입력하고 결과를 바로 확인할 수 있습니다.

---

## 2. 폴더 구조

```
URL-bot/
├── server.py                    # 웹 GUI 서버 (FastAPI)
│
├── web/
│   ├── index.html               # 웹 프론트엔드
│   ├── app.js                   # 프론트엔드 JS
│   └── style.css                # 스타일
│
├── crawl/
│   ├── crawler.py               # Playwright 크롤링 (1단계)
│   ├── config.py                # 크롤링 설정 (브라우저, 사이트 선택자 등)
│   ├── urls.txt                 # 캡처 대상 URL 목록 (CLI 단계별 실행 시 사용)
│   ├── chrome_profiles/         # Playwright 영구 Chrome 프로필 (세션 재사용)
│   └── output/
│       ├── capture_YYYYMMDD_HHMMSS/   # CLI 단계별 실행 결과 (자동 삭제 안 됨)
│       └── gui_YYYYMMDD_HHMMSS/       # GUI 실행 결과 (1시간 TTL 후 자동 삭제)
│           └── {index}_{domain}/
│               ├── context.md          # DOM 텍스트 + 표 구조 통합 마크다운
│               ├── assets/             # OCR 대상 이미지·Canvas
│               │   └── asset_001_img.png
│               ├── assets.json         # 에셋 메타데이터
│               └── metadata.json       # URL, 상태, 소요시간 등
│
├── ocr/
│   ├── paddle_ocr.py            # PaddleOCR 추출 (2단계)
│   ├── config.py                # OCR 설정 (타일 크기, 임계값 등)
│   ├── cache/                   # 이미지별 OCR 캐시 (최종 출력물 아님, git 제외)
│   └── output/
│       ├── capture_YYYYMMDD_HHMMSS/
│       └── gui_YYYYMMDD_HHMMSS/
│           └── {index}_{domain}/
│               ├── ocr_asset.txt        # 상품별 OCR 텍스트 통합본
│               └── product.md           # crawl/의 context.md + OCR 텍스트 통합 마크다운
│
├── extract/
│   ├── extractor.py             # 상품 정보 추출 (3단계)
│   ├── config.py                # 추출 설정 (엔진, 키워드, 파라미터 등)
│   └── output/
│       ├── capture_YYYYMMDD_HHMMSS/
│       └── gui_YYYYMMDD_HHMMSS/
│           ├── products_summary.json    # 추출 결과 (JSON)
│           └── products_summary.txt     # 추출 결과 (사람이 읽기 좋은 형식)
│
├── .env                         # API 키 환경변수 (git 제외, 직접 생성 필요)
├── requirements.txt
└── .gitignore
```

---

## 3. 설치

```bash
pip install -r requirements.txt
playwright install chrome
```

### OpenAI API 키 설정

프로젝트 루트에 `.env` 파일을 생성하고 API 키를 입력합니다:

```
OPENAI_API_KEY=sk-...
```

`.env` 파일은 `.gitignore`에 등록되어 있어 git에 올라가지 않습니다.

---

## 4. 사용 방법

### 방법 A: 웹 GUI

```bash
python server.py
```

서버 시작 후 브라우저에서 `http://localhost:8000` 접속.

- URL을 입력하고 **크롤링 시작** 버튼 클릭 (이미지 OCR 포함 여부 토글 가능)
- 실시간 로그 스트리밍으로 진행 상황 확인
- 완료 후 **결과 보기** 버튼으로 상품별 결과 마크다운 렌더링 확인 (OCR을 돌렸으면 OCR 텍스트까지 합쳐진 `product.md`, 아니면 크롤링만 된 `context.md`)
- **추출 실행** 버튼으로 GPT-4o-mini 상품 정보(상품명/제조원/모델번호/규격) 추출 결과 확인
- **실행 기록**은 화면 상단에 접힌 상태로 표시되며, 클릭하면 펼쳐서 과거 실행 목록을 확인할 수 있습니다

### 방법 B: CLI (단계별 개별 실행)

`crawl/urls.txt`에 캡처할 URL을 한 줄에 하나씩 입력합니다:

```
https://kr.misumi-ec.com/vona2/detail/110302634310/
https://www.festo.com/kr/ko/a/8001234/
# 주석 처리된 줄은 무시됩니다
```

```bash
# 크롤링만
python crawl/crawler.py

# OCR만
python ocr/paddle_ocr.py

# 정보 추출만
python extract/extractor.py
```

결과는 `crawl/output/capture_날짜/`, `ocr/output/capture_날짜/`, `extract/output/capture_날짜/`에 저장되며 **자동 삭제되지 않습니다**.

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
- **통합 마크다운(`context.md`) 생성**: DOM 텍스트·표·상품 영역을 LLM 친화적 마크다운 한 파일로 통합 저장합니다.

설정 파일 `crawl/config.py`에서 사이트별 선택자, 봇 차단 대기 시간, OCR 이미지 최소 크기 등을 조정할 수 있습니다.

### 2단계: OCR (ocr/paddle_ocr.py)

PaddleOCR 3.x (PaddleX 백엔드, PaddlePaddle 3.3.1, paddleocr 3.7.0)로 이미지에서 텍스트를 추출합니다.

**인식 모델**: 검출 `PP-OCRv5_mobile_det` + 인식 `korean_PP-OCRv5_mobile_rec`(한국어 특화, 세대만 v5)로 고정합니다. 이 조합으로 초기화가 실패하면(모델 다운로드 불가 등) `lang="korean"` 기반 자동 선택(`PP-OCRv3`)으로 폴백합니다.

> **왜 예전엔 PaddlePaddle 3.0.0에 묶여 있었는가?**  
> `paddleocr>=3.7.0`이 받는 모델은 최신 포맷(PIR)인데 `paddlepaddle==3.0.0`의 추론 엔진이 이 포맷을 못 읽어 오류가 났었습니다. 원인은 "최신 버전 자체가 안 되는 것"이 아니라 "구버전 PaddlePaddle + 신버전 paddleocr"라는 어긋난 조합이었고, PaddlePaddle도 함께 올리면(3.3.1) 정상 동작합니다. 이 조합으로 예전 `korean_PP-OCRv3_mobile_rec`보다 오독이 크게 줄고(예: "2.4GHZ"→"24GHZz" 같은 오독 해소) 신뢰도도 0.94~1.00으로 올라, 언어별로 모델을 나눠 쓸 필요 없이 이 모델 하나로 한국어 문장과 영문·숫자·코드(모델번호, 규격표 등)를 모두 잘 인식합니다. 이 조합은 `numpy>=2.0.0`도 요구해 `pandas`를 함께 올려야 합니다 (`requirements.txt` 주석 참고).

**처리 방식**

- **대상**: `assets/*.png` (이미지·Canvas 스크린샷)
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

**추출 항목**: 상품명, 제조원, 모델번호, 사이즈, 사양

**추출 방식 (우선순위)**:

1. **OpenAI GPT-4o-mini**: OCR이 통합된 `product.md`(없으면 crawl의 `context.md`)를 프롬프트로 넘겨 JSON으로 추출. URL 마지막 경로에서 모델번호로 보이는 패턴을 찾아 힌트로 함께 제공합니다. API 키는 `.env`의 `OPENAI_API_KEY`에서 읽습니다.
2. **규칙 기반 폴백**: API 오류·빈 응답 시 자동으로 전환. 정규식 패턴과 키워드 매칭으로 라벨:값 쌍을 찾아 분류합니다.

---

## 6. 주요 설정

각 단계별 `config.py`에서 동작을 조정합니다.

| 파일 | 주요 설정 |
|---|---|
| `crawl/config.py` | `HEADLESS`, `DEFAULT_VIEWPORT`, `EXCLUDE_DOMAINS`, 사이트별 선택자, OCR 이미지 최소 크기 |
| `ocr/config.py` | `OCR_TILE_HEIGHT`, `OCR_CONFIDENCE_THRESHOLD`, `OCR_CACHE_ENABLED`, `OCR_TEXT_DETECTION_MODEL_NAME`/`OCR_TEXT_RECOGNITION_MODEL_NAME`(고정 모델), `OCR_FALLBACK_OCR_VERSION`(초기화 실패 시 폴백), `OCR_COLUMN_GAP_MIN_RATIO`(다열 레이아웃 분리 기준) |
| `extract/config.py` | `EXTRACTION_ENGINE` (`"gpt"` 또는 `"rules"`), `OPENAI_MODEL`, `OPENAI_MAX_TOKENS`, `SPEC_LABEL_KEYWORDS` |

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

| 사이트 | Crawl | OCR |
|---|---:|---:|
| Misumi | 18.6초 | 37.1초 |
| Festo | 11.2초 | 25.1초 |
| Swagelok | 9.6초 | 167.7초 |
| Siemens Industry Mall | 9.5초 | 93.8초 |
| Navimro (1) | 36.9초 | 37.3초 |
| Danawa | 87.6초 | 177.2초 |
| Navimro (2) | 40.9초 | 115.8초 |
| **단계 합계** | **218.7초** | **664.6초** |

> Extract 단계는 Ollama/Qwen 로컬 추론에서 OpenAI API 호출 방식으로 변경되어 기존 측정값과 직접 비교가 어렵습니다.

---

## 9. GUI 파일 자동 정리 (TTL)

GUI 실행 결과는 `crawl/output/gui_날짜/`, `ocr/output/gui_날짜/`, `extract/output/gui_날짜/` 에 저장됩니다.  
결과 파일이 무한정 쌓이지 않도록 TTL(Time-To-Live) 방식으로 자동 정리합니다.

| 상황 | 동작 |
|---|---|
| 서버 실행 중 | 10분마다 체크 — 완료된 job 중 생성 후 **1시간 초과** 시 삭제 |
| 서버 재시작 | 이전 세션의 `gui_*` 폴더 **전부** 삭제 (서버가 꺼지면 job 정보도 사라지므로) |

CLI로 직접 실행한 결과(`capture_날짜/`)는 이 정리 대상에 포함되지 않습니다. 자동 삭제 없이 영구 보존됩니다.
