import os

_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(_DIR)  # 루트 (crawler.py에서 BASE_DIR 참조용)

BROWSER_PROFILE_DIR = os.path.join(_DIR, "chrome_profiles", "product_capture")

# 캡처 대상 URL 목록 파일. 코드 수정 없이 이 파일만 편집하면 대상이 바뀐다.
URLS_FILE = os.path.join(_DIR, "urls.txt")

# 브라우저 표시 여부 (False: 화면 표시, True: 백그라운드 실행)
HEADLESS = False

# 보안 확인 화면이 나타났을 때 열린 Chrome에서 사용자가 정상 확인을 마칠 최대 시간.
MANUAL_CHALLENGE_WAIT_SECONDS = 20

# Playwright 브라우저 기본 뷰포트 크기
DEFAULT_VIEWPORT = {"width": 1500, "height": 1000}

# ── 브라우저 실행 옵션 ───────────────────────────────────────────────────────
# 실제 설치된 Chrome을 사용(번들 Chromium 대비 봇 탐지에 덜 걸림). launch_persistent_context에
# 그대로 전달되므로 여기 값만 바꾸면 crawler.py 수정 없이 로케일/타임존/실행 인자를 조정할 수 있다.
BROWSER_CHANNEL = "chrome"
BROWSER_LOCALE = "ko-KR"
BROWSER_TIMEZONE = "Asia/Seoul"
BROWSER_LAUNCH_ARGS = ["--start-maximized"]

# ── 페이지 로딩/대기 타이밍 ───────────────────────────────────────────────────
PAGE_GOTO_TIMEOUT_MS = 60000
WARMUP_GOTO_TIMEOUT_MS = 45000
PAGE_LOAD_STATE_TIMEOUT_MS = 20000
# 페이지 로드 직후의 "본문이 준비됐는지" 대기는 더 이상 이 고정값을 쓰지 않고
# 아래 CONTENT_READY_* 값으로 폴링한다(빠른 사이트는 일찍 넘어가고, 느린 사이트는
# 예산 안에서 필요한 만큼만 기다림). 이 상수 자체는 여전히 쓰인다 — warm_up()의
# 홈페이지 방문 후 고정 대기, wait_for_manual_challenge()의 재확인 간격.
POST_LOAD_WAIT_MS = 2000
BLOCKED_CHECK_TIMEOUT_MS = 3000
BLOCKED_TEXT_SAMPLE_CHARS = 1500
CONSENT_BUTTON_CLICK_TIMEOUT_MS = 2000
CONSENT_BUTTON_MAX_CANDIDATES = 5
CONSENT_VISIBLE_TIMEOUT_MS = 500
CONSENT_POST_CLICK_WAIT_MS = 500
EXPAND_BUTTON_MAX_CANDIDATES = 8
EXPAND_BUTTON_CLICK_TIMEOUT_MS = 1500
EXPAND_VISIBLE_TIMEOUT_MS = 300
EXPAND_POST_CLICK_WAIT_MS = 500
INNER_TEXT_TIMEOUT_MS = 5000
WAKE_LAZY_MAX_ROUNDS = 18
WAKE_LAZY_STABLE_ROUNDS = 3
# 스크롤 한 번당 대기 시간. 800ms -> 500ms로 낮춰도 STABLE_ROUNDS(연속 3회 높이
# 불변)로 안정성을 판단하므로 완결성은 그대로 유지되면서 페이지당 최대 수 초가
# 절약된다(느린 지연로딩 사이트는 어차피 안정될 때까지 라운드가 늘어나 자동으로
# 더 기다리게 된다).
WAKE_LAZY_WAIT_MS = 500
WAKE_LAZY_NETWORK_IDLE_TIMEOUT_MS = 5000
PRODUCT_REGION_VISIBLE_TIMEOUT_MS = 800
PRODUCT_REGION_PROBE_TIMEOUT_MS = 250
PRODUCT_REGION_MIN_WIDTH = 300
PRODUCT_REGION_MIN_HEIGHT = 150
# product.png 후보의 세로 길이가 "현재 뷰포트 높이 x 이 배수"를 넘으면 그 후보는
# 버린다. 특정 사이트를 이름으로 예외 처리하는 대신 일반적인 기준 하나로 처리한다:
# 상품 상세 "영역"이 아니라 메뉴/푸터/연관상품까지 포함한 "페이지 전체"를 골라버린
# 경우(예: Swagelok의 <main>이 15000px 넘게 늘어나던 사례)를 걸러내기 위함이다.
PRODUCT_REGION_MAX_VIEWPORT_MULTIPLE = 4

# ── 본문 로딩 확인 / 빈 캡처 감지 ────────────────────────────────────────────
# 차단 문구(BLOCKED_PATTERN)는 안 뜨지만 본문이 사실상 비어 있는 경우(예: SPA가
# 늦게 그려지거나 WAF가 빈 응답만 준 경우)를 "captured"로 잘못 표시하지 않기 위한
# 값들. is_blocked()와는 별개로, 캡처된 본문 글자 수가 이 값 미만이면 상태를
# "empty"로 표시하고 실패 스크린샷을 남긴다.
MIN_VALID_CONTENT_CHARS = 200
# 본문이 안정될 때까지 짧은 간격으로 폴링한다(고정 sleep 대신). 길이가 더
# 늘지 않는 상태가 이 횟수만큼 연속되면 더 기다리지 않고 다음 단계로 넘어간다.
CONTENT_READY_POLL_MS = 300
CONTENT_READY_STABLE_ROUNDS = 2
CONTENT_READY_MAX_WAIT_MS = 4000
# 1차 확인에서 본문이 MIN_VALID_CONTENT_CHARS 미만이면, 느린 SPA일 가능성을 감안해
# 이 예산만큼 한 번 더(네트워크 idle 대기 + 폴링) 기회를 준다. 대부분의 사이트는
# 이 경로를 타지 않으므로 전체 평균 소요 시간에는 영향이 없다.
EMPTY_CONTENT_RETRY_WAIT_MS = 6000

# ── 이미지 전처리 (image_preprocess.py) ─────────────────────────────────────
OCR_PREPROCESS_ENABLED = True
OCR_PREPROCESS_MIN_DIMENSION = 400
OCR_PREPROCESS_MAX_UPSCALE_FACTOR = 3.0
OCR_PREPROCESS_MAX_DIMENSION = 3000
OCR_PREPROCESS_AUTOCONTRAST_CUTOFF = 1
# 채널별 명암 범위가 이미 이 값(0~255 기준) 이상이면 autocontrast를 건너뛴다.
# 이미 대비가 충분한 스크린샷을 또 늘리면 과보정으로 색이 뜨거나 글자 경계가
# 뭉개질 수 있고, 불필요한 연산도 아낄 수 있다(품질 + 속도 동시 개선).
OCR_PREPROCESS_SKIP_CONTRAST_IF_RANGE_GTE = 200
OCR_PREPROCESS_SHARPEN_RADIUS = 1.5
OCR_PREPROCESS_SHARPEN_PERCENT = 120
OCR_PREPROCESS_SHARPEN_THRESHOLD = 3
# PNG 압축 레벨(0~9). 기본값(6)보다 낮추면 화질 손실 없이(PNG는 무손실) 저장
# 속도만 빨라진다 — 이 이미지들은 최종 산출물이 아니라 OCR 입력이라 용량보다
# 속도가 더 중요하다.
OCR_PREPROCESS_PNG_COMPRESS_LEVEL = 3

# ── 텍스트 필터링 (text_filter.py) ──────────────────────────────────────────
# 상품명/모델번호/사이즈/사양은 한글·영문·숫자(+기호)로 이뤄지므로, 캡처된
# DOM/표 텍스트에서 일본어(히라가나/가타카나)와 한자를 걸러내 이후 추출
# 단계(LLM/규칙 기반)의 잡음을 줄인다.
# 주의: 한자(U+4E00–U+9FFF)는 한/중/일 표기가 코드값을 공유해 "중국어만"
# 골라낼 수는 없다 — 한자 전체를 걸러내며, 한국 문서에 드물게 병기되는
# 한자까지 같이 제거될 수 있음을 감안한 실용적 선택이다.
FILTER_NON_KOREAN_SCRIPTS = True
# 한 줄에서 필터 대상 문자 비율이 이 값 이상이면 그 줄 전체를 버린다
# (예: 다국어 사이트의 언어선택 메뉴 "日本語 / 中文" 같은 줄). 너무 낮게
# 잡으면 "규격 32mm ネジ穴付き"처럼 유효한 한글·숫자 정보가 섞인 줄까지
# 통째로 날아가므로, 사실상 그 줄 전체가 외국어인 경우만 버리도록 높게 잡는다.
FILTER_LINE_DROP_RATIO = 0.7

# 상세 URL 직접 접근을 경계하는 사이트는 먼저 홈페이지에서 정상 세션을 만든다.
# festo.com은 2026-08-15 캡처에서 차단 문구 없이 본문이 통째로 비어 오는 사례가
# 확인됐다(WAF가 세션 없는 딥링크 접근에 빈 응답을 준 것으로 추정) — 다른 사이트와
# 같은 방식으로 홈페이지를 먼저 들러 정상 세션을 만들어두면 재현 빈도를 줄일 수 있다.
WARMUP_URLS = {
    "itempage3.auction.co.kr": "https://www.auction.co.kr/",
    "www.festo.com": "https://www.festo.com/kr/ko/",
}

# 하이브리드 추출: DOM에 없는 글자를 읽기 위해 큰 이미지/Canvas만 별도 OCR한다.
MAX_OCR_ASSETS_PER_PAGE = 60
MIN_OCR_ASSET_WIDTH = 250
MIN_OCR_ASSET_HEIGHT = 80

# 상품 영역 스크린샷(product.png)에 딸린 DOM 텍스트(product_dom.txt)가 이 글자 수
# 이상이면 이미 텍스트를 충분히 확보했다고 보고 product.png의 OCR을 생략한다.
# 실제로 이 값을 읽는 곳은 paddle_ocr.py(ocr/ 폴더)인데, crawl/와 ocr/는
# 폴더별로 각자의 config.py를 따로 보므로(각 폴더가 sys.path에서 자기
# 자신을 먼저 삽입) 이 값을 여기 crawl/config.py에 적어둬도 ocr/config.py엔
# 반영되지 않는다. OCR 담당자(ocr/config.py)에게도 같은 값을 전달해야
# 실제로 동작한다 — 크롤링 쪽은 참고용으로만 갖고 있는다.
OCR_PRODUCT_SCREENSHOT_MIN_DOM_CHARS = 300

# 상품 본문 후보 선택자. 앞의 선택자부터 시도하고, 모두 실패하면 전체 화면을 OCR한다.
# 각 후보는 실제 사이트를 열어 후보 요소의 bounding box를 확인하고 등록한 값이다
# (products.swagelok.com: 2026-08-15, h1의 상위 요소를 따라 올라가며 확인 —
#  main은 관련상품/푸터까지 포함해 5000~15000px까지 늘어나 부적합했고,
#  .s-pdp__product가 제목+스펙표+이미지를 딱 감싸는 실제 상품 영역이었다).
# 등록된 선택자가 모두 실패해도 PRODUCT_REGION_MAX_VIEWPORT_MULTIPLE 기준으로
# "사실상 페이지 전체"인 후보는 capture_product_region()에서 한 번 더 걸러진다.
PRODUCT_REGION_SELECTORS = {
    "www.festo.com": ["main", "[data-testid='product-detail']", "#main-content"],
    "mall.industry.siemens.com": ["main", "#content", ".product-detail"],
    "kr.misumi-ec.com": ["main", "#product-detail", ".product-detail"],
    "products.swagelok.com": [".s-pdp__product", ".s-pdp__details", "main", "#main-content", ".product-detail"],
    "item.gmarket.co.kr": ["#container", "#itemcase_basic", "main"],
    "itempage3.auction.co.kr": ["#container", "#itemcase_basic", "main"],
    # 2026-08-17 확인: navimro는 "main" 태그 자체가 없어(host 미등록 시 폴백값)
    # product_screenshot이 항상 null이었다. h1(#product-detail-title)에서
    # 상위로 올라가며 확인한 결과 .product-spec(1250x547)이 제목+스펙표+요약을
    # 딱 감싸는 실제 상품 영역이었다.
    "www.navimro.com": [".product-spec", ".spec-sum", "main"],
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
