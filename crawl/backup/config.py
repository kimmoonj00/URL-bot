import os

_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_DIR)  # 루트

BROWSER_PROFILE_DIR = os.path.join(_DIR, "chrome_profiles", "product_capture")

# 캡처 대상 URL 목록 파일. 코드 수정 없이 이 파일만 편집하면 대상이 바뀐다.
URLS_FILE = os.path.join(_DIR, "urls.txt")

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
