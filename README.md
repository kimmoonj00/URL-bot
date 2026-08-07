# 자동화 웹 캡처 봇

전자상거래 사이트에서 제품 URL을 입력하면 전체 페이지를 고해상도로 자동 캡처하고, Google Cloud Vision OCR로 형번·규격·가격 등 제품 사양을 텍스트로 추출하는 자동화 도구입니다.

캡처 시 쿠키 팝업 자동 제거, 더보기 버튼 자동 클릭, lazy-load 콘텐츠 완전 로드 후 캡처 등의 처리를 자동으로 수행합니다. OCR은 단순 텍스트 추출이 아닌 좌표 기반 공간 재조합 방식으로, 표 구조의 행·열 순서를 보존해 추출합니다.

---

## 파이프라인

```
config.py에 URL 입력
    ↓
main.py          — 전체 페이지 고해상도 캡처 → output/ 저장
    ↓
google_ocr_v2.py — Google Vision OCR + 좌표 기반 구조 재조합 → text/ 저장
```

---

## 파일 구조

```
├── main.py             # 웹 페이지 캡처 (Playwright)
├── google_ocr_v2.py    # OCR 메인 (Google Cloud Vision, 좌표 기반 재조합)
├── config.py           # URL 목록 및 설정
├── requirements.txt    # 의존성 패키지
│
├── google_ocr/         # Google Vision 단순 텍스트 추출 (구버전, 참고용)
├── upstage/            # Upstage OCR (정확도 비교 테스트용, 비채택)
├── paddle_ocr/         # PaddleOCR (정확도 비교 테스트용, 비채택)
├── easy_ocr/           # EasyOCR (정확도 비교 테스트용, 비채택)
│
├── output/             # 캡처 이미지 저장 (main.py 실행 결과)
└── text/               # OCR 추출 텍스트 저장 (google_ocr_v2.py 실행 결과)
```

---

## 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

Google Cloud Vision API 인증 (gcloud CLI 필요):

```bash
gcloud auth application-default login
```

---

## 사용 방법

**1. `config.py`에 캡처할 URL 추가**

```python
TARGET_URLS = [
    "https://example-mro-site.com/product/12345",
    ...
]
```

**2. 캡처 실행**

```bash
python main.py
```

`output/capture_YYYYMMDD_HHMMSS/` 폴더에 PNG 이미지로 저장됩니다.

**3. OCR 실행**

```bash
python google_ocr_v2.py
```

`text/capture_YYYYMMDD_HHMMSS/` 폴더에 `.txt` 파일로 저장됩니다.

---

## 주요 특징

- **고해상도 캡처**: `device_scale_factor=2`로 2배 해상도 캡처 (OCR 정확도 향상)
- **팝업 자동 처리**: 쿠키 동의 배너, 오버레이 자동 제거
- **lazy-load 대응**: 스크롤 기반 콘텐츠 완전 로드 후 캡처
- **좌표 기반 OCR**: Vision API 단어별 바운딩 박스를 활용해 표 구조 재조합
- **대용량 이미지 처리**: 8MB 초과 이미지 자동 타일 분할 후 좌표 보정 병합
- **봇 차단 도메인 필터링**: 네이버, 쿠팡 등 자동 제외 (`config.py`에서 관리)

---

## OCR 엔진 비교 경위

Upstage, PaddleOCR, EasyOCR, Google Cloud Vision 총 4가지 엔진을 동일 이미지로 비교 테스트했습니다. PaddleOCR은 소수점 체계적 누락(예: `ZUS-1.5S` → `ZUS-15S`) 등 형번 오인식 문제가 있었고, Upstage·EasyOCR은 Google Vision 대비 전반적인 정확도가 낮아 현재 Google Cloud Vision을 중심으로 진행 중입니다. 각 엔진의 테스트 코드와 결과물은 `upstage/`, `paddle_ocr/`, `easy_ocr/` 폴더에 보관 중입니다.

---

## 지원 사이트 현황

| 사이트 | 캡처 | OCR |
|--------|------|-----|
| Misumi | ✅ | ✅ |
| Festo | ✅ | ✅ |
| Gmarket | ✅ | ✅ |
| Swagelok | ✅ | ✅ |
| Siemens | ✅ | ✅ |
| Auction | ⚠️ Cloudflare 봇 탐지 | — |
| 네이버, 쿠팡 | 🚫 차단 (제외 처리) | — |
