import os

_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_DIR)  # 루트 (crawler.py에서 BASE_DIR 참조용)

BROWSER_PROFILE_DIR = os.path.join(_DIR, "chrome_profiles", "product_capture")

# 캡처 대상 URL 목록 파일. 코드 수정 없이 이 파일만 편집하면 대상이 바뀐다.
URLS_FILE = os.path.join(_DIR, "urls.txt")

# 브라우저 표시 여부 (False: 화면 표시, True: 백그라운드 실행)
HEADLESS = True

# 보안 확인 화면이 나타났을 때 열린 Chrome에서 사용자가 정상 확인을 마칠 최대 시간.
MANUAL_CHALLENGE_WAIT_SECONDS = 20

# Playwright 브라우저 기본 뷰포트 크기
DEFAULT_VIEWPORT = {"width": 1500, "height": 1000}

# 상세 URL 직접 접근을 경계하는 사이트는 먼저 홈페이지에서 정상 세션을 만든다.
WARMUP_URLS = {
    "itempage3.auction.co.kr": "https://www.auction.co.kr/",
}

# 하이브리드 추출: DOM에 없는 글자를 읽기 위해 큰 이미지/Canvas만 별도 OCR한다.
MAX_OCR_ASSETS_PER_PAGE = 60
MIN_OCR_ASSET_WIDTH = 250
MIN_OCR_ASSET_HEIGHT = 80

# 상품 본문 후보 선택자. 앞의 선택자부터 시도하고, 모두 실패하면 전체 화면을 OCR한다.
PRODUCT_REGION_SELECTORS = {
    "www.festo.com": ["main", "[data-testid='product-detail']", "#main-content"],
    "mall.industry.siemens.com": ["main", "#content", ".product-detail"],
    "kr.misumi-ec.com": ["main", "#product-detail", ".product-detail"],
    "products.swagelok.com": ["main", "#main-content", ".product-detail"],
    "item.gmarket.co.kr": ["#container", "#itemcase_basic", "main"],
    "itempage3.auction.co.kr": ["#container", "#itemcase_basic", "main"],
    "www.navimro.com": ["#container", "#prdDetail", ".product_view", "#product_detail", ".xans-product-detail", "#content"],
    "prod.danawa.com": ["#productDescriptionArea", "#productDetail", ".prod_detail_area", "#danawa_product_info", "#product_detail"],
}

# 상품명 후보 선택자.
PRODUCT_NAME_SELECTORS = {
    "kr.misumi-ec.com": ["h1", ".fs-productDetailHeader-title"],
    "www.festo.com": ["h1"],
    "products.swagelok.com": ["h1"],
    "mall.industry.siemens.com": ["h1", ".product-title"],
    "*": ["h1", "[class*='product'][class*='name']", "[class*='product'][class*='title']"],
}

# 사이트별 쿠키 동의 완료 쿠키 (현재 비활성화 상태, 최후의 수단으로 보관 중)
# 클릭 기반 처리로 해결이 안 되는 사이트가 나오면 여기에 등록할 것
# 사이트 쿠키 이름은 브라우저 개발자도구 → Application → Cookies 에서 확인 가능
#
# 참고: Festo는 OneTrust가 아니라 Didomi를 사용하는 것으로 확인됨 (2026-08-05).
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


# ============================================================
# [NEW] 타이밍 설정 (기존에 crawler.py 안에 매직넘버로 박혀 있던 값들을
# 전부 여기로 옮겼다. 코드 수정 없이 여기 숫자만 바꿔서 튜닝 가능.)
# ============================================================

# 페이지 이동(goto) 최대 대기 시간
NAV_TIMEOUT_MS = 60000
# "load" 이벤트 대기 최대 시간 (실패해도 계속 진행)
LOAD_STATE_TIMEOUT_MS = 15000
# load 이후 "network idle" 상태를 최대 이 시간만큼 기다린다.
# 예전처럼 무조건 2초를 자는 대신, 네트워크가 먼저 조용해지면 그 즉시 다음 단계로 넘어가고
# 느린 사이트는 이 시간까지는 기다려준다 (평균적으로 더 빠르고, 느린 사이트엔 더 안전함).
NETWORK_SETTLE_TIMEOUT_MS = 4000

# 차단/보안확인 페이지 감지 시 본문 텍스트를 읽어오는 타임아웃
BLOCKED_CHECK_TIMEOUT_MS = 3000
# 수동 보안확인 대기 중 재확인 간격
CHALLENGE_POLL_INTERVAL_MS = 2000

# 쿠키 동의 배너 처리
CONSENT_MAX_BUTTONS = 5
CONSENT_VISIBLE_TIMEOUT_MS = 500
CONSENT_CLICK_TIMEOUT_MS = 2000
CONSENT_SETTLE_MS = 500

# "더보기" 등 상세정보 펼치기 버튼 처리
DETAIL_EXPAND_MAX_BUTTONS = 8
DETAIL_EXPAND_VISIBLE_TIMEOUT_MS = 300
DETAIL_EXPAND_CLICK_TIMEOUT_MS = 1500
DETAIL_EXPAND_SETTLE_MS = 500

# 지연 로딩(lazy-load) 콘텐츠를 깨우기 위한 스크롤
SCROLL_MAX_ATTEMPTS = 18
SCROLL_WAIT_MS = 600
SCROLL_STABLE_ROUNDS = 2  # 이 횟수만큼 연속으로 높이 변화가 없으면 스크롤 중단

# MISUMI 가격표처럼 스크롤 정지 후 XHR로 늦게 채워지는 표를 위한 재확인.
# 네트워크가 조용해졌다고 곧바로 렌더링까지 끝났다는 보장은 없으므로(특히 SPA),
# <table> 요소가 실제로 DOM에 붙을 때까지 최대 이 시간만큼 명시적으로 기다린다.
# 표가 원래 없거나 이미 있는 대다수 페이지는 이 대기를 타지 않아 속도 영향이 없다.
TABLE_WAIT_TIMEOUT_MS = 6000
# 위 대기로도 표가 안 나타나면, 스크롤을 다시 유도해 이 횟수만큼 더 재시도한다.
# (실측 결과 misumi 같은 무거운 SPA는 API 호출이 순차로 여러 번 이어져 최초 1~2회
# 재시도로는 부족한 경우가 있어 여유를 뒀다. 표가 이미 있는 페이지는 영향 없음.)
TABLE_RETRY_ATTEMPTS = 3

# DOM 텍스트/표 추출 타임아웃
TEXT_EXTRACT_TIMEOUT_MS = 5000

# 상품 본문 영역 판별
PRODUCT_REGION_VISIBLE_TIMEOUT_MS = 800
PRODUCT_REGION_MIN_WIDTH = 300
PRODUCT_REGION_MIN_HEIGHT = 150

# 개별 요소 스크린샷(OCR 에셋/상품 영역) 타임아웃
ELEMENT_SCREENSHOT_TIMEOUT_MS = 5000


# ============================================================
# [NEW] 리소스 차단 (속도 향상 + 트래픽/리소스 절감)
# 텍스트는 DOM에서 직접 읽고, 이미지는 OCR용으로만 필요하므로
# 화면 렌더링에 불필요한 리소스(동영상, 폰트, 광고/추적 스크립트)는 아예 받지 않는다.
# 이미지(image)와 스타일시트(stylesheet)는 레이아웃/스크린샷 품질에 필요하므로 차단하지 않는다.
# ============================================================
BLOCK_RESOURCE_TYPES = ["media", "font"]

# URL에 아래 키워드가 포함되면 요청 자체를 막는다 (도메인/경로 일부 매칭).
BLOCK_URL_KEYWORDS = [
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "googlesyndication.com",
    "facebook.com/tr",
    "connect.facebook.net",
    "hotjar.com",
    "criteo.com",
    "amazon-adsystem.com",
    "channel.io",
    "channel.talk",
    "mixpanel.com",
    "adsystem",
]


# ============================================================
# [NEW] 이미지 전처리 (색 보정) — OCR 정확도 개선용
# OCR 대상 이미지(캡처 에셋, 상품 본문 스크린샷)에 대해
# 저해상도 업스케일 + 명암 자동 보정 + 선명도 보정을 적용한다.
# Pillow만 사용해 가볍게 처리한다 (OpenCV 등 무거운 의존성 추가 없음).
# ============================================================
ENABLE_IMAGE_PREPROCESS = True

# 이미지 폭이 이 값보다 작으면 이 값에 맞춰 업스케일한다 (너무 작은 글자 대응).
IMAGE_UPSCALE_MIN_WIDTH = 700
# 업스케일 배율 상한 (지나친 확대로 인한 용량/시간 낭비 방지)
IMAGE_UPSCALE_MAX_SCALE = 3.0

# 명암 자동 보정 시 상/하위 몇 %를 잘라낼지 (PIL ImageOps.autocontrast의 cutoff)
IMAGE_AUTOCONTRAST_CUTOFF = 1
# 대비/선명도 보정 배율 (1.0 = 원본 그대로)
IMAGE_CONTRAST_FACTOR = 1.15
IMAGE_SHARPNESS_FACTOR = 1.6


def load_target_urls():
    """urls.txt 파일에서 캡처 대상 URL 목록을 읽는다."""
    if not os.path.exists(URLS_FILE):
        return []
    with open(URLS_FILE, encoding="utf-8") as handle:
        return [
            line.strip()
            for line in handle
            if line.strip() and not line.strip().startswith("#")
        ]


TARGET_URLS = load_target_urls()
