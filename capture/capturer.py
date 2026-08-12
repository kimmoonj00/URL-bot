"""상품 URL을 열어 페이지 전체를 스크린샷으로 캡쳐하고 저장하는 로직.

OCR/파싱 로직과는 완전히 분리되어 있으며, 이 모듈의 결과물은
디스크에 저장된 이미지 파일(및 메타데이터)뿐이다.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import urlparse

from playwright.sync_api import Page, sync_playwright

# 로그인 상태가 필요하거나 봇 탐지가 특히 공격적인 사이트. 매번 새로 뜨는
# 임시 브라우저 대신 로그인 세션이 남아있는 실제 Chrome 프로필을 재사용하고,
# 요청 간격도 랜덤하게 둬서 반복 요청 패턴으로 탐지되는 것을 피한다.
BOT_SENSITIVE_DOMAINS = ["coupang.com", "naver.com"]
CHROME_PROFILE_PATH = str(Path(__file__).resolve().parent.parent / "output" / "chrome-profile")

# 쿠키 동의를 이미 완료한 것처럼 위장해 배너 자체를 억제하는 사전 주입 쿠키
CONSENT_COOKIES = [
    {"name": "cookieconsent_status", "value": "dismiss"},
    {"name": "cookie_consent", "value": "1"},
    {"name": "cookies_accepted", "value": "true"},
    {"name": "CookieConsent", "value": "true"},
]

# 네트워크 레벨에서 차단할 CMP(쿠키 동의 플랫폼) 스크립트 도메인/패턴
CMP_BLOCK_PATTERNS = [
    "cookiebot.com",
    "cookieconsent",
    "onetrust.com",
    "otSDKStub",
    "usercentrics",
    "trustarc.com",
    "cookielaw.org",
    "privacymanager.io",
    "consensu.org",
]

CONSENT_BUTTON_TEXTS = [
    "동의", "전체 동의", "모두 동의", "허용", "확인", "동의합니다",
    "Accept All", "Accept", "I Agree", "OK", "Got it",
]

CONSENT_BUTTON_PATTERN = re.compile(
    r"accept all|accept|allow all|allow|agree|i agree|dismiss|got it|"
    r"동의\s*후|모두\s*수락|수락|모두\s*동의|동의|허용",
    re.IGNORECASE,
)

# 접힌 상세정보/설명을 펼치는 "더보기" 류 버튼 문구
EXPAND_TEXTS = [
    "더보기", "더 보기", "상세정보 더보기", "상세 보기", "펼쳐보기", "펼치기",
    "전체보기", "전체 보기",
    "View More", "Show More", "Details", "Read More", "Expand",
]

# 로딩 스피너/스켈레톤 UI가 사라질 때까지 대기할 때 쓰는 선택자
SPINNER_SELECTORS = ["[class*='spinner']", "[class*='loading']", "[class*='skeleton']"]

# 페이지 본문에서 발견되면 접속 차단/봇 탐지로 판단하는 키워드
BLOCKED_KEYWORDS = [
    "보안", "로봇이 아닙니다", "captcha", "CAPTCHA", "access denied",
    "일시적으로", "차단", "verify you are human", "unusual traffic",
    "서비스 이용이 불가능",
]

# 동의 버튼 클릭이 실패했을 때의 CSS 강제숨김 폴백.
# 클래스/id에 키워드가 있다고 무조건 지우면 실제 상품 콘텐츠까지 오탐으로
# 지울 수 있어, fixed/sticky 배치이거나 z-index가 높으면서 화면에 실제로
# 보이는 크기가 있는 요소만 골라 숨긴다.
POPUP_KILLER_SCRIPT = """
    (function() {
        const keywords = [
            'cookie', 'consent', 'gdpr', 'popup', 'banner', 'overlay',
            'modal', 'notice', 'onetrust', 'cookiebot', 'trustarcbar',
            'cc-window', 'privacy-banner', 'cookie-law', 'cookie-notice',
            'floating', 'layer'
        ];
        const selectors = keywords.flatMap(k => [`[class*="${k}"]`, `[id*="${k}"]`]).join(', ');

        document.querySelectorAll(selectors).forEach(el => {
            const style = window.getComputedStyle(el);
            const zIndex = parseInt(style.zIndex) || 0;
            const rect = el.getBoundingClientRect();
            if ((style.position === 'fixed' || style.position === 'sticky' || zIndex > 100)
                && rect.width > 0 && rect.height > 0) {
                el.style.setProperty('display', 'none', 'important');
            }
        });

        document.body.style.setProperty('overflow', 'auto', 'important');
        document.documentElement.style.setProperty('overflow', 'auto', 'important');
    })()
"""

# 스크린샷 직전, 화면에 고정된(fixed/sticky) 헤더·배너가 캡쳐를 가리지 않도록 숨긴다.
HIDE_STICKY_SCRIPT = """
    (function() {
        document.querySelectorAll('*').forEach(el => {
            const style = window.getComputedStyle(el);
            if (style.position === 'fixed' || style.position === 'sticky') {
                el.style.setProperty('display', 'none', 'important');
            }
        });
    })()
"""


@dataclass
class CaptureResult:
    url: str
    image_path: Path
    title: str
    captured_at: str
    ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["image_path"] = str(self.image_path)
        return d


def _slugify(text: str, max_len: int = 40) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "_", text).strip("_")
    return text[:max_len] or "capture"


def _block_cmp_scripts(page: Page) -> None:
    """CMP(쿠키 동의 플랫폼) 스크립트를 네트워크 레벨에서 차단해 팝업을 원천 억제한다."""

    def handle_route(route):
        if any(pattern in route.request.url for pattern in CMP_BLOCK_PATTERNS):
            route.abort()
        else:
            route.continue_()

    page.route("**/*", handle_route)


def _inject_consent_cookies(page: Page, domain: str) -> None:
    """쿠키 동의를 이미 완료한 것처럼 위장하는 쿠키를 페이지 로드 전에 심어둔다."""
    try:
        page.context.add_cookies(
            [{**cookie, "domain": domain, "path": "/"} for cookie in CONSENT_COOKIES]
        )
    except Exception:
        pass


def _dismiss_consent_popup(page: Page) -> bool:
    """쿠키 동의 배너의 '수락' 버튼을 찾아 클릭한다.

    배너/다이얼로그 컨테이너 안에서 우선 찾고, 못 찾으면 메인 프레임과 모든
    iframe 전체에서 동의 버튼 문구를 직접 찾아 클릭한다 (컨테이너 클래스명이
    특이한 사이트 대응). 성공하면 True를 반환한다.
    """
    try:
        banner = page.locator(
            '[class*="cookie"], [id*="cookie"], [class*="consent"], [id*="consent"], '
            '[class*="gdpr"], [id*="gdpr"], [id*="onetrust"], [class*="onetrust"], '
            '[id*="cookiebot"], [class*="cookiebot"]'
        ).first
        if banner.is_visible(timeout=2000):
            btn = banner.locator('button, a, [role="button"]').filter(
                has_text=CONSENT_BUTTON_PATTERN
            ).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                return True
    except Exception:
        pass

    try:
        dialog = page.locator('[role="dialog"], [role="alertdialog"]').first
        if dialog.is_visible(timeout=1000):
            btn = dialog.locator('button, a, [role="button"]').filter(
                has_text=CONSENT_BUTTON_PATTERN
            ).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                return True
    except Exception:
        pass

    for frame in [page, *page.frames]:
        for text in CONSENT_BUTTON_TEXTS:
            try:
                btn = frame.get_by_role("button", name=text, exact=False).first
                if btn.is_visible(timeout=500):
                    btn.click(timeout=1000, force=True)
                    return True
            except Exception:
                continue

    return False


def _remove_popups(page: Page) -> None:
    """동의 버튼 클릭을 우선 시도하고, 실패하면 CSS로 강제 숨긴다."""
    if _dismiss_consent_popup(page):
        return
    try:
        page.evaluate(POPUP_KILLER_SCRIPT)
    except Exception:
        # 페이지 구조와 맞지 않아도 캡쳐 자체는 계속 진행한다
        pass


def _expand_detail_sections(page: Page) -> int:
    """접힌 상세정보/설명을 펼치는 '더보기' 류 버튼을 찾아 클릭한다.

    "더보기"는 콘텐츠를 펼치는 버튼뿐 아니라 카테고리 전체보기처럼 다른
    페이지로 이동하는 링크에도 흔히 쓰이는 문구다 (실제로 navimro에서
    상품 상세페이지 대신 카테고리 목록 페이지로 이동해버린 사례가 있었다).
    실제 경로를 가리키는 <a href="..."> 링크는 건너뛰고, 혹시 클릭으로
    페이지 이동이 발생하면 즉시 뒤로 가서 원복한다.
    """
    current_url = page.url
    clicked = 0
    for text in EXPAND_TEXTS:
        try:
            buttons = page.get_by_text(text, exact=False).all()
        except Exception:
            continue
        for btn in buttons:
            try:
                if not btn.is_visible(timeout=500):
                    continue
                href = btn.get_attribute("href")
                if href and href not in ("#", "") and not href.startswith("javascript:"):
                    continue
                btn.click(timeout=800)
                page.wait_for_timeout(300)
                if page.url != current_url:
                    page.go_back(timeout=5000)
                    page.wait_for_timeout(500)
                    continue
                clicked += 1
            except Exception:
                continue
    return clicked


def _hide_sticky_elements(page: Page) -> None:
    """스크린샷 직전, 화면에 고정된 헤더/배너가 캡쳐를 가리지 않도록 숨긴다."""
    try:
        page.evaluate(HIDE_STICKY_SCRIPT)
    except Exception:
        pass


def _wait_for_page_fully_loaded(page: Page, max_wait_sec: int = 15) -> None:
    """load 이벤트 -> networkidle -> 로딩 스피너/스켈레톤 사라짐 순으로 기다린다.

    goto()는 domcontentloaded까지만 기다리고 넘어오므로(=DOM 파싱만 끝난
    시점), 이미지/스크립트 등 리소스까지 다 받은 load 이벤트를 한 번 더
    기다려 SPA가 데이터를 그릴 시간을 벌어준다. SPA(React 등)는 networkidle에
    도달해도 데이터가 화면에 그려지기 전일 수 있다 (예: MISUMI가 렌더링 완료
    전에 캡쳐되어 빈 화면으로 저장된 사례). 스피너/스켈레톤 UI가 사라질
    때까지 한 번 더 기다려 이를 보완한다. 각 단계는 실패해도 캡쳐 자체를
    중단시키지 않는다 (navimro처럼 백그라운드 요청이 끝없이 이어지는 페이지
    대응).
    """
    try:
        page.wait_for_load_state("load", timeout=max_wait_sec * 1000)
    except Exception:
        print("    [경고] load 이벤트 타임아웃, 계속 진행")

    try:
        page.wait_for_load_state("networkidle", timeout=max_wait_sec * 1000)
    except Exception:
        # 추천상품/트래킹 등 백그라운드 요청이 계속 이어져 networkidle에
        # 끝내 도달하지 못하는 페이지가 있다. 캡쳐를 중단하지 않고 진행한다.
        print("    [경고] networkidle 타임아웃, 대체 대기 방식으로 진행")

    for selector in SPINNER_SELECTORS:
        try:
            page.wait_for_selector(selector, state="hidden", timeout=3000)
        except Exception:
            pass

    page.wait_for_timeout(1000)


def _check_blocked(page: Page) -> List[str]:
    """페이지 본문에서 접속 차단/봇 탐지 관련 키워드를 찾아 반환한다."""
    try:
        body_text = page.inner_text("body")[:1000]
    except Exception:
        return []
    return [kw for kw in BLOCKED_KEYWORDS if kw in body_text]


def _autoscroll(page: Page, steps: int = 4, dwell_ms: int = 2000) -> None:
    """문서 높이의 1/steps 지점씩 내려가며 각 지점에서 충분히 대기한 뒤
    맨 위로 복귀한다.

    고정 픽셀 단위로 빠르게 훑고 "스크롤이 더 안 내려가면 중단"하는 방식은,
    스크롤해도 문서 높이 자체는 그대로인 채 그 자리에서 비동기로 콘텐츠만
    채워지는 SPA(예: MISUMI)에서 렌더링이 끝나기도 전에 멈춰버리는 문제가
    있었다. 구간마다 고정 시간을 대기하면 이런 지연 렌더링에도 안전하다.
    """
    for i in range(1, steps + 1):
        page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * ({i}/{steps}))")
        page.wait_for_timeout(dwell_ms)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(1000)


def _open_browser(p, domain: str, scale: float):
    """도메인에 맞는 브라우저/페이지를 준비해 (닫아야 할 객체, page)를 반환한다.

    headless + Playwright 번들 Chromium 조합은 Akamai 등 봇 탐지 시스템에
    쉽게 걸린다 (navigator.webdriver, headless 전용 렌더링 특성 등으로 식별
    가능). headless=False + 실제 설치된 Chrome(channel="chrome")을 쓰면 "진짜
    사용자" fingerprint에 가까워져 차단을 피할 수 있다.

    쿠팡/네이버처럼 봇 탐지가 특히 공격적이거나 로그인 상태가 필요한 사이트는
    로그인 세션이 남아있는 실제 Chrome 프로필을 재사용하는
    launch_persistent_context로 열고 요청 전 랜덤하게 대기한다.
    """
    is_sensitive = any(sensitive in domain for sensitive in BOT_SENSITIVE_DOMAINS)

    if is_sensitive:
        wait_time = random.uniform(8, 15)
        print(f"    [대기] 민감 사이트 - 랜덤 지연 {wait_time:.1f}초")
        time.sleep(wait_time)
        context = p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_PATH,
            headless=False,
            channel="chrome",
            viewport={"width": 1440, "height": 900},
            device_scale_factor=scale,
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        return context, page

    browser = p.chromium.launch(
        headless=False,
        channel="chrome",
        args=["--window-position=0,0", "--start-maximized"],
    )
    # no_viewport(실제 창 크기 사용)는 device_scale_factor와 함께 쓸 수 없어서
    # (Playwright 제약) 고정 뷰포트를 유지한다. OCR 인식률을 위한 2배 스케일은
    # 이 방식으로만 보장된다.
    page = browser.new_page(
        viewport={"width": 1440, "height": 900},
        device_scale_factor=scale,
    )
    return browser, page


def capture_url(
    url: str,
    output_dir: Path,
    scale: float = 2.0,
    timeout_ms: int = 30000,
) -> CaptureResult:
    """URL 하나를 열어 전체 페이지를 캡쳐하고 이미지+메타데이터를 저장한다."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    captured_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    domain = urlparse(url).hostname or ""

    t_start = time.perf_counter()
    try:
        with sync_playwright() as p:
            t0 = time.perf_counter()
            closeable, page = _open_browser(p, domain, scale)
            _block_cmp_scripts(page)
            _inject_consent_cookies(page, domain)
            t1 = time.perf_counter()
            print(f"    [타이밍] 브라우저 실행: {t1 - t0:.1f}초")

            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            _wait_for_page_fully_loaded(page, max_wait_sec=timeout_ms // 1000)
            title = page.title()
            t2 = time.perf_counter()
            print(f"    [타이밍] 페이지 로드: {t2 - t1:.1f}초")

            blocked_keywords = _check_blocked(page)
            if blocked_keywords:
                debug_path = output_dir / f"DEBUG_{_slugify(domain)}_{captured_at}.png"
                page.screenshot(path=str(debug_path), full_page=False)
                closeable.close()
                raise RuntimeError(
                    f"차단/봇탐지 의심 키워드 발견: {blocked_keywords} (진단용 캡쳐: {debug_path})"
                )

            _autoscroll(page)
            t3 = time.perf_counter()
            print(f"    [타이밍] 오토스크롤: {t3 - t2:.1f}초")

            _remove_popups(page)
            expanded = _expand_detail_sections(page)
            if expanded:
                print(f"    [상세정보] '더보기' 버튼 {expanded}개 클릭")
            page.wait_for_timeout(500)
            t4 = time.perf_counter()
            print(f"    [타이밍] 팝업 제거: {t4 - t3:.1f}초")

            # 스크롤 중 뒤늦게 나타난 팝업 재처리 (일부 사이트는 로드 후 몇 초
            # 뒤에 가입 유도/이벤트 팝업을 띄운다)
            _remove_popups(page)
            _hide_sticky_elements(page)
            filename = f"{_slugify(title)}_{captured_at}.png"
            image_path = output_dir / filename
            page.screenshot(path=str(image_path), full_page=True)
            t5 = time.perf_counter()
            print(f"    [타이밍] 스크린샷 저장: {t5 - t4:.1f}초")

            closeable.close()

        print(f"    [타이밍] 총 소요시간: {time.perf_counter() - t_start:.1f}초")
        result = CaptureResult(
            url=url, image_path=image_path, title=title, captured_at=captured_at
        )
    except Exception as exc:  # 개별 URL 실패가 전체 배치를 중단시키지 않도록 함
        result = CaptureResult(
            url=url,
            image_path=Path(""),
            title="",
            captured_at=captured_at,
            ok=False,
            error=str(exc),
        )

    _write_metadata(output_dir, result)
    return result


def capture_urls(urls: List[str], output_dir: Path, scale: float = 2.0) -> List[CaptureResult]:
    """여러 URL을 순차적으로 캡쳐한다."""
    return [capture_url(url, output_dir, scale=scale) for url in urls]


def _write_metadata(output_dir: Path, result: CaptureResult) -> None:
    meta_path = output_dir / "captures.jsonl"
    with meta_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
