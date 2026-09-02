# URL Bot — 상품 URL 자동 크롤링 · OCR · 정보 추출 도구

상품 URL을 붙여넣으면 페이지를 자동으로 열어 텍스트와 이미지를 수집하고, 이미지 속 규격 정보까지 읽어낸 뒤, GPT로 상품명·모델번호·제조원·사양을 정리해줍니다.

---

## 목차

1. [파이프라인 개요](#1-파이프라인-개요)
2. [폴더 구조](#2-폴더-구조)
3. [설치](#3-설치)
4. [사용 방법](#4-사용-방법)
5. [각 단계 상세](#5-각-단계-상세)
6. [주요 설정](#6-주요-설정)
7. [성능 측정](#7-성능-측정)
8. [슬랙봇](#8-슬랙봇)

---

## 1. 파이프라인 개요

> URL 하나를 넣으면 크롤링 → OCR → 추출, 세 단계를 자동으로 거쳐 구조화된 상품 정보가 나옵니다.  
> 각 단계는 독립적으로도 실행할 수 있습니다.

```
URL 입력 (GUI 또는 crawl/urls.txt)
        │
        ▼
[ 1단계 ] crawl/crawler.py   — 상품 페이지 크롤링
        │  · 페이지 텍스트·표 → context.md
        │  · OCR 대상 이미지 → assets/*.png
        │    (브라우저 fetch → urllib → 스크린샷 3단계 다운로드)
        │
        ▼   crawl/output/{run_name}/{index}_{domain}/
        │
        ▼
[ 2단계 ] ocr/paddle_ocr.py  — 이미지에서 텍스트 추출  (선택)
        │  · 이미지 속 규격·모델번호 등 인식
        │  · context.md + OCR 결과 합본 → product.md
        │
        ▼   ocr/output/{run_name}/{index}_{domain}/
        │
        ▼
[ 3단계 ] extract/extractor.py  — GPT로 상품 정보 추출
           · 상품명 / 제조원 / 모델번호 / 규격 정리
           · 각 항목에 출처 표시 (DOM: 페이지 텍스트, OCR: 이미지 인식)

           extract/output/{run_name}/
```

---

## 2. 폴더 구조

> 크롤링·OCR·추출 결과는 각 단계 폴더의 `output/` 아래에 실행 날짜별로 저장됩니다.

```
URL-bot/
├── server.py                    # 웹 GUI 서버 (FastAPI)
├── slack_bot.py                 # 슬랙봇 (Slack Bolt, Socket Mode)
│
├── web/
│   ├── index.html               # 웹 프론트엔드
│   ├── app.js                   # 프론트엔드 JS
│   └── style.css                # 스타일
│
├── crawl/
│   ├── crawler.py               # 크롤링 (1단계)
│   ├── config.py                # 크롤링 설정
│   ├── urls.txt                 # CLI 실행 시 대상 URL 목록
│   ├── chrome_profiles/         # 로그인 세션 저장용 Chrome 프로필
│   └── output/
│       └── {run_name}/
│           └── {index}_{domain}/
│               ├── context.md       # 페이지 텍스트·표 통합 마크다운
│               ├── assets/          # OCR 대상 이미지
│               ├── assets.json      # 이미지 메타데이터
│               └── metadata.json    # URL, 상태, 소요시간 등
│
├── ocr/
│   ├── paddle_ocr.py            # OCR (2단계)
│   ├── config.py                # OCR 설정
│   ├── cache/                   # 이미지별 OCR 캐시 (git 제외)
│   └── output/
│       └── {run_name}/
│           └── {index}_{domain}/
│               ├── ocr_asset.txt    # 이미지별 OCR 결과
│               └── product.md       # context.md + OCR 합본
│
├── extract/
│   ├── extractor.py             # 상품 정보 추출 (3단계)
│   ├── config.py                # 추출 설정
│   └── output/
│       └── {run_name}/
│           └── {domain}.json        # 추출 결과
│
├── .env                         # API 키 (git 제외, 직접 생성 필요)
├── requirements.txt
└── .gitignore
```

---

## 3. 설치

> Python 패키지 설치와 OpenAI API 키 설정 두 가지만 하면 바로 사용할 수 있습니다.

```bash
pip install -r requirements.txt
playwright install chrome
```

프로젝트 루트에 `.env` 파일을 만들고 API 키를 입력합니다:

```
OPENAI_API_KEY=sk-...

# 슬랙봇 사용 시 추가
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
```

`.env` 파일은 `.gitignore`에 등록되어 있어 git에 올라가지 않습니다.

---

## 4. 사용 방법

### 방법 A: 웹 GUI

> 브라우저에서 URL을 붙여넣고 버튼만 누르면 됩니다.  
> 실시간 로그로 진행 상황을 확인하고, 추출 결과를 표로 바로 볼 수 있습니다.

```bash
python server.py
```

서버 시작 후 `http://localhost:8000` 접속.

**Step 1 — 크롤링**

1. URL 입력창에 상품 URL 입력 (한 줄에 하나씩, Ctrl+Enter로 바로 실행)
2. 이미지 속 텍스트도 읽으려면 **이미지 OCR 포함** 토글 켜기
3. **실행** 클릭 → 실시간 로그로 진행 상황 확인
4. 완료 후 **결과 보기**로 수집된 내용 확인

**Step 2 — 데이터 추출**

1. **Extract 실행** 클릭 → GPT가 상품명·제조원·모델번호·규격을 표로 정리
2. 각 항목 옆 뱃지로 출처 확인
   - `DOM`: 페이지 텍스트·표에서 읽은 정보
   - `OCR`: 이미지에서 인식한 정보 (오탈자 가능성 있음)

**실행 기록**: 화면 상단 **실행 기록** 섹션에서 이전 실행 결과를 다시 볼 수 있습니다.

---

### 방법 B: 슬랙봇

> Slack App Home에서 URL을 입력하면 크롤링과 Extract를 슬랙 안에서 바로 실행할 수 있습니다.  
> 결과는 DM으로 받고, Extract 버튼 한 번으로 추출까지 완료됩니다.  
> 자세한 설정 방법은 [8. 슬랙봇](#8-슬랙봇) 섹션을 참고하세요.

```bash
python slack_bot.py
```

**흐름**

1. Slack에서 URL Bot 앱의 **App Home** 탭 열기
2. **새 작업 시작** 버튼 클릭 → URL 입력 모달에 상품 URL 입력 (한 줄에 하나씩)
3. OCR이 필요하면 **OCR 포함** 체크 후 **실행**
4. 처리 완료 시 DM으로 결과 통보 → **📊 Extract 실행** 버튼 클릭
5. DM에 상품명·제조원·모델번호·규격이 표시됨

---

### 방법 C: CLI (단계별 개별 실행)

> 자동화 스크립트나 대량 처리에 적합합니다.  
> `crawl/urls.txt`에 URL을 넣고 각 단계를 순서대로 실행합니다.

```
https://kr.misumi-ec.com/vona2/detail/110302634310/
https://www.festo.com/kr/ko/a/8001234/
# 주석 처리된 줄은 무시됩니다
```

```bash
python crawl/crawler.py      # 1단계: 크롤링
python ocr/paddle_ocr.py     # 2단계: OCR
python extract/extractor.py  # 3단계: 추출
```

---

## 5. 각 단계 상세

### 1단계: 크롤링 (crawl/crawler.py)

> 실제 Chrome 브라우저로 페이지를 열어 텍스트·표·이미지를 수집합니다.  
> 로그인 상태 유지, 봇 차단 대응, 더보기 자동 클릭까지 처리합니다.

- **세션 재사용**: Chrome 프로필을 저장해 로그인·쿠키 상태를 다음 실행에도 유지
- **봇 차단 대응**: Cloudflare 등 차단 감지 시 수동 확인 완료까지 자동 대기
- **페이지 자동 조작**: 쿠키 동의·더보기 버튼 자동 클릭, 지연 로딩 완료 후 수집
- **표 병합**: 열 고정으로 분리 렌더링된 표(MISUMI 등)를 하나로 합쳐서 저장
- **병렬 처리**: 여러 URL 동시 크롤링 (기본 3개)
- **지원 사이트**: Misumi, Festo, Swagelok, Siemens Industry Mall, Navimro, Danawa는 상품 영역 선택자가 등록되어 더 정확하게 수집됩니다. 등록되지 않은 사이트도 일반 크롤링으로 동작합니다. 네이버·쿠팡·지마켓·옥션은 자동으로 제외됩니다.
- **이미지 3단계 다운로드**: OCR용 이미지를 아래 순서로 시도해 잘린 이미지 없이 원본을 확보
  1. **브라우저 fetch** — 쿠키·세션이 살아있는 상태로 브라우저 내부에서 직접 다운로드 (CORS 우회, 로그인 이미지 포함)
  2. **Python urllib 폴백** — 브라우저 fetch가 CORS·SSL 오류로 실패하면 Python이 직접 HTTP 요청으로 재시도
  3. **element.screenshot() 최종 폴백** — 위 둘 모두 실패하거나 data:/blob: URL인 경우 요소 단위 스크린샷으로 저장

### 2단계: OCR (ocr/paddle_ocr.py)

> 이미지 속 텍스트를 PaddleOCR로 인식해 페이지 텍스트와 합칩니다.  
> 이미지에만 있는 규격·모델번호도 놓치지 않고 추출할 수 있습니다.

- **인식 모델**: `PP-OCRv5_mobile_det` + `korean_PP-OCRv5_mobile_rec` — 한국어·영문·숫자 통합 인식
- **타일 분할**: 긴 이미지를 잘라 처리 후 좌표로 재조합. 타임아웃은 이미지 수가 아닌 **예상 타일 수**에 비례해 계산해 초대형 이미지도 안정적으로 처리
- **배치 처리**: 한 실행의 미처리 이미지를 모아 **엔진 1번 로딩**으로 처리 (상품마다 새 프로세스를 띄우던 방식에서 개선, 상품이 많을수록 시간 단축)
- **다열 레이아웃 분리**: 가로로 나란한 제품 카드·표를 열별로 나눠 인식
- **중복 제거**: 타일 경계에서 겹쳐 인식된 텍스트를 신뢰도(IOU) 기준으로 제거
- **캐시**: 이미지별 결과를 `ocr/cache/`에 저장해 재실행 시 건너뜀

### 3단계: 정보 추출 (extract/extractor.py)

> GPT-4o-mini가 수집된 텍스트를 읽고 상품 정보를 구조화된 JSON으로 정리합니다.  
> OCR 없이 크롤링만 했으면 페이지 텍스트로, OCR까지 했으면 이미지 텍스트까지 합쳐서 추출합니다.

**추출 항목**: 상품명, 제조원, 모델번호, 규격

**출처 추적**: 각 항목이 어디서 왔는지 기록

```json
{
  "상품명": "string",
  "제조원": "string",
  "제조원_source": "dom | ocr",
  "variants": [
    {
      "model": "string",
      "model_source": "dom | ocr",
      "규격": [{ "text": "string", "source": "dom | ocr" }]
    }
  ]
}
```

**폴백**: GPT 오류·빈 응답 시 정규식/키워드 규칙 기반으로 자동 전환

---

## 6. 주요 설정

> 각 단계의 `config.py`에서 동작을 조정할 수 있습니다.

| 파일 | 주요 설정 |
|---|---|
| `crawl/config.py` | `HEADLESS`, `MAX_CONCURRENT_PAGES`, `EXCLUDE_DOMAINS`, 사이트별 CSS 선택자 |
| `ocr/config.py` | `OCR_TILE_HEIGHT`, `OCR_CONFIDENCE_THRESHOLD`, `OCR_CACHE_ENABLED`, 인식 모델명 |
| `extract/config.py` | `EXTRACTION_ENGINE` (`"gpt"` 또는 `"rules"`), `OPENAI_MODEL`, `SPEC_LABEL_KEYWORDS` |

---

## 7. 성능 측정 (수정 예정)

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

---

## 8. 슬랙봇

> Slack 앱을 설치하면 브라우저 없이 슬랙에서 바로 URL을 입력하고 결과를 받을 수 있습니다.  
> Socket Mode로 동작하므로 외부 서버 없이 로컬에서 실행됩니다.

### 실행

```bash
python slack_bot.py
```

### 사용 흐름

```
App Home [새 작업 시작]
        │
        ▼
URL 입력 모달 (여러 URL, OCR 옵션)
        │
        ▼
백그라운드 실행: 크롤링 (→ OCR)
        │
        ▼
DM: ✅ 크롤링 완료 + [📊 Extract 실행] 버튼
        │
        ▼
DM: 상품명 / 제조원 / 모델번호 / 규격 (표 형식)
```

### 주의사항

- 모델 15개를 초과하는 경우 DM에는 상위 15개만 표시됩니다.
