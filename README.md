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
        │  · 타일 분할 → 좌표 기반 행·열 재조합 → IOU 중복 제거
        │  · 상품별 ocr_combined.txt 생성
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
│   └── output/
│       └── capture_YYYYMMDD_HHMMSS/
│           └── {index}_{domain}/
│               ├── ocr_text/            # 이미지별 OCR 텍스트
│               ├── ocr_combined.txt     # 상품별 OCR 텍스트 통합본
│               └── context.md           # crawl/의 context.md + OCR 텍스트 통합 마크다운
│
├── extract/
│   ├── extractor.py             # 상품 정보 추출 — 파이프라인·규칙 기반·LLM 통합 (3단계)
│   ├── config.py                # 추출 설정 (키워드, LLM 파라미터 등)
│   └── output/
│       └── capture_YYYYMMDD_HHMMSS/
│           ├── products_summary.json    # 추출 결과 (JSON)
│           └── products_summary.txt     # 추출 결과 (사람이 읽기 좋은 형식)
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

PaddleOCR 3.x (PaddleX 백엔드, PaddlePaddle 3.0.0)로 이미지에서 텍스트를 추출합니다.

**언어별 모델 자동 분기**

| 상황 | 인식 모델 | 특징 |
|---|---|---|
| 한국어 페이지 (기본값) | `korean_PP-OCRv3_mobile_rec` | 한국어 특화 모델. 자연스러운 한국어 문장에 가장 정확 |
| 외국어 페이지 (예: 지멘스처럼 한글이 거의 없는 페이지) | `PP-OCRv5_mobile_rec` (범용 다국어) | 영문·숫자/코드(모델번호, 규격표 등) 인식이 훨씬 정확 |

> **왜 언어별로 나누는가?**  
> 범용 모델(PP-OCRv5)은 영문과 숫자·코드는 한국어 전용 모델보다 훨씬 정확하지만, 자연스러운 한국어 문장은 한자로 잘못 읽는 경우가 많습니다(실측: 한글 마케팅 카피가 의미 없는 한자로 깨짐). 반대로 한국어 전용 모델은 작은 글씨 표나 영문 텍스트에 약합니다. 그래서 crawl/이 만든 `context.md`의 한글 비율을 보고(`detect_product_lang`) 상품 페이지마다 알맞은 모델을 자동으로 고릅니다. `paddleocr==3.7.0` 이상은 `PP-OCRv6_medium_rec` 같은 모델을 기본 선택해 PaddlePaddle 3.0.0과 모델 포맷(PIR)이 안 맞아 오류가 나므로, `paddleocr`는 3.0.0으로 고정하고 `ocr_version`을 명시해서 씁니다.

**처리 방식**

- **대상**: `assets/*.png`(이미지·Canvas) + `product.png`(상품 본문 스크린샷)
- **타일 분할**: 긴 이미지를 일정 높이로 잘라 처리하고 y좌표 오프셋으로 보정합니다.
- **IOU 중복 제거**: 타일 경계에서 중복 인식된 단어를 신뢰도 기준으로 제거합니다.
- **블록 분리**: 제품 카드 + 표처럼 가로로 나란히 배치된 서로 다른 콘텐츠가 한 줄로 섞이지 않도록, 세로로 길게 비어 있는 영역을 기준으로 블록을 먼저 나눕니다.
- **소형 텍스트 확대 재인식**: 평균 글자 높이가 작은(표처럼 촘촘한) 블록은 그 영역만 원본에서 잘라 확대한 뒤 같은 엔진으로 다시 인식합니다.
- **표 헤더 기준 열 재조합**: 3~6열짜리 표는 헤더 행의 열 위치(x좌표)를 기준 삼아 데이터 행의 단어를 배정합니다 — 열 사이 인쇄 간격이 좁아 같은 행 안의 간격만으로는 못 나누는 경우도 표 구조를 그대로 따라갑니다. 일반 문단·"라벨: 값" 목록에는 적용하지 않도록 조건을 두어 회귀를 방지합니다. 일부 행의 좌표가 어긋나도 그 행만 간격 기반으로 대체하고 나머지 행의 열 구조는 그대로 살립니다.
- **표 열 단위 언어 전환**: `detect_product_lang`은 상품 페이지 전체 기준이라, 한국어 위주 페이지 안에 박힌 규격표(모델번호·숫자 위주)는 그대로 두면 여전히 한국어 모델로 깨집니다. 표로 인식된 블록은 헤더 열 위치를 기준으로 각 열에 숫자·라틴 문자가 몰려 있는지(한글이 하나라도 섞여 있으면 절대 제외) 판단해, 숫자/모델명 열만 범용 모델(PP-OCRv5)로 다시 인식합니다. 같은 행에 있는 한글 열("형태" 등)은 건드리지 않아 모델번호·규격값과 한글 값을 동시에 살릴 수 있습니다. 정확도를 우선한 선택이라 표가 있는 이미지는 처리 시간이 늘어날 수 있습니다.
- **좌표 기반 행·열 재조합**: 그 외에는 단어별 바운딩 박스 y좌표로 행을 그룹핑하고, x좌표 간격이 넓으면 탭으로 구분합니다.
- **띄어쓰기 복원**: 한국어 모델이 인식한 줄만 `kiwipiepy`(형태소 분석기)로 띄어쓰기를 복원합니다. 표 열 단위 전환 등으로 범용 모델이 대신 인식한 줄에는 적용하지 않습니다.
- **캐시**: 이미 처리한 이미지는 재실행 시 건너뜁니다(`config.py`에서 끌 수 있음).
- **상품 단위 프로세스 격리 + 자동 재시도**: 메모리가 넉넉하지 않은 환경에서 PaddleOCR 네이티브 추론이 죽거나 멈추는 경우가 있어, 상품 폴더 단위로 별도 프로세스에서 처리하고 실패 시 자동 재시도합니다 — 한 상품이 실패해도 다른 상품과 이미 처리된 결과에는 영향이 없습니다.
- **통합 마크다운(`context.md`) 생성**: crawl/이 만든 DOM 표·텍스트 마크다운에 OCR 텍스트 섹션을 더해, LLM에 바로 넘길 수 있는 상품별 통합 문서를 `ocr/output/`에 생성합니다. OCR 대상 이미지가 없거나 전부 인식에 실패해도(예: 크롤링 과정에서 이미지를 못 받은 상품) crawl의 DOM 표·텍스트만으로 항상 생성되므로, extract는 모든 크롤 상품 폴더에 대해 읽을 파일이 보장됩니다.

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
| `ocr/config.py` | `OCR_TILE_HEIGHT`, `OCR_CONFIDENCE_THRESHOLD`, `OCR_CACHE_ENABLED`, `OCR_VERSION`/`OCR_FOREIGN_LANG_OCR_VERSION`(언어별 모델), `OCR_LANG_DETECT_MAX_HANGUL_RATIO`(언어 판단 기준) |
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
