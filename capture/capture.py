from playwright.sync_api import sync_playwright
# from PIL import Image  # [방법2 - 비활성화] 재활성화 시 주석 해제 (구간 캡처 이어붙이기용)
# import io               # [방법2 - 비활성화] 재활성화 시 주석 해제
import re
import time
import os
from datetime import datetime
from urllib.parse import urlparse

from config import TARGET_URLS, EXCLUDE_DOMAINS, HEADLESS
# SITE_COOKIES는 현재 비활성화 상태 (아래 [레이어 3 - 비활성화] 참고)

# 뷰포트 확장 방식(방법1)의 안전 한계. 문서 높이가 이보다 크면 Chromium 텍스처 크기
# 제한에 걸릴 수 있음. 원래는 이 경우 구간 캡처 방식(방법2)으로 전환했으나 현재 비활성화 상태
MAX_VIEWPORT_HEIGHT = 15000
DEFAULT_VIEWPORT = {"width": 1500, "height": 1000}

# [레이어 1 - 비활성화] TCF/CMP API 스푸핑
# 2026-08-05 테스트 결과 실제 효과 확인 안 됨 (Festo의 Didomi 팝업도 이 레이어가 아닌
# 버튼 클릭으로 닫혔음) → 우선 비활성화, 필요한 사이트가 생기면 재활성화
# 재활성화 방법: 아래 주석 해제 + context.add_init_script(INIT_SCRIPT) 호출부 주석 해제
#
# INIT_SCRIPT = """
#     try {
#         Object.defineProperty(window, '__tcfapi', {
#             value: (cmd, ver, cb) => cb({ gdprApplies: false, cmpStatus: 'loaded', eventStatus: 'tcloaded' }, true),
#             writable: false, configurable: false
#         });
#     } catch(e) {}
#     try {
#         Object.defineProperty(window, '__cmp', {
#             value: (cmd, param, cb) => { if (cb) cb(null, true); },
#             writable: false, configurable: false
#         });
#     } catch(e) {}
# """

# [전략 3-폴백] 동의 버튼 클릭 실패 시 CSS로 강제 숨김 + overflow 복구
POPUP_KILLER_SCRIPT = """
    (function() {
        const keywords = [
            'cookie', 'consent', 'gdpr', 'popup', 'banner', 'overlay',
            'modal', 'notice', 'onetrust', 'cookiebot', 'trustarcbar',
            'cc-window', 'privacy-banner', 'cookie-law', 'cookie-notice'
        ];
        const selectors = keywords.flatMap(k => [
            `[class*="${k}"]`, `[id*="${k}"]`
        ]).join(', ');

        let removed = 0;
        document.querySelectorAll(selectors).forEach(el => {
            const style = window.getComputedStyle(el);
            const pos = style.position;
            const zIndex = parseInt(style.zIndex) || 0;
            const rect = el.getBoundingClientRect();
            // 실제 눈에 보이는 팝업 오버레이만 숨김:
            // fixed/sticky 포지션이거나 z-index > 100 이면서, 실제 크기가 있는 경우만
            // (옥션의 #PDPLayer처럼 0x0 크기의 빈 플레이스홀더는 오탐이므로 제외)
            if ((pos === 'fixed' || pos === 'sticky' || zIndex > 100) && rect.width > 0 && rect.height > 0) {
                el.style.setProperty('display', 'none', 'important');
                removed++;
            }
        });

        // 팝업이 body 스크롤을 막고 있는 경우 복구
        document.body.style.setProperty('overflow', 'auto', 'important');
        document.documentElement.style.setProperty('overflow', 'auto', 'important');

        return removed;
    })()
"""

# 캡처 직전 모든 img 태그의 로드 완료 여부 확인
IMAGES_LOADED_SCRIPT = "() => Array.from(document.images).every(img => img.complete)"

# 네트워크 레벨에서 차단할 CMP(쿠키 동의 플랫폼) 스크립트 패턴
CMP_BLOCK_PATTERNS = [
    'cookiebot.com',
    'cookieconsent',
    'onetrust.com',
    'otSDKStub',
    'usercentrics',
    'trustarc.com',
    'cookielaw.org',
    'privacymanager.io',
    'consensu.org',
    'quantcast.mgr',
]


def block_cmp_scripts(page):
    """CMP/쿠키 동의 스크립트를 네트워크 레벨에서 차단 (팝업 원천 차단)"""
    def handle_route(route):
        if any(pattern in route.request.url for pattern in CMP_BLOCK_PATTERNS):
            route.abort()
        else:
            route.continue_()
    page.route('**/*', handle_route)


def dismiss_consent_popup(page):
    """쿠키 팝업 동의 버튼 클릭 (2단계 탐색)"""
    consent_btn_pattern = re.compile(
        r'accept all|accept|allow all|allow|agree|i agree|dismiss|got it|'
        r'동의\s*후|모두\s*수락|수락|모두\s*동의|동의|허용',
        re.IGNORECASE
    )

    # 1차: class/id에 쿠키 키워드가 있는 배너 컨테이너 안에서 탐색
    try:
        banner = page.locator(
            '[class*="cookie"], [id*="cookie"], [class*="consent"], [id*="consent"], '
            '[class*="gdpr"], [id*="gdpr"], [id*="onetrust"], [class*="onetrust"], '
            '[id*="cookiebot"], [class*="cookiebot"]'
        ).first
        if banner.is_visible(timeout=2000):
            btn = banner.locator('button, a, [role="button"]').filter(
                has_text=consent_btn_pattern
            ).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                time.sleep(0.8)
                return True
    except Exception:
        pass

    # 2차: role="dialog" 기반 탐색 (Festo처럼 class/id에 쿠키 키워드 없는 커스텀 팝업 대응)
    try:
        dialog = page.locator('[role="dialog"], [role="alertdialog"]').first
        if dialog.is_visible(timeout=1000):
            btn = dialog.locator('button, a, [role="button"]').filter(
                has_text=consent_btn_pattern
            ).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=2000)
                time.sleep(0.8)
                return True
    except Exception:
        pass

    return False


# "더보기" 류 버튼 텍스트 패턴 (한/영, 옥션뿐 아니라 다른 사이트에도 재사용 가능하도록 범용화)
# 구체적인 문구를 먼저, 범용적인 "더보기"/"more"는 뒤에 두어 우선순위를 둠
MORE_DETAILS_PATTERN = re.compile(
    r'상세\s*(정보|설명)\s*더\s*보기|상품\s*정보\s*더\s*보기|제품\s*정보\s*더\s*보기|'
    r'자세히\s*보기|전체\s*보기|펼쳐\s*보기|더\s*보기|더보기|'
    r'view\s*more|read\s*more|show\s*more|see\s*more|more\s*details?|learn\s*more',
    re.IGNORECASE
)


def expand_more_details(page):
    """상세정보/설명을 펼치는 '더보기' 류 버튼을 찾아 클릭 (사이트 무관 재사용 목적).
    옥션처럼 상세설명이 접혀있는 상태로 렌더링되는 사이트에서, 접힌 상태 그대로 캡처되는
    문제를 막기 위함. "더보기"는 다른 페이지로 이동하는 링크에도 흔히 쓰이는 문구라
    href가 실제 경로를 가리키면 건너뛰고, 클릭 후 URL이 바뀌면 즉시 뒤로 가서 원복함"""
    current_url = page.url
    expanded = 0
    try:
        candidates = page.locator('button, a, [role="button"], summary').filter(
            has_text=MORE_DETAILS_PATTERN
        )
        count = min(candidates.count(), 5)  # 무한 확장/오탐 방지용 상한
        for i in range(count):
            btn = candidates.nth(i)
            try:
                if not btn.is_visible(timeout=500):
                    continue
                # 실제 다른 페이지로 이동하는 <a href="..."> 링크는 건너뜀
                href = btn.get_attribute('href')
                if href and href not in ('#', '') and not href.startswith('javascript:'):
                    continue
                btn.click(timeout=1500)
                time.sleep(0.8)
                # 혹시 클릭으로 페이지 이동이 발생했으면 즉시 되돌리기 (안전장치)
                if page.url != current_url:
                    page.go_back(timeout=5000)
                    time.sleep(1)
                    continue
                expanded += 1
            except Exception:
                continue
    except Exception:
        pass
    return expanded


def safe_evaluate(page, script, retries=3, retry_delay=1.0):
    """일시적인 오류(예: SPA 리렌더링 중 짧은 순간 document.body가 null이 되는 경우)에
    대비해 page.evaluate()를 재시도. 미스미에서 이 순간에 정확히 걸리면
    "Cannot read properties of null (reading 'scrollHeight')" 예외가 발생하는데,
    실제 네비게이션 문제가 아니라 순식간에 지나가는 현상이라 재시도로 대부분 해결됨"""
    last_exception = None
    for _ in range(retries):
        try:
            return page.evaluate(script)
        except Exception as e:
            last_exception = e
            time.sleep(retry_delay)
    raise last_exception


# [방법2 - 비활성화] 뷰포트 확장(방법1)이 통하지 않을 때 구간별로 나눠 캡처 후 이어붙이는 방식.
# 지금까지 테스트한 사이트는 모두 MAX_VIEWPORT_HEIGHT(15000px) 이하라 방법1만으로 충분히 해결됨.
# 나중에 훨씬 긴 페이지(15000px 초과)를 만나면 아래 주석 해제 + 상단 PIL/io import도 함께 해제할 것
#
# def capture_by_stitching(page, full_path, total_height, width, viewport_height):
#     """[방법2] 뷰포트 크기씩 스크롤하며 여러 장 캡처 후 이어붙이기 (100% 확실하지만 느림)"""
#     stitched = Image.new('RGB', (width, total_height), 'white')
#     offset = 0
#     while offset < total_height:
#         try:
#             page.evaluate(f'window.scrollTo(0, {offset})')
#         except Exception:
#             break
#         time.sleep(0.4)
#         actual_y = page.evaluate('window.scrollY')
#         chunk = Image.open(io.BytesIO(page.screenshot()))
#         stitched.paste(chunk, (0, actual_y))
#         if actual_y + viewport_height >= total_height:
#             break
#         offset += viewport_height
#
#     stitched.save(full_path)
#     try:
#         page.evaluate('window.scrollTo(0, 0)')
#     except Exception:
#         pass


def capture_full_page(page, full_path):
    """[방법1] 문서 전체 높이로 뷰포트 확장 후 캡처.
    [방법2 - 비활성화] 임계값(MAX_VIEWPORT_HEIGHT) 초과 시 원래는 구간별 캡처로 전환했으나
    현재 비활성화 상태 → 초과해도 일단 방법1을 그대로 시도"""
    total_height = page.evaluate('document.body.scrollHeight')
    viewport = page.viewport_size or DEFAULT_VIEWPORT
    width = viewport['width']

    if total_height > MAX_VIEWPORT_HEIGHT:
        print(f"   ⚠️  문서 높이 {total_height}px가 안전 한계를 초과 (방법2 비활성화 상태 → 방법1로 시도)")

    try:
        page.set_viewport_size({"width": width, "height": total_height})
        time.sleep(0.5)  # 리사이즈 후 페인트 안정화 대기
        page.screenshot(path=full_path, full_page=True, scale="device")
    except Exception:
        page.screenshot(path=full_path, full_page=True, scale="device")  # 최종 폴백: 일반 스크린샷


def capture_url(page, url, idx, total, session_output_dir):
    """단일 URL 캡처 로직 (URL별로 독립 실행)"""
    domain = urlparse(url).hostname
    safe_name = domain.replace(".", "_")
    start_time = time.time()  # 소요 시간 측정 시작

    print(f"\n[{idx}/{total}] 🌐 [{safe_name}] 접속 및 캡처 중...")

    # [전략 2] 사전 쿠키 주입 - 동의 완료 상태로 위장하여 팝업 억제
    try:
        page.context.add_cookies([
            {'name': 'cookieconsent_status', 'value': 'dismiss', 'domain': domain, 'path': '/'},
            {'name': 'cookie_consent',       'value': '1',       'domain': domain, 'path': '/'},
            {'name': 'cookies_accepted',     'value': 'true',    'domain': domain, 'path': '/'},
            {'name': 'CookieConsent',        'value': 'true',    'domain': domain, 'path': '/'},
        ])
    except Exception:
        pass

    # [레이어 3 - 비활성화] config.py의 SITE_COOKIES에 등록된 사이트별 추가 쿠키 적용
    # 2026-08-05: 클릭 기반 처리(레이어 4)만으로 충분히 해결되어 우선 비활성화.
    # 클릭도 통하지 않는 사이트(예: iframe 안에 팝업이 들어있는 CMP)를 만나면
    # config.py의 SITE_COOKIES에 해당 사이트 쿠키를 등록하고 아래 주석을 해제
    #
    # for cookie in SITE_COOKIES.get(domain, []):
    #     try:
    #         page.context.add_cookies([{**cookie, 'domain': domain, 'path': cookie.get('path', '/')}])
    #     except Exception:
    #         pass

    # 페이지 이동
    page.goto(url, wait_until='domcontentloaded', timeout=60000)
    # SPA/React 리다이렉트 완료 대기 (미스미처럼 domcontentloaded 직후 URL 전환하는 사이트 대응)
    # 이 대기가 없으면 "Execution context was destroyed" 오류 발생
    try:
        page.wait_for_load_state('load', timeout=15000)
    except Exception:
        pass
    print("   ⏳ 로딩 완료, 동적 데이터 대기 중...")
    time.sleep(1.5)

    # [전략 3] 동의 버튼 클릭 시도 → 실패 시 CSS 강제 숨김(폴백)
    if dismiss_consent_popup(page):
        print("   🍪 쿠키 팝업 발견 → 동의 버튼 클릭으로 제거 완료!")
    else:
        removed = page.evaluate(POPUP_KILLER_SCRIPT)
        if removed:
            print(f"   🍪 쿠키 팝업 발견 → CSS 강제 숨김으로 제거 완료! ({removed}개 요소)")
        else:
            print("   ✅ 쿠키 팝업 없음")

    # "더보기" 류 버튼 클릭 (옥션의 상세정보 더보기처럼 접힌 콘텐츠를 펼쳐서 캡처)
    expanded = expand_more_details(page)
    if expanded:
        print(f"   📖 '더보기' 버튼 {expanded}개 클릭하여 콘텐츠 펼침")

    # 스크롤: 각 evaluate를 개별 try/except로 보호
    # 미스미처럼 스크롤 도중 JS 네비게이션이 일어나 컨텍스트가 파괴되는 사이트 대응
    print("   ⏬ 스크롤 내리며 데이터 깨우는 중...")
    for i in range(1, 5):
        try:
            safe_evaluate(page, f'window.scrollTo(0, document.body.scrollHeight * ({i}/4))')
        except Exception:
            # 재시도까지 다 실패한 경우에만 진짜 네비게이션 문제로 판단하고 안정화 대기 후 중단
            try:
                page.wait_for_load_state('load', timeout=10000)
            except Exception:
                pass
            break
        time.sleep(1.5)

    # 높이가 안정될 때까지 반복 (연속 8회=16초간 변화 없으면 완료로 판단, 최대 10회=20초 대기)
    # 미스미처럼 API 응답은 왔지만 화면에 실제로 그려지기까지(React 렌더링) 15초 가까이
    # 걸리는 사이트가 있음 → "높이 변화 없음"을 바로 완료로 판단하지 않고 충분히 기다림
    # (다른 사이트는 이 정도의 지연이 없어 조금 더 대기하는 정도의 비용만 발생)
    prev_height = 0
    stable_count = 0
    STABLE_THRESHOLD = 8
    MAX_ITER = 10
    for _ in range(MAX_ITER):
        try:
            current_height = safe_evaluate(page, 'document.body.scrollHeight')
        except Exception:
            break
        if current_height <= prev_height:
            stable_count += 1
            if stable_count >= STABLE_THRESHOLD:
                break
        else:
            stable_count = 0
            prev_height = current_height
        try:
            safe_evaluate(page, 'window.scrollTo(0, document.body.scrollHeight)')
        except Exception:
            break
        time.sleep(2)

    # 스크롤 완료 후 네트워크 안정화 1회 대기
    try:
        page.wait_for_load_state('networkidle', timeout=5000)
    except Exception:
        pass

    # 맨 위로 복구
    try:
        page.evaluate('window.scrollTo(0, 0)')
    except Exception:
        pass

    # 캡처 직전: 모든 img 태그 로드 완료 확인 (미완성 이미지 캡처 방지)
    try:
        page.wait_for_function(IMAGES_LOADED_SCRIPT, timeout=10000)
        print("   🖼️  모든 이미지 로드 완료 확인!")
    except Exception:
        print("   ⚠️  이미지 로드 대기 타임아웃 (캡처 진행)")

    # 스크롤 중 뒤늦게 나타난 팝업 재처리 (Didomi 등 일부 CMP는 로드 후 몇 초 뒤에 팝업을 띄움)
    if dismiss_consent_popup(page):
        print("   🍪 (재확인) 지연 등장한 쿠키 팝업 발견 → 동의 버튼 클릭으로 제거 완료!")
    else:
        try:
            removed = page.evaluate(POPUP_KILLER_SCRIPT)
        except Exception:
            removed = 0
        if removed:
            print(f"   🍪 (재확인) 지연 등장한 쿠키 팝업 발견 → CSS 강제 숨김으로 제거 완료! ({removed}개 요소)")

    # 스크롤 중 새로 나타난 "더보기" 버튼 재확인 (지연 로딩된 위젯 내부의 더보기 등)
    expanded = expand_more_details(page)
    if expanded:
        print(f"   📖 (재확인) '더보기' 버튼 {expanded}개 클릭하여 콘텐츠 펼침")

    full_path = os.path.join(session_output_dir, f"{idx}_{safe_name}_full_page.png")
    capture_full_page(page, full_path)
    elapsed = time.time() - start_time
    print(f"   ✅ 전체화면 캡처 완료: {full_path}")
    print(f"   ⏱️  소요 시간: {elapsed:.1f}초")


def run_capture_bot():
    """제외 도메인을 필터링하고 output 폴더에 전체화면을 캡처하는 봇"""

    # 1. 봇 차단 도메인(네이버, 쿠팡 등) 필터링
    valid_urls = []
    print("🔍 URL 필터링 검사 중...")
    for url in TARGET_URLS:
        is_excluded = any(domain in url for domain in EXCLUDE_DOMAINS)
        if is_excluded:
            print(f"   🚫 제외됨 (블랙리스트 매칭): {url}")
        else:
            valid_urls.append(url)
            print(f"   ✅ 캡처 대상 승인: {url}")

    if not valid_urls:
        print("\n❌ 캡처할 수 있는 유효한 URL이 없습니다!")
        return

    # 2. output/ 폴더 내부에 타임스탬프 세션 폴더 생성
    base_output_dir = 'output'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    session_output_dir = os.path.join(base_output_dir, f'capture_{timestamp}')
    os.makedirs(session_output_dir, exist_ok=True)

    print(f"\n📁 최종 저장 폴더: {session_output_dir}")
    print("=" * 60)

    with sync_playwright() as p:
        print("\n🌐 Chrome 실행 중...")

        browser = p.chromium.launch(
            headless=HEADLESS,  # config.py에서 제어
            channel="chrome",
            args=["--window-position=0,0", "--start-maximized"]
        )
        # 고정 뷰포트 사용 (no_viewport=True였던 이전 방식은 set_viewport_size()가
        # 정상 동작하지 않아 캡처 직전 뷰포트 확장(방법1)이 불가능했음)
        context = browser.new_context(viewport=DEFAULT_VIEWPORT, device_scale_factor=2)

        # [레이어 1 - 비활성화] context.add_init_script(INIT_SCRIPT)
        # 재활성화 시 위 INIT_SCRIPT 정의의 주석도 함께 해제할 것

        try:
            for idx, url in enumerate(valid_urls, 1):
                # URL마다 새 page 생성 → 이전 사이트의 JS 상태/스토리지 오염 방지
                page = context.new_page()
                block_cmp_scripts(page)  # CMP 스크립트 네트워크 차단 등록
                try:
                    capture_url(page, url, idx, len(valid_urls), session_output_dir)
                except Exception as e:
                    print(f"   ❌ 오류 발생: {e}")
                    # 오류 발생 시 해당 URL 스크린샷 저장 후 다음 URL로 계속 진행
                    try:
                        safe_name = urlparse(url).hostname.replace(".", "_")
                        error_path = os.path.join(session_output_dir, f"{idx}_{safe_name}_error.png")
                        page.screenshot(path=error_path, full_page=True)
                    except Exception:
                        pass
                finally:
                    page.close()  # 성공/실패 무관하게 page 반드시 닫기

            print(f"\n🎉 모든 유효 페이지 캡처 완료!")
            print(f"📂 저장 위치: {os.path.abspath(session_output_dir)}")

        finally:
            browser.close()


if __name__ == "__main__":
    print("=" * 60)
    print("🚀 URL 필터링 오토 캡처 봇 실행")
    print("=" * 60)
    run_capture_bot()
