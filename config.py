import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(BASE_DIR, "output")
TEXT_DIR = os.path.join(BASE_DIR, "text")
BROWSER_PROFILE_DIR = os.path.join(BASE_DIR, "chrome_profiles", "product_capture")

# 캡처 대상 URL 목록 파일. 코드 수정 없이 이 파일만 편집하면 대상이 바뀐다.
# 한 줄에 URL 하나. '#'으로 시작하는 줄은 주석으로 무시한다.
URLS_FILE = os.path.join(BASE_DIR, "urls.txt")

# 브라우저 표시 여부 (False: 화면 표시, True: 백그라운드 실행)
HEADLESS = False

# 보안 확인 화면이 나타났을 때 열린 Chrome에서 사용자가 정상 확인을 마칠 최대 시간.
MANUAL_CHALLENGE_WAIT_SECONDS = 20

# Playwright 브라우저 기본 뷰포트 크기
DEFAULT_VIEWPORT = {"width": 1500, "height": 1000}


# 상세 URL 직접 접근을 경계하는 사이트는 먼저 홈페이지에서 정상 세션을 만든다.
WARMUP_URLS = {
    "itempage3.auction.co.kr": "https://www.auction.co.kr/",
}

# ── OCR 공통 설정 (main.py / paddle_ocr.py가 모두 이 값을 사용한다) ─────────
OCR_TILE_HEIGHT = 1200
OCR_TILE_OVERLAP = 100
OCR_CONFIDENCE_THRESHOLD = 0.30
OCR_PADDLE_FALLBACK_THRESHOLD = 0.55
OCR_CACHE_ENABLED = True
OCR_FAST_MODE = True
OCR_MAX_INPUT_WIDTH = 1600
OCR_NUMERIC_REREAD = False
OCR_TABLE_FIRST = True
OCR_TABLE_MIN_WIDTH_RATIO = 0.20

# PaddleOCR 좌표 재조립 파라미터 (paddle_ocr.py 전용, 과거엔 파일 안에 별도 하드코딩되어
# config 값과 어긋나 있었다 — 여기 값이 유일한 기준이다)
OCR_IOU_THRESHOLD = 0.5
OCR_ROW_TOLERANCE = 0.6
OCR_COL_GAP_RATIO = 2.5

# PaddleOCR 엔진 초기화 파라미터
OCR_LANG = "korean"
# 텍스트 방향 분류 모델도 문서방향보정과 같은 계열(PP-LCNet 분류 모델)이라
# 같은 oneDNN 버그를 낼 수 있어 기본은 꺼둔다. 웹 스크린샷은 텍스트가 대부분
# 똑바로 나오므로 정확도 손해는 적다. 문제 없어지면 True로 다시 켜도 된다.
OCR_USE_TEXTLINE_ORIENTATION = False
OCR_TEXT_DET_LIMIT_SIDE_LEN = 4000
OCR_TEXT_DET_LIMIT_TYPE = "max"
# 스캔 문서용 전처리(카메라로 비스듬히 찍은 종이를 펴주는 기능). 웹페이지
# 스크린샷은 이미 똑바르므로 꺼둔다. Windows oneDNN 환경에서 이 모델들이
# "ConvertPirAttribute2RuntimeAttribute" 오류를 내는 버그도 이걸로 회피된다.
OCR_USE_DOC_ORIENTATION_CLASSIFY = False
OCR_USE_DOC_UNWARPING = False
# oneDNN 가속을 아예 끈다 (환경변수 FLAGS_use_mkldnn이 새 PIR 실행기에는 안 먹혀서
# 파라미터로 직접 제어). None으로 두면 파라미터 자체를 안 넘긴다(설치 버전이 지원 안 할 때).
OCR_ENABLE_MKLDNN = False
# 검출 모델을 무거운 서버형(PP-OCRv5_server_det) 대신 경량 모바일형으로 교체.
# 서버형 모델에서 oneDNN 오류가 재현됐을 때의 우회책. 빈 문자열/None이면 기본값 사용.
OCR_TEXT_DETECTION_MODEL_NAME = "PP-OCRv5_mobile_det"

# 하이브리드 추출: DOM에 없는 글자를 읽기 위해 큰 이미지/Canvas만 별도 OCR한다.
MAX_OCR_ASSETS_PER_PAGE = 60
MIN_OCR_ASSET_WIDTH = 250
MIN_OCR_ASSET_HEIGHT = 80
# 현재 환경의 PaddleOCR/NumPy/SciPy 버전 충돌을 피하고 EasyOCR만 사용한다.
# 패키지 호환성을 정리한 뒤 필요할 때 True로 바꿀 수 있다.
OCR_USE_PADDLE_FALLBACK = False

# 상품 본문 후보 선택자. 앞의 선택자부터 시도하고, 모두 실패하면 전체 화면을 OCR한다.
PRODUCT_REGION_SELECTORS = {
    "www.festo.com": ["main", "[data-testid='product-detail']", "#main-content"],
    "mall.industry.siemens.com": ["main", "#content", ".product-detail"],
    "kr.misumi-ec.com": ["main", "#product-detail", ".product-detail"],
    "products.swagelok.com": ["main", "#main-content", ".product-detail"],
    "item.gmarket.co.kr": ["#container", "#itemcase_basic", "main"],
    "itempage3.auction.co.kr": ["#container", "#itemcase_basic", "main"],
}

# 상품명 후보 선택자. 사이트별로 등록해두면 <title> 태그보다 우선 사용한다.
# "*"는 등록되지 않은 사이트에 적용되는 공통 폴백이다.
PRODUCT_NAME_SELECTORS = {
    "kr.misumi-ec.com": ["h1", ".fs-productDetailHeader-title"],
    "www.festo.com": ["h1"],
    "products.swagelok.com": ["h1"],
    "mall.industry.siemens.com": ["h1", ".product-title"],
    "*": ["h1", "[class*='product'][class*='name']", "[class*='product'][class*='title']"],
}

# 사이트별 쿠키 동의 완료 쿠키 (현재 main.py에서 비활성화 상태, 최후의 수단으로 보관 중)
# 클릭 기반 처리(동의 버튼 클릭 / CSS 강제 숨김)로 해결이 안 되는 사이트가 나오면
# 여기에 등록하고 main.py의 "[레이어 3 - 비활성화]" 주석을 해제할 것
# 형식: {'name': '쿠키명', 'value': '값'}
# 사이트 쿠키 이름은 브라우저 개발자도구 → Application → Cookies 에서 확인 가능
#
# 참고: Festo는 OneTrust가 아니라 Didomi를 사용하는 것으로 확인됨 (2026-08-05).
# 벤더를 정확히 모르고 등록하면 이번처럼 아무 효과 없는 값이 될 수 있으니,
# 실제 브라우저 개발자도구에서 쿠키명을 직접 확인한 뒤 등록할 것
SITE_COOKIES = {
    # 예시:
    # "example.com": [
    #     {'name': '쿠키명', 'value': '값'},
    # ],
}

# 제외 (네이버, 쿠팡, 옥션, 지마켓)
EXCLUDE_DOMAINS = [
    "naver.com",
    "coupang.com",
    "auction.co.kr",
    "gmarket.co.kr",
]

# ── 상품명/규격 추출용 설정 (extract_info.py) ───────────────────────────────
# 표/텍스트에서 "라벨: 값" 쌍을 찾을 때, 라벨이 이 키워드 중 하나와 일치하면
# 규격(모델번호/사이즈/사양 등) 후보로 채택한다. 소문자로 비교한다.
SPEC_LABEL_KEYWORDS = {
    "model": ["모델명", "모델번호", "모델", "형번", "품번", "제품번호", "제품코드",
              "model name", "model no", "model number", "model", "type", "type no",
              "part no", "part number", "p/n", "sku", "ordering code", "mlfb", "품목번호"],
    "size": ["사이즈", "규격", "치수", "크기", "size", "dimension", "dimensions"],
    "spec": ["사양", "스펙", "제품사양", "specification", "spec"],
}

# 라벨 없이도 모델번호로 볼 수 있는 값 패턴 (영문+숫자+기호 조합, 최소 4자 이상 등)
SPEC_VALUE_PATTERNS = [
    r"\b[A-Z]{1,6}[-/][A-Z0-9]{1,10}(?:[-/][A-Z0-9]{1,10})*\b",  # 예: T-8M3-1, DSBC-32
    r"\b\d{2,4}-\d{2,6}\b",  # 예: 500-033260
]


def load_target_urls():
    """urls.txt 파일에서 캡처 대상 URL 목록을 읽는다.
    파일이 없거나 비어 있으면 빈 리스트를 반환한다 (코드에 URL을 하드코딩하지 않는다)."""
    if not os.path.exists(URLS_FILE):
        return []
    with open(URLS_FILE, encoding="utf-8") as handle:
        return [
            line.strip()
            for line in handle
            if line.strip() and not line.strip().startswith("#")
        ]


TARGET_URLS = load_target_urls()

# ── 상품정보 추출 엔진 선택 ──────────────────────────────────────────────────
# "qwen": Ollama로 로컬 구동 중인 Qwen에게 물어봐서 추출 (정확도 높음, Ollama 필요)
# "rules": 정규식/키워드 규칙 기반 추출 (오프라인, Ollama 불필요)
# Qwen 호출이 실패하면(Ollama 미실행, 타임아웃, 응답 파싱 실패 등) 자동으로 rules로 폴백한다.
EXTRACTION_ENGINE = "qwen"

OLLAMA_BASE_URL = "http://localhost:11434"
# ollama list로 실제 받아둔 모델 태그를 확인하고 이름이 다르면 맞춰서 바꿀 것.
OLLAMA_MODEL = "qwen2.5:3b"
OLLAMA_TIMEOUT_SECONDS = 120
# 호출 사이에 모델을 메모리에 얼마나 유지할지. 짧게 두면 매 호출마다 로드 오버헤드가
# 생기고, 아예 안 주면 Ollama 기본값(5분)을 쓰지만 여기서는 명시적으로 관리한다.
OLLAMA_KEEP_ALIVE = "5m"
# 응답 최대 토큰 수. JSON 하나만 출력하므로 너무 클 필요는 없지만, model/spec 배열이
# 길어질 수 있어 여유 있게 잡는다.
OLLAMA_NUM_PREDICT = 1024
# 프롬프트에 넣는 각 텍스트 소스(DOM/표/OCR)의 최대 길이. 너무 길면 컨텍스트를
# 낭비하고 느려지므로 앞부분만 잘라서 사용한다.
OLLAMA_MAX_SOURCE_CHARS = 4000
