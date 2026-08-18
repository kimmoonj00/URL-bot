import json
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

_SELF = os.path.dirname(os.path.abspath(__file__))   # crawl/
_ROOT = os.path.dirname(_SELF)                        # 루트
# _ROOT: from ocr import paddle_ocr / from extract import extract_info 용
# _SELF: import config → crawl/config.py 찾기 위해 _ROOT보다 앞에 삽입
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _SELF not in sys.path:
    sys.path.insert(0, _SELF)

# Windows 콘솔/파일 리다이렉션은 기본적으로 cp949 등 시스템 코드페이지를 쓰기 때문에
# 로그에 쓰는 이모지(⏱️)나 일부 특수문자가 UnicodeEncodeError를 내며 파이프라인
# 전체를 죽일 수 있다. 표준출력/에러를 UTF-8로 강제하되, 그래도 인코딩 못 하는
# 문자가 나오면 예외 대신 대체문자로 바꿔서(errors="replace") 로그 때문에
# 크롤링이 죽는 일이 없게 한다.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

import image_preprocess
import text_filter

from config import (
    BASE_DIR,
    BLOCKED_CHECK_TIMEOUT_MS,
    BLOCKED_TEXT_SAMPLE_CHARS,
    BROWSER_CHANNEL,
    BROWSER_LAUNCH_ARGS,
    BROWSER_LOCALE,
    BROWSER_PROFILE_DIR,
    BROWSER_TIMEZONE,
    CONSENT_BUTTON_CLICK_TIMEOUT_MS,
    CONSENT_BUTTON_MAX_CANDIDATES,
    CONSENT_POST_CLICK_WAIT_MS,
    CONSENT_VISIBLE_TIMEOUT_MS,
    CONTENT_READY_MAX_WAIT_MS,
    CONTENT_READY_POLL_MS,
    CONTENT_READY_STABLE_ROUNDS,
    DEFAULT_VIEWPORT,
    EMPTY_CONTENT_RETRY_WAIT_MS,
    EXCLUDE_DOMAINS,
    EXPAND_BUTTON_CLICK_TIMEOUT_MS,
    EXPAND_BUTTON_MAX_CANDIDATES,
    EXPAND_POST_CLICK_WAIT_MS,
    EXPAND_VISIBLE_TIMEOUT_MS,
    HEADLESS,
    INNER_TEXT_TIMEOUT_MS,
    MANUAL_CHALLENGE_WAIT_SECONDS,
    MAX_OCR_ASSETS_PER_PAGE,
    MIN_OCR_ASSET_HEIGHT,
    MIN_OCR_ASSET_WIDTH,
    MIN_VALID_CONTENT_CHARS,
    PAGE_GOTO_TIMEOUT_MS,
    PAGE_LOAD_STATE_TIMEOUT_MS,
    POST_LOAD_WAIT_MS,
    PRODUCT_REGION_MAX_VIEWPORT_MULTIPLE,
    PRODUCT_REGION_MIN_HEIGHT,
    PRODUCT_REGION_MIN_WIDTH,
    PRODUCT_REGION_PROBE_TIMEOUT_MS,
    PRODUCT_REGION_SELECTORS,
    PRODUCT_REGION_VISIBLE_TIMEOUT_MS,
    TARGET_URLS,
    WAKE_LAZY_MAX_ROUNDS,
    WAKE_LAZY_NETWORK_IDLE_TIMEOUT_MS,
    WAKE_LAZY_STABLE_ROUNDS,
    WAKE_LAZY_WAIT_MS,
    WARMUP_GOTO_TIMEOUT_MS,
    WARMUP_URLS,
)


BLOCKED_PATTERN = re.compile(
    r"access\s*denied|request\s*blocked|unusual\s*traffic|automated\s*(request|access)|"
    r"just\s*a\s*moment|checking\s*your\s*browser|cloudflare|"
    r"비정상적인?\s*접근|접근이?\s*(제한|차단)|봇\s*(확인|검토)|검토\s*번호",
    re.IGNORECASE,
)
MORE_PATTERN = re.compile(
    r"상세\s*(정보|설명)\s*더\s*보기|상품\s*정보\s*더\s*보기|전체\s*보기|더보기|"
    r"view\s*more|show\s*more|more\s*details?",
    re.IGNORECASE,
)


def safe_name(url):
    host = urlparse(url).hostname or "unknown"
    return host.replace(".", "_")


def is_blocked(page):
    try:
        sample = f"{page.title()} {page.locator('body').inner_text(timeout=BLOCKED_CHECK_TIMEOUT_MS)[:BLOCKED_TEXT_SAMPLE_CHARS]}"
        return bool(BLOCKED_PATTERN.search(sample))
    except Exception:
        return False


def get_visible_text_length(page):
    """메인 프레임 body의 글자 수. 차단 문구는 없지만 본문이 사실상 비어 있는
    캡처(예: SPA가 아직 안 그려짐)를 판단하는 데 쓰는 가벼운 지표다."""
    try:
        return len(page.locator("body").inner_text(timeout=INNER_TEXT_TIMEOUT_MS))
    except Exception:
        return 0


def wait_for_content_ready(page, max_wait_ms):
    """본문 글자 수가 더 늘지 않을 때까지 짧은 간격으로 폴링한다.

    예전에는 페이지 로드 후 무조건 POST_LOAD_WAIT_MS(고정값)만큼 잠들었다.
    이 방식은 이미 다 그려진 빠른 사이트에서도 항상 같은 시간을 낭비하고,
    반대로 느린 SPA에서는 그 시간이 부족해도 그대로 다음 단계로 넘어가는
    문제가 있었다. 대신 본문 길이가 안정될 때까지(또는 예산 소진까지)만
    기다려서 빠른 사이트는 즉시 넘어가고 느린 사이트는 필요한 만큼 기다리게
    한다."""
    deadline = time.time() + max_wait_ms / 1000
    previous_length = -1
    stable_rounds = 0
    length = 0
    while True:
        length = get_visible_text_length(page)
        if length == previous_length:
            stable_rounds += 1
            if stable_rounds >= CONTENT_READY_STABLE_ROUNDS:
                return length
        else:
            stable_rounds = 0
        previous_length = length
        if time.time() >= deadline:
            return length
        page.wait_for_timeout(CONTENT_READY_POLL_MS)


def warm_up(page, url):
    host = urlparse(url).hostname or ""
    warmup = WARMUP_URLS.get(host)
    if not warmup:
        return
    print(f"   워밍업 방문: {warmup}")
    try:
        page.goto(warmup, wait_until="domcontentloaded", timeout=WARMUP_GOTO_TIMEOUT_MS)
        page.wait_for_timeout(POST_LOAD_WAIT_MS)
    except Exception as error:
        print(f"   워밍업 실패(상세 페이지는 계속 진행): {error}")


def wait_for_manual_challenge(page):
    """표시 브라우저에서 사용자가 사이트의 정상 확인 절차를 마칠 시간을 준다."""
    if HEADLESS or not is_blocked(page):
        return not is_blocked(page)

    print("   보안 확인 화면입니다. 열린 Chrome에서 정상 확인 절차를 완료하세요.")
    deadline = time.time() + MANUAL_CHALLENGE_WAIT_SECONDS
    while time.time() < deadline:
        page.wait_for_timeout(POST_LOAD_WAIT_MS)
        if not is_blocked(page):
            print("   보안 확인 완료. 저장된 브라우저 세션을 다음 실행에도 재사용합니다.")
            return True
    return False


def dismiss_consent(page):
    # "동의/수락" 계열 문구만 잡던 예전 패턴은 Swagelok처럼 "모두 허용" 문구를
    # 쓰는 배너(Didomi 등)를 놓쳤다 — 배너가 안 닫힌 채로 product_region
    # 스크린샷 하단을 가려버리는 걸 실제 캡처로 확인해서 "허용" 계열도 추가했다.
    pattern = re.compile(
        r"accept all|allow all|i agree|got it|"
        r"모두\s*수락|전체\s*동의|모두\s*동의|모두\s*허용|전체\s*허용|동의|허용",
        re.IGNORECASE,
    )
    try:
        candidates = page.get_by_role("button", name=pattern)
        for index in range(min(candidates.count(), CONSENT_BUTTON_MAX_CANDIDATES)):
            button = candidates.nth(index)
            if button.is_visible(timeout=CONSENT_VISIBLE_TIMEOUT_MS):
                button.click(timeout=CONSENT_BUTTON_CLICK_TIMEOUT_MS)
                page.wait_for_timeout(CONSENT_POST_CLICK_WAIT_MS)
                return True
    except Exception:
        pass
    return False


def expand_details(page):
    expanded = 0
    try:
        candidates = page.locator("button, [role=button], summary").filter(has_text=MORE_PATTERN)
        for index in range(min(candidates.count(), EXPAND_BUTTON_MAX_CANDIDATES)):
            target = candidates.nth(index)
            try:
                if target.is_visible(timeout=EXPAND_VISIBLE_TIMEOUT_MS):
                    target.click(timeout=EXPAND_BUTTON_CLICK_TIMEOUT_MS)
                    expanded += 1
                    page.wait_for_timeout(EXPAND_POST_CLICK_WAIT_MS)
            except Exception:
                continue
    except Exception:
        pass
    return expanded


def wake_lazy_content(page):
    previous_height = 0
    stable = 0
    for _ in range(WAKE_LAZY_MAX_ROUNDS):
        try:
            height = page.evaluate("document.documentElement.scrollHeight")
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        except Exception:
            break
        page.wait_for_timeout(WAKE_LAZY_WAIT_MS)
        if height == previous_height:
            stable += 1
            if stable >= WAKE_LAZY_STABLE_ROUNDS:
                break
        else:
            stable = 0
            previous_height = height
    try:
        # 스크롤로 지연 로딩을 트리거한 뒤, 이미지 다운로드 같은 네트워크 요청이
        # 실제로 끝날 때까지 한 번 더 기다린다(전처리/OCR 전 완전히 로드된 상태로 캡처).
        page.wait_for_load_state("networkidle", timeout=WAKE_LAZY_NETWORK_IDLE_TIMEOUT_MS)
    except Exception:
        pass
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


def extract_tables(frame):
    return frame.evaluate(
        """() => {
            // 일부 사이트(예: 나비엠알오)는 VAT포함가/VAT별도가를 같은 셀 안에
            // '.price-info'(제외가) / '.price-info.vat_price'(포함가) 두 개로
            // 넣어두고 CSS display로 토글해 하나만 보이게 한다. cell.innerText는
            // 그 순간 화면에 보이는 쪽만 읽으므로, 캡처 시점(토글 상태)에 따라
            // 결과가 랜덤하게 달라지고 나머지 값은 그냥 사라진다. 이런 셀을
            // 만나면 두 값을 각각 명시적으로 읽어 text에 같이 담고, 구조화된
            // 값도 price_vat_excluded/price_vat_included로 별도 저장한다.
            const cellData = (cell) => {
                const priceEls = Array.from(cell.querySelectorAll('.price-info'));
                if (priceEls.length > 1) {
                    const excludedEl = priceEls.find(el => !el.classList.contains('vat_price'));
                    const includedEl = priceEls.find(el => el.classList.contains('vat_price'));
                    const excludedText = excludedEl ? excludedEl.textContent.replace(/\\s+/g, ' ').trim() : '';
                    const includedText = includedEl ? includedEl.textContent.replace(/\\s+/g, ' ').trim() : '';
                    return {
                        text: [excludedText, includedText].filter(Boolean).join(' / '),
                        price_vat_excluded: excludedText || null,
                        price_vat_included: includedText || null
                    };
                }
                return { text: cell.innerText.replace(/\\s+/g, ' ').trim() };
            };
            return Array.from(document.querySelectorAll('table')).map((table, tableIndex) => ({
                table_index: tableIndex + 1,
                rows: Array.from(table.querySelectorAll('tr')).map(row =>
                    Array.from(row.querySelectorAll('th,td')).map(cell => {
                        const data = cellData(cell);
                        return {
                            text: data.text,
                            rowspan: Number(cell.getAttribute('rowspan') || 1),
                            colspan: Number(cell.getAttribute('colspan') || 1),
                            ...(data.price_vat_excluded !== undefined ? {
                                price_vat_excluded: data.price_vat_excluded,
                                price_vat_included: data.price_vat_included
                            } : {})
                        };
                    })
                ).filter(row => row.length)
            })).filter(table => table.rows.length);
        }"""
    )


def merge_split_tables(tables):
    """일부 사이트(예: MISUMI)는 열 고정 때문에 화면상 하나인 표를
    헤더 1행짜리 표 + 본문 N행짜리 표로 쪼개서 렌더링한다.
    연속된 (헤더, 본문) 쌍을 화면에 보이는 순서대로 다시 이어붙인다."""
    merged = []
    index = 0
    total = len(tables)
    while index < total:
        header = tables[index]
        header_rows = header["rows"]
        if len(header_rows) != 1 or index + 1 >= total:
            merged.append(header)
            index += 1
            continue
        body = tables[index + 1]
        header_columns = len(header_rows[0])
        if (
            body["frame_index"] != header["frame_index"]
            or len(body["rows"]) <= 1
            or len(body["rows"][0]) != header_columns
        ):
            merged.append(header)
            index += 1
            continue

        row_count = len(body["rows"])
        header_blocks = [header_rows[0]]
        body_blocks = [body["rows"]]
        cursor = index + 2
        while cursor + 1 < total:
            next_header = tables[cursor]
            next_body = tables[cursor + 1]
            if (
                len(next_header["rows"]) == 1
                and next_header["frame_index"] == header["frame_index"]
                and next_body["frame_index"] == header["frame_index"]
                and len(next_body["rows"]) == row_count
            ):
                header_blocks.append(next_header["rows"][0])
                body_blocks.append(next_body["rows"])
                cursor += 2
            else:
                break

        combined_rows = [[cell for block in header_blocks for cell in block]]
        for row_index in range(row_count):
            combined_rows.append(
                [cell for block in body_blocks for cell in block[row_index]]
            )
        merged.append(
            {
                "table_index": header["table_index"],
                "rows": combined_rows,
                "frame_index": header["frame_index"],
            }
        )
        index = cursor

    for position, table in enumerate(merged, 1):
        table["table_index"] = position
    return merged


def save_page_sources(page, prefix):
    text_sections = []
    tables = []
    for frame_index, frame in enumerate(page.frames):
        try:
            frame_text = frame.locator("body").inner_text(timeout=INNER_TEXT_TIMEOUT_MS).strip()
            if frame_text:
                label = "MAIN" if frame == page.main_frame else f"IFRAME {frame_index}"
                text_sections.append(f"[{label}]\n{frame_text}")
        except Exception:
            pass
        try:
            for table in extract_tables(frame):
                table["frame_index"] = frame_index
                tables.append(table)
        except Exception:
            pass
    tables = merge_split_tables(tables)
    # 상품명/모델번호/사이즈는 한글·영문·숫자로만 이뤄지므로, 다국어 사이트의
    # 언어선택 메뉴나 병기된 일본어/한자를 여기서 걸러내 이후 추출 단계의
    # 잡음을 줄인다 (text_filter.py, config.FILTER_NON_KOREAN_SCRIPTS로 on/off).
    tables = text_filter.clean_table_cells(tables)
    visible_text = text_filter.clean_unwanted_scripts("\n\n".join(text_sections))
    with open(os.path.join(prefix, "dom.txt"), "w", encoding="utf-8") as output:
        output.write(visible_text)
    with open(os.path.join(prefix, "tables.json"), "w", encoding="utf-8") as output:
        json.dump(tables, output, ensure_ascii=False, indent=2)

    with open(os.path.join(prefix, "tables.txt"), "w", encoding="utf-8") as output:
        for table in tables:
            output.write(f"[표 {table['table_index']}]\n")
            for row in table["rows"]:
                output.write("\t".join(cell["text"] for cell in row) + "\n")
            output.write("\n")
    return len(tables)


def capture_ocr_assets(page, prefix):
    """DOM으로 읽을 수 없는 이미지/Canvas만 개별 저장한다.

    성능: 예전 방식은 이미지 하나당 is_visible/bounding_box/evaluate(태그)/
    evaluate(src)/get_attribute(alt)까지 최대 5번씩 Playwright와 왕복했다.
    이미지가 많은 페이지(아이콘/뱃지가 수십 개인 상세페이지 등)에서는 이
    왕복 비용이 스크린샷 자체보다 커질 수 있다. 여기서는 프레임당 판단에
    필요한 정보(보임 여부/크기/태그/src/alt)를 JS 한 번(evaluate)으로 모두
    가져온 뒤, 실제로 저장 대상으로 채택된 이미지에 대해서만 screenshot()을
    호출한다 — 왕복 횟수를 "이미지 수 x 5"에서 "1 + 채택된 이미지 수"로 줄인다.

    (참고: evaluate와 이후 screenshot 사이에 DOM이 크게 바뀌면 인덱스가
    어긋날 이론적 여지가 있으나, wake_lazy_content에서 이미 지연 로딩과
    네트워크 idle까지 기다린 뒤 호출되므로 실제 위험은 낮다.)

    저장 전 image_preprocess로 화질/색감을 다듬고, 각 이미지에 어떤 처리가
    적용됐는지(action, 원본/처리후 크기)를 manifest(assets.json)에 함께
    남긴다 — 실행 결과 파일만 열어봐도 전처리가 실제로 적용됐는지,
    어떤 이미지가 확대/축소됐는지 바로 확인할 수 있게 하기 위함이다.
    """
    asset_dir = os.path.join(prefix, "assets")
    os.makedirs(asset_dir, exist_ok=True)
    manifest = []
    seen_sources = set()

    for frame_index, frame in enumerate(page.frames):
        try:
            elements_info = frame.evaluate(
                """() => Array.from(document.querySelectorAll('img, canvas')).map(node => {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    const visible = rect.width > 0 && rect.height > 0 &&
                        style.visibility !== 'hidden' && style.display !== 'none' &&
                        parseFloat(style.opacity || '1') > 0;
                    const tag = node.tagName.toLowerCase();
                    return {
                        tag: tag,
                        visible: visible,
                        width: rect.width,
                        height: rect.height,
                        src: tag === 'img' ? (node.currentSrc || node.src || '') : '',
                        alt: node.getAttribute('alt') || ''
                    };
                })"""
            )
            locator = frame.locator("img, canvas")
        except Exception:
            continue

        for element_index, info in enumerate(elements_info):
            if len(manifest) >= MAX_OCR_ASSETS_PER_PAGE:
                break
            if not info["visible"]:
                continue
            if info["width"] < MIN_OCR_ASSET_WIDTH or info["height"] < MIN_OCR_ASSET_HEIGHT:
                continue
            key = info["src"] or f"canvas:{frame_index}:{element_index}:{round(info['width'])}x{round(info['height'])}"
            if key in seen_sources:
                continue
            seen_sources.add(key)
            try:
                element = locator.nth(element_index)
                filename = f"asset_{len(manifest) + 1:03d}_{info['tag']}.png"
                path = os.path.join(asset_dir, filename)
                screenshot_bytes = element.screenshot(animations="disabled")
                processed_bytes, preprocess_stats = image_preprocess.preprocess_for_ocr(screenshot_bytes)
                with open(path, "wb") as image_file:
                    image_file.write(processed_bytes)
                manifest.append(
                    {
                        "file": path,
                        "tag": info["tag"],
                        "src": info["src"],
                        "alt": info["alt"],
                        "frame_index": frame_index,
                        "width": round(info["width"]),
                        "height": round(info["height"]),
                        "preprocess": preprocess_stats,
                    }
                )
            except Exception:
                continue
        if len(manifest) >= MAX_OCR_ASSETS_PER_PAGE:
            break

    manifest_path = os.path.join(prefix, "assets.json")
    with open(manifest_path, "w", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
    return manifest


def capture_product_region(page, url, prefix):
    """사이트별 상품 본문만 별도 저장해 메뉴·광고가 OCR을 방해하지 않게 한다.
    선택자 여러 개가 등록된 사이트는 마지막 후보 전까지 짧은 타임아웃으로
    빠르게 훑고, 마지막 후보만 넉넉히 기다린다(불필요한 대기 시간 절약)."""
    host = urlparse(url).hostname or ""
    selectors = PRODUCT_REGION_SELECTORS.get(host, ["main"])
    last_index = len(selectors) - 1
    viewport = page.viewport_size or DEFAULT_VIEWPORT
    # 후보가 뷰포트 높이의 N배를 넘으면 상품 "영역"이 아니라 메뉴/푸터/연관상품까지
    # 딸려온 페이지 "전체"로 보고 건너뛴다(사이트별 예외 대신 일반 규칙 하나로 처리).
    max_region_height = viewport["height"] * PRODUCT_REGION_MAX_VIEWPORT_MULTIPLE
    for index, selector in enumerate(selectors):
        visible_timeout = (
            PRODUCT_REGION_VISIBLE_TIMEOUT_MS if index == last_index else PRODUCT_REGION_PROBE_TIMEOUT_MS
        )
        try:
            region = page.locator(selector).first
            if not region.is_visible(timeout=visible_timeout):
                continue
            box = region.bounding_box()
            if not box or box["width"] < PRODUCT_REGION_MIN_WIDTH or box["height"] < PRODUCT_REGION_MIN_HEIGHT:
                continue
            if box["height"] > max_region_height:
                continue
            path = os.path.join(prefix, "product.png")
            screenshot_bytes = region.screenshot(animations="disabled")
            processed_bytes, preprocess_stats = image_preprocess.preprocess_for_ocr(screenshot_bytes)
            with open(path, "wb") as image_file:
                image_file.write(processed_bytes)
            with open(os.path.join(prefix, "product_dom.txt"), "w", encoding="utf-8") as output:
                output.write(text_filter.clean_unwanted_scripts(region.inner_text(timeout=INNER_TEXT_TIMEOUT_MS)))
            return path, selector, preprocess_stats
        except Exception:
            continue
    return None, None, None


def capture_one(page, url, index, total, output_dir):
    # 상품 하나당 파일을 흩뿌리지 않고 전용 폴더({index}_{도메인}/) 하나에 모은다.
    # 예: output_dir/1_kr_misumi-ec_com/{dom.txt, tables.json, assets/, metadata.json, ...}
    name = safe_name(url)
    prefix = os.path.join(output_dir, f"{index}_{name}")
    os.makedirs(prefix, exist_ok=True)
    print(f"\n[{index}/{total}] 접속: {url}")
    started = time.perf_counter()

    warm_up(page, url)
    page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
    try:
        page.wait_for_load_state("load", timeout=PAGE_LOAD_STATE_TIMEOUT_MS)
    except Exception:
        pass
    wait_for_content_ready(page, CONTENT_READY_MAX_WAIT_MS)

    if is_blocked(page) and not wait_for_manual_challenge(page):
        try:
            page.screenshot(path=os.path.join(prefix, "blocked.png"), full_page=True)
        except Exception:
            pass
        elapsed = time.perf_counter() - started
        metadata = {
            "url": url,
            "status": "blocked",
            "title": page.title(),
            "elapsed_seconds": round(elapsed, 1),
        }
        with open(os.path.join(prefix, "metadata.json"), "w", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)
        print("   차단 화면이 유지되어 상품 캡처와 OCR 대상에서 제외했습니다.")
        print(f"   ⏱️  소요 시간: {elapsed:.1f}초")
        return "blocked"

    if dismiss_consent(page):
        print("   쿠키 동의 창을 닫았습니다.")
    expanded = expand_details(page)
    if expanded:
        print(f"   상세정보 버튼 {expanded}개를 펼쳤습니다.")
    wake_lazy_content(page)
    # 스크롤로 새로 나타난 "더보기" 버튼이 있을 수 있어 한 번 더 시도한다
    # (스크롤 전 시도만으로는 지연 로딩된 영역의 버튼을 못 잡는 경우가 있음).
    expand_details(page)
    # 동의 배너를 한 번 더 확인한다. Festo(Didomi) 실측 캡처에서 배너가 최초
    # dismiss_consent() 호출 시점엔 아직 안 떴다가 뒤늦게(로드 후 수백ms~수초)
    # 나타나는 걸 확인했다 — 그대로 두면 product.png 중간을 가린다.
    if dismiss_consent(page):
        print("   쿠키 동의 창을 닫았습니다(지연 표시분).")

    content_length = get_visible_text_length(page)
    if content_length < MIN_VALID_CONTENT_CHARS:
        # 차단 문구는 없지만 본문이 사실상 비어 있다 — 아직 다 안 그려진 SPA일
        # 수 있으니, 네트워크가 잠잠해지길 한 번 더 기다린 뒤 재확인한다.
        print("   본문이 비어 있는 것으로 보여 추가 대기 후 재확인합니다.")
        try:
            page.wait_for_load_state("networkidle", timeout=EMPTY_CONTENT_RETRY_WAIT_MS)
        except Exception:
            pass
        content_length = wait_for_content_ready(page, EMPTY_CONTENT_RETRY_WAIT_MS)

    table_count = save_page_sources(page, prefix)
    ocr_assets = capture_ocr_assets(page, prefix)
    product_path, product_selector, product_preprocess = capture_product_region(page, url, prefix)

    # 재시도 후에도 본문/표/OCR 에셋이 전부 비었다면 "captured"로 표시해 성공한
    # 것처럼 보이게 하지 않는다 — Festo처럼 차단 문구 없이 빈 페이지만 오는
    # 경우를 조용히 놓치지 않기 위한 안전장치다.
    is_empty = content_length < MIN_VALID_CONTENT_CHARS and table_count == 0 and not ocr_assets

    # 이번 페이지에서 전처리가 실제로 어떻게 적용됐는지 집계한다.
    # (예: {"upscaled": 2, "downscaled": 1, "none": 3}) — 실행 로그를 다시
    # 뒤지지 않고 metadata.json만 열어봐도 전처리 적용 여부를 바로 확인할 수 있다.
    preprocess_summary = {"upscaled": 0, "downscaled": 0, "none": 0, "disabled_or_failed": 0}
    for asset in ocr_assets:
        stats = asset.get("preprocess") or {}
        if not stats.get("applied"):
            preprocess_summary["disabled_or_failed"] += 1
        else:
            preprocess_summary[stats.get("action", "none")] += 1
    if product_preprocess:
        if not product_preprocess.get("applied"):
            preprocess_summary["disabled_or_failed"] += 1
        else:
            preprocess_summary[product_preprocess.get("action", "none")] += 1

    if is_empty:
        try:
            page.screenshot(path=os.path.join(prefix, "empty.png"), full_page=True)
        except Exception:
            pass

    status = "empty" if is_empty else "captured"
    elapsed = time.perf_counter() - started
    metadata = {
        "url": url,
        "status": status,
        "title": page.title(),
        "final_url": page.url,
        "content_length": content_length,
        "table_count": table_count,
        "ocr_asset_count": len(ocr_assets),
        "ocr_assets_manifest": os.path.join(prefix, "assets.json"),
        "product_screenshot": product_path,
        "product_selector": product_selector,
        "product_screenshot_preprocess": product_preprocess,
        "preprocess_summary": preprocess_summary,
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(os.path.join(prefix, "metadata.json"), "w", encoding="utf-8") as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2)
    if is_empty:
        print("   ⚠️  본문/표/OCR 에셋이 모두 비어 있어 status를 'empty'로 표시했습니다 (empty.png 확인).")
    else:
        print(f"   캡처 완료: DOM 표 {table_count}개 / OCR 에셋 {len(ocr_assets)}개")
    print(f"   🖼️  전처리 적용: 확대 {preprocess_summary['upscaled']}개 / "
          f"축소 {preprocess_summary['downscaled']}개 / 변경없음 {preprocess_summary['none']}개")
    print(f"   ⏱️  소요 시간: {elapsed:.1f}초")
    return status


def run_capture_bot(run_ocr_and_extract=True):
    urls = [
        url for url in TARGET_URLS
        if not any(excluded.lower() in (urlparse(url).hostname or "").lower() for excluded in EXCLUDE_DOMAINS)
    ]
    if not urls:
        print("캡처할 URL이 없습니다. urls.txt를 확인하세요.")
        return

    # 'crawl'이라는 이름을 하드코딩하지 않는다 — crawler.py가 어떤 이름의
    # 폴더에 있든(product_extractor_3 등) 항상 그 폴더 바로 아래에 output/을
    # 만든다. 예전엔 _ROOT/"crawl"/output으로 고정해뒀는데, 폴더명이 "crawl"이
    # 아니면 한 단계 위 엉뚱한 곳에 output이 생겨서 못 찾는 문제가 있었다.
    output_dir = os.path.join(_SELF, "output", "capture_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    print(f"캡처 대상 {len(urls)}개 / 저장 위치: {output_dir}")

    pipeline_started = time.perf_counter()
    results = []
    with sync_playwright() as playwright:
        # 실제 Chrome 프로필과 섞지 않는 전용 영구 프로필이다. 정상 로그인/보안 확인 상태만 재사용한다.
        context = playwright.chromium.launch_persistent_context(
            BROWSER_PROFILE_DIR,
            channel=BROWSER_CHANNEL,
            headless=HEADLESS,
            viewport=DEFAULT_VIEWPORT,
            locale=BROWSER_LOCALE,
            timezone_id=BROWSER_TIMEZONE,
            args=BROWSER_LAUNCH_ARGS,
        )
        try:
            for index, url in enumerate(urls, 1):
                page = context.new_page()
                try:
                    status = capture_one(page, url, index, len(urls), output_dir)
                except Exception as error:
                    status = "error"
                    print(f"   오류: {error}")
                    try:
                        error_dir = os.path.join(output_dir, f"{index}_{safe_name(url)}")
                        os.makedirs(error_dir, exist_ok=True)
                        page.screenshot(
                            path=os.path.join(error_dir, "error.png"),
                            full_page=True,
                        )
                    except Exception:
                        pass
                finally:
                    page.close()
                results.append({"url": url, "status": status})
        finally:
            context.close()

    capture_elapsed = time.perf_counter() - pipeline_started
    with open(os.path.join(output_dir, "capture_summary.json"), "w", encoding="utf-8") as output:
        json.dump(results, output, ensure_ascii=False, indent=2)
    print(f"\n캡처 완료: {output_dir}")
    print(f"⏱️  캡처 전체 소요 시간: {capture_elapsed:.1f}초 (평균 {capture_elapsed / len(urls):.1f}초/건)")

    if run_ocr_and_extract:
        # 캡처가 끝나면 이어서 OCR → 상품명/규격 추출까지 한 번에 수행한다.
        # ocr/, extract/ 폴더가 아직 없거나(팀원 파일을 아직 안 받음) paddleocr
        # 미설치 환경이면 여기서 ImportError가 난다. 이미 캡처는 성공적으로
        # 끝난 뒤이므로, 그 결과가 트레이스백에 묻혀 안 보이는 일이 없도록
        # 크래시 대신 안내 메시지만 남기고 넘어간다.
        try:
            from ocr import paddle_ocr
            from extract import extract_info
        except ImportError as error:
            print(f"\n⚠️  OCR/추출 단계를 건너뜁니다({error}).")
            print(f"   캡처 결과는 정상적으로 저장되어 있습니다: {output_dir}")
            print("   ocr/, extract/ 폴더를 팀원에게 받은 뒤 다시 시도하거나,")
            print("   run_capture_bot(run_ocr_and_extract=False)로 캡처만 반복 실행하세요.")
        else:
            run_name = os.path.basename(output_dir)  # "capture_YYYYMMDD_HHMMSS"
            ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name)
            extract_dir = os.path.join(_ROOT, "extract", "output", run_name)

            paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)
            extract_info.build_summary(output_dir, ocr_dir=ocr_dir, extract_dir=extract_dir)

    total_elapsed = time.perf_counter() - pipeline_started
    print(f"⏱️  전체 파이프라인 소요 시간: {total_elapsed:.1f}초")


if __name__ == "__main__":
    run_capture_bot()
