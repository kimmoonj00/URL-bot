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
│               └── ocr_combined.txt     # 상품별 OCR 텍스트 통합본
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

**사용 모델**

| 역할 | 모델 | 설명 |
|---|---|---|
| 텍스트 검출 (Detection) | `PP-OCRv5_mobile_det` | 이미지에서 텍스트 영역 박스를 찾는 모델. mobile = 경량·빠름 |
| 텍스트 인식 (Recognition) | `korean_PP-OCRv5_mobile_rec` | 검출된 영역에서 실제 글자를 읽는 모델. 한국어 특화 학습 버전 |

> **왜 이 조합인가?**  
> PaddleOCR 3.x는 기본적으로 인식 모델로 `PP-OCRv6_medium_rec`를 선택합니다.  
> 그러나 이 모델은 PaddlePaddle 3.0.0의 PIR(Program IR)에서 `strides` 속성 타입 불일치 버그가 있어 실행 시 오류가 납니다.  
> `korean_PP-OCRv5_mobile_rec`는 동일 PIR 환경에서 정상 동작하는 최신 한국어 인식 모델입니다.

**처리 방식**

- **대상**: `assets/*.png`(이미지·Canvas) + `product.png`(상품 본문 스크린샷)
- **타일 분할**: 긴 이미지를 일정 높이로 잘라 처리하고 y좌표 오프셋으로 보정합니다.
- **IOU 중복 제거**: 타일 경계에서 중복 인식된 단어를 신뢰도 기준으로 제거합니다.
- **좌표 기반 행·열 재조합**: 단어별 바운딩 박스 y좌표로 행을 그룹핑하고, x좌표 간격이 넓으면 탭으로 구분해 표 구조를 보존합니다.
- **캐시**: 이미 처리한 이미지는 재실행 시 건너뜁니다(`config.py`에서 끌 수 있음).

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
| `ocr/config.py` | `OCR_TILE_HEIGHT`, `OCR_CONFIDENCE_THRESHOLD`, `OCR_CACHE_ENABLED`, PaddleOCR 엔진 파라미터 |
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
| Misumi | 18.6초 | | 78.8초 | |
| Festo | 11.2초 | | 90.4초 | |
| Swagelok | 9.6초 | | 303.7초 | |
| Siemens Industry Mall | 9.5초 | | 52.6초 | |
| Navimro (1) | 36.9초 | | 101.3초 | |
| Danawa | 87.6초 | | 322.0초 | |
| Navimro (2) | 40.9초 | | 280.8초 | |
| **단계 합계** | **218.7초** | | **1229.6초** | |
