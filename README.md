# URL Bot — 자동화 웹 캡처 & OCR 텍스트 추출 도구

전자상거래 사이트에서 제품 URL을 입력하면 전체 페이지를 고해상도로 자동 캡처하고, 여러 OCR 엔진으로 텍스트를 추출한 뒤 LLM으로 상품 정보만 정제해 저장하는 자동화 도구입니다.

캡처 시 쿠키 팝업 자동 제거, 더보기 버튼 자동 클릭, lazy-load 콘텐츠 완전 로드 후 캡처 등의 처리를 자동으로 수행합니다. OCR은 단순 텍스트 추출이 아닌 **좌표 기반 공간 재조합 방식**으로 표 구조의 행·열 순서를 보존해 추출하며, 이후 LLM이 네비게이션·푸터 등 노이즈를 제거하고 형번·규격·가격 정보만 정제합니다.

---

## 목차

1. [파이프라인](#1-파이프라인)
2. [파일 구조](#2-파일-구조)
3. [설치](#3-설치)
4. [사용 방법](#4-사용-방법)
5. [주요 특징](#5-주요-특징)
6. [OCR 엔진 비교](#6-ocr-엔진-비교)
7. [성능 개선 적용 현황](#7-성능-개선-적용-현황)
8. [지원 사이트 현황](#8-지원-사이트-현황)
9. [단계별 소요 시간](#9-단계별-소요-시간)
10. [트러블슈팅](#10-트러블슈팅)

[부록 A. API 키 설정](#부록-a-api-키-설정)  
[부록 B. Google Cloud Vision 인증](#부록-b-google-cloud-vision-인증)

---

## 1. 파이프라인

```
capture/config.py 에 URL 입력
        ↓
capture/capture.py          — 전체 페이지 고해상도 캡처 → capture/output/ 저장
        ↓
ocr/google_ocr.py        — Google Cloud Vision + 좌표 기반 구조 재조합
ocr/paddle_ocr.py        — PaddleOCR (PP-OCRv5) + 좌표 기반 구조 재조합
ocr/easy_ocr.py          — EasyOCR + 좌표 기반 구조 재조합
ocr/upstage_ocr.py       — Upstage OCR API + 좌표 기반 구조 재조합
ocr/upstage_dp.py        — Upstage Document Parse Enhanced (실험용)
        ↓
ocr/output/{엔진명}/      — 엔진별 텍스트 추출 결과 저장
        ↓
extract/llm_filter.py    — LLM 노이즈 필터 (Ollama + Qwen3) → 상품 정보만 추출
        ↓
extract/output/          — 정제된 상품 정보 저장
```

---

## 2. 파일 구조

```
├── capture/
│   ├── capture.py              # 웹 페이지 캡처 (Playwright)
│   ├── config.py            # URL 목록 및 캡처 설정
│   └── output/              # 캡처 이미지 저장 (capture.py 실행 결과)
│
├── ocr/
│   ├── google_ocr.py        # Google Cloud Vision OCR
│   ├── paddle_ocr.py        # PaddleOCR (PP-OCRv5 한국어)
│   ├── easy_ocr.py          # EasyOCR (한국어 + 영어)
│   ├── upstage_ocr.py       # Upstage OCR API
│   ├── upstage_dp.py        # Upstage Document Parse Enhanced (실험용)
│   └── output/
│       ├── google_ocr/      # Google Vision 추출 결과 (.txt)
│       ├── paddle_ocr/      # PaddleOCR 추출 결과 (.txt)
│       ├── easy_ocr/        # EasyOCR 추출 결과 (.txt)
│       ├── upstage_ocr/     # Upstage OCR 추출 결과 (.txt)
│       └── upstage_dp/      # Upstage Document Parse 결과 (.md)
│
├── extract/
│   ├── llm_filter.py        # LLM 노이즈 필터 (Ollama + Qwen3)
│   └── output/              # LLM 필터링 결과 저장
│
├── .env                     # API 키 (git 제외)
├── requirements.txt         # 의존성 패키지
└── .gitignore
```

---

## 3. 설치

### 3-1. Python 패키지

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3-2. Ollama 설치 (Extract 단계)

[ollama.com](https://ollama.com) 에서 Ollama를 설치한 뒤 Qwen3 모델을 다운로드합니다:

```bash
ollama pull qwen3:1.7b
```

> Ollama는 LLM을 로컬에서 실행하는 런타임입니다. Qwen3는 Ollama 위에서 동작하는 모델로, OCR 결과에서 상품 정보만 추출하는 Extract 단계에 사용됩니다.

유료 API(Google Vision, Upstage)를 사용하는 경우 [부록 A](#부록-a-api-키-설정)를 참고합니다.

---

## 4. 사용 방법

### 4-1. URL 설정

`capture/config.py`에 캡처할 URL을 추가합니다:

```python
TARGET_URLS = [
    "https://example-mro-site.com/product/12345",
    ...
]
```

### 4-2. 캡처 실행

```bash
python capture/capture.py
```

`capture/output/capture_YYYYMMDD_HHMMSS/` 폴더에 PNG 이미지로 저장됩니다.

### 4-3. OCR 실행

원하는 엔진을 선택해 실행합니다:

```bash
python ocr/paddle_ocr.py      # PaddleOCR PP-OCRv5 (무료, 권장)
python ocr/google_ocr.py      # Google Cloud Vision (정확도 최고, 유료)
python ocr/easy_ocr.py        # EasyOCR (무료, 한국어 오인식 주의)
python ocr/upstage_ocr.py     # Upstage OCR API (유료)
python ocr/upstage_dp.py      # Upstage Document Parse (실험용)
```

결과는 `ocr/output/{엔진명}/capture_YYYYMMDD_HHMMSS/` 폴더에 저장됩니다.

### 4-4. Extract 실행

```bash
python extract/llm_filter.py
```

`ocr/output/` 아래의 모든 `.txt` 파일을 읽어 LLM으로 노이즈를 제거한 뒤 `extract/output/` 에 동일한 폴더 구조로 저장합니다.

---

## 5. 주요 특징

- **고해상도 캡처**: `device_scale_factor=2`로 2배 해상도 캡처 (OCR 정확도 향상)
- **팝업 자동 처리**: 쿠키 동의 배너, 오버레이 자동 제거
- **lazy-load 대응**: 스크롤 기반 콘텐츠 완전 로드 후 캡처
- **좌표 기반 OCR**: 단어별 바운딩 박스를 활용해 표 구조 행·열을 공간적으로 재조합 (5개 엔진 공통)
- **타일 분할 처리**: 대용량 이미지를 타일로 분할 후 좌표 보정 병합
- **타일 오버랩**: 타일 경계 절단 방지를 위한 150px 겹침 + IOU 중복 제거 (PaddleOCR, EasyOCR)
- **신뢰도 필터링**: 낮은 신뢰도 노이즈 토큰 자동 제거 (PaddleOCR 0.4, EasyOCR 0.3)
- **LLM 노이즈 필터링**: OCR 결과에서 네비게이션·푸터·광고 노이즈 제거, 상품명·규격·가격 정보만 추출 (Ollama + Qwen3, 로컬 실행)
- **API 키 보안**: `.env` 기반 관리 (코드 하드코딩 없음)
- **봇 차단 도메인 필터링**: 네이버, 쿠팡 등 자동 제외 (`config.py`에서 관리)

---

## 6. OCR 엔진 비교

### 6-1. 항목별 성능 비교

| 비교 항목 | Google Vision | PaddleOCR | EasyOCR | Upstage OCR | Upstage DP |
|---|:---:|:---:|:---:|:---:|:---:|
| 한국어 OCR 정확도 | ★★★★★ | ★★★★☆ | ★★☆☆☆ | ★★★★☆ | ★★★☆☆ |
| 표 구조 추출 | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★★☆☆ | ★☆☆☆☆ |
| 한·영·숫자 혼합 인식 | ★★★★★ | ★★★★☆ | ★★☆☆☆ | ★★★★☆ | ★★★☆☆ |
| 대용량 이미지 처리 | ★★★★☆ | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| 비용 효율성 | ★★☆☆☆ | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★☆☆☆ |
| 설치·환경 설정 | ★★★★☆ | ★★★☆☆ | ★★★★★ | ★★★★☆ | ★★★★☆ |
| **종합 평점** | **★★★★★** | **★★★★☆** | **★★★☆☆** | **★★★☆☆** | **★★☆☆☆** |

> **표 구조 추출** — Gmarket 규격표(9행) 기준, PaddleOCR은 Google Vision과 동등 수준으로 추출  
> **EasyOCR 한국어** — 좌표 기반 구조는 정상이나 문자 자체 오인식 심각 (`mm→rnrn`, `100→IUU`)  
> **Upstage DP 표 추출** — 셀이 개별 텍스트 블록으로 분해되어 행·열 구조 완전 소실  
> **비용 효율성** — 무료(PaddleOCR·EasyOCR) = ★★★★★, 유료 API 비교는 Google Vision 대비 상대적 평가

### 6-2. 엔진별 장단점

| 엔진 | 비용 | 장점 | 단점 |
|---|---|---|---|
| **Google Vision** | 유료 (API) | 정확도 최고, 한국어·영문·숫자 안정적, 타일 경계 처리 우수 | 비용 발생, 네트워크 의존 |
| **PaddleOCR** | 무료 | PP-OCRv5 한국어 모델로 Google Vision 수준, 로컬 실행 | 초기 모델 다운로드 필요, Windows SAC 환경에서 pandas stub 필요 |
| **EasyOCR** | 무료 | 설치 간단, 다국어 지원 | 한국어+숫자+영문 혼합 시 오인식 심각 (`mm→rnrn`, `100→IUU`, `1/2→12`) |
| **Upstage OCR** | 유료 (API) | 한국어 특화 | 복잡한 시각 표에서 Google Vision 대비 낮은 정확도 |
| **Upstage DP** | 유료 (API) | 문서 파싱 특화, Markdown 출력 | 웹 스크린샷 대용량 처리 불가, 표 구조 복원 실패, 타일링 없음 |

---

## 7. 성능 개선 적용 현황

| 개선 항목 | Google Vision | Upstage OCR | PaddleOCR | EasyOCR | Upstage DP |
|---|:---:|:---:|:---:|:---:|:---:|
| 좌표 기반 행 재조립 | ✅ | ✅ | ✅ | ✅ | ❌ |
| 탭 삽입 (열 구분) | ✅ | ✅ | ✅ | ✅ | ❌ |
| 타일링 (대용량 처리) | ✅ 8MB↑ | ✅ 5MB↑ | ✅ 항상 | ✅ 항상 | ❌ 리사이즈만 |
| 타일 오버랩 150px | ❌ | ❌ | ✅ | ✅ | N/A |
| IOU 중복 제거 | ❌ | ❌ | ✅ | ✅ | N/A |
| 신뢰도 필터링 | ❌ | ❌ | ✅ 0.4 | ✅ 0.3 | N/A |
| 모델 업그레이드 | N/A | N/A | ✅ (3.7.0 기본값) | ❌ | ✅ nightly |

---

## 8. 지원 사이트 현황

| 사이트 | 캡처 | OCR | Extract |
|---|---|---|---|
| Misumi (kr.misumi-ec.com) | ✅ | ✅ | ✅ |
| Festo (www.festo.com) | ✅ | ✅ | ✅ |
| Gmarket (item.gmarket.co.kr) | ✅ | ✅ | ✅ |
| Swagelok (products.swagelok.com) | ✅ | ✅ | ✅ |
| Siemens Industry Mall | ✅ | ✅ | ✅ |
| Navimro (www.navimro.com) | ✅ | ✅ | ✅ |
| Auction (itempage3.auction.co.kr) | ⚠️ Cloudflare 봇 탐지 | — | — |
| 네이버, 쿠팡 | 🚫 차단 (자동 제외) | — | — |

---

## 9. 단계별 소요 시간

| 사이트 | Capture | OCR | Extract | 합계 |
|---|---:|---:|---:|---:|
| kr.misumi-ec.com | 33.4초 | 129.0초 | - | 162.4초 (2분 42초) |
| www.festo.com | 34.6초 | 93.4초 | - | 128.0초 (2분 8초) |
| www.navimro.com | 45.7초 | 133.6초 | - | 179.3초 (2분 59초) |
| products.swagelok.com | 27.4초 | 127.4초 | - | 154.8초 (2분 35초) |
| mall.industry.siemens.com | 27.8초 | 74.7초 | - | 102.5초 (1분 43초) |

---

## 10. 트러블슈팅

### PaddleOCR 실행 시 `DLL load failed` 오류

**증상**

```
ImportError: DLL load failed while importing timestamps:
애플리케이션 제어 정책에서 이 파일을 차단했습니다.
```

또는

```
ImportError: DLL load failed while importing escape:
애플리케이션 제어 정책에서 이 파일을 차단했습니다.
```

**원인**

Windows 11 Smart App Control(SAC)이 `paddleocr → paddlex → pandas` 의존성 체인의 pandas C 확장(`.pyd`) 파일을 차단합니다. SAC는 클라우드 평판 DB 기반으로 신규 설치된 `.pyd`를 "실행 이력 없음 = 낮은 평판"으로 판정하며, pandas 버전을 바꿔도 동일하게 차단됩니다.

**해결**

`paddle_ocr.py` 최상단의 `_stub_pandas()`가 `sys.meta_path`에 가짜 pandas 모듈을 주입해 실제 C 확장 로드를 우회합니다. paddleocr은 OCR 처리 자체에 pandas를 사용하지 않으므로(CSV/시계열용 의존성만 존재) 동작에 영향이 없습니다.

> SAC 비활성화로도 해결되지만, 한 번 끄면 Windows 초기화 전까지 되돌릴 수 없으므로 권장하지 않습니다.

---

## 부록 A. API 키 설정

유료 OCR API(Google Vision, Upstage)를 사용하는 경우 프로젝트 루트에 `.env` 파일을 생성합니다:

```
UPSTAGE_API_KEY=your_upstage_api_key_here

# Google 인증 경로 (미설정 시 gcloud ADC 자동 감지)
# GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\application_default_credentials.json
```

---

## 부록 B. Google Cloud Vision 인증

gcloud CLI 설치 후 아래 명령어로 인증합니다:

```bash
gcloud auth application-default login
```

> `.env`에 `GOOGLE_APPLICATION_CREDENTIALS` 경로를 명시해도 되고, 미설정 시 gcloud ADC를 자동 감지합니다.
