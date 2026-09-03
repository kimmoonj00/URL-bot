import asyncio
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # 한국어 Windows(cp949) 콘솔 인코딩으로는 이모지(⏱️ 등)를 print()할 때
    # UnicodeEncodeError가 나서 캡처 자체가 죽는다(실제 데이터는 이미 저장된
    # 뒤라 크래시 자체는 치명적이지 않지만 매번 에러 로그가 남는다).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import html2text as _html2text_lib

from playwright.async_api import async_playwright

_SELF = os.path.dirname(os.path.abspath(__file__))   # crawl/
_ROOT = os.path.dirname(_SELF)                        # 루트
# _ROOT: from ocr import paddle_ocr / from extract import extract_info 용
# _SELF: import config → crawl/config.py 찾기 위해 _ROOT보다 앞에 삽입
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if _SELF not in sys.path:
    sys.path.insert(0, _SELF)

from config import (
    BLOCK_RESOURCE_TYPES,
    BLOCK_URL_KEYWORDS,
    BLOCKED_CHECK_TIMEOUT_MS,
    BROWSER_PROFILE_DIR,
    CHALLENGE_POLL_INTERVAL_MS,
    CONSENT_CLICK_TIMEOUT_MS,
    CONSENT_MAX_BUTTONS,
    CONSENT_SETTLE_MS,
    CONSENT_VISIBLE_TIMEOUT_MS,
    DEFAULT_VIEWPORT,
    DETAIL_EXPAND_CLICK_TIMEOUT_MS,
    DETAIL_EXPAND_MAX_BUTTONS,
    DETAIL_EXPAND_SETTLE_MS,
    DETAIL_EXPAND_VISIBLE_TIMEOUT_MS,
    ELEMENT_SCREENSHOT_TIMEOUT_MS,
    ENABLE_IMAGE_PREPROCESS,
    EXCLUDE_DOMAINS,
    HEADLESS,
    IMAGE_AUTOCONTRAST_CUTOFF,
    IMAGE_CONTRAST_FACTOR,
    IMAGE_SHARPNESS_FACTOR,
    IMAGE_UPSCALE_MAX_SCALE,
    IMAGE_UPSCALE_MIN_WIDTH,
    LOAD_STATE_TIMEOUT_MS,
    MANUAL_CHALLENGE_WAIT_SECONDS,
    MAX_CONCURRENT_PAGES,
    MAX_OCR_ASSETS_PER_PAGE,
    MIN_OCR_ASSET_HEIGHT,
    MIN_OCR_ASSET_WIDTH,
    NAV_TIMEOUT_MS,
    NETWORK_SETTLE_TIMEOUT_MS,
    PRODUCT_REGION_MIN_HEIGHT,
    PRODUCT_REGION_MIN_WIDTH,
    PRODUCT_REGION_SELECTORS,
    PRODUCT_REGION_VISIBLE_TIMEOUT_MS,
    SCROLL_MAX_ATTEMPTS,
    SCROLL_STABLE_ROUNDS,
    SCROLL_WAIT_MS,
    TABLE_RETRY_ATTEMPTS,
    TABLE_WAIT_TIMEOUT_MS,
    TARGET_URLS,
    TEXT_EXTRACT_TIMEOUT_MS,
    WARMUP_URLS,
)


def _html_to_md(html_source):
    """HTML 조각을 LLM 친화적 Markdown으로 변환한다.
    링크 URL과 이미지 src는 노이즈이므로 제거한다."""
    converter = _html2text_lib.HTML2Text()
    converter.ignore_links = True
    converter.ignore_images = True
    converter.body_width = 0       # 자동 줄바꿈 없음
    converter.unicode_snob = True  # 유니코드 그대로 유지
    return converter.handle(html_source or "").strip()


def _tables_to_markdown(tables):
    """JS로 추출·머지된 테이블 목록을 Markdown 파이프 테이블로 변환한다."""
    if not tables:
        return ""

    def _cell(text):
        return text.replace("|", "\\|").replace("\n", " ").strip()

    lines = []
    for table in tables:
        rows = table.get("rows", [])
        if not rows:
            continue
        lines.append(f"\n### 표 {table['table_index']}")
        header = rows[0]
        lines.append("| " + " | ".join(_cell(c["text"]) for c in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(_cell(c["text"]) for c in row) + " |")
    return "\n".join(lines)


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

# 요소 단위로 뷰포트 내 표시 여부 + 크기를 한 번에 스캔하기 위한 JS.
# (기존에는 요소마다 is_visible()/bounding_box()/evaluate()를 각각 호출해
#  요소 수만큼 왕복(round-trip)이 발생했다. 이제 프레임당 한 번의 evaluate로 끝낸다.)
_SCAN_MEDIA_JS = """
([minWidth, minHeight, scopeSelector]) => {
    const all = Array.from(document.querySelectorAll('img, canvas'));
    let scopeSet = null;
    if (scopeSelector) {
        const root = document.querySelector(scopeSelector);
        if (root) scopeSet = new Set(Array.from(root.querySelectorAll('img, canvas')));
    }
    return all.map((el, i) => {
        if (scopeSet && !scopeSet.has(el)) return null;
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        const visible = style.visibility !== 'hidden'
            && style.display !== 'none'
            && parseFloat(style.opacity || '1') > 0
            && rect.width >= minWidth
            && rect.height >= minHeight;
        return {
            index: i,
            tag: el.tagName.toLowerCase(),
            src: el.tagName.toLowerCase() === 'img' ? (el.currentSrc || el.src || '') : '',
            alt: el.getAttribute('alt') || '',
            width: Math.round(rect.width),
            height: Math.round(rect.height),
            visible,
        };
    }).filter(item => item && item.visible);
}
"""


def safe_name(url):
    host = urlparse(url).hostname or "unknown"
    return host.replace(".", "_")


async def setup_resource_blocking(context):
    """텍스트는 DOM에서 직접 읽고 이미지는 OCR용으로만 필요하므로,
    렌더링에 불필요한 리소스(동영상, 폰트, 광고/추적 스크립트)는 아예 받지 않는다."""
    if not BLOCK_RESOURCE_TYPES and not BLOCK_URL_KEYWORDS:
        return

    async def handle_route(route):
        request = route.request
        if request.resource_type in BLOCK_RESOURCE_TYPES:
            return await route.abort()
        url = request.url.lower()
        if any(keyword in url for keyword in BLOCK_URL_KEYWORDS):
            return await route.abort()
        return await route.continue_()

    await context.route("**/*", handle_route)


def preprocess_image_for_ocr(path):
    """OCR 정확도를 높이기 위한 가벼운 이미지 전처리(색 보정):
    - 너무 작은 이미지는 업스케일 (작은 글자 대응)
    - 명암 자동 보정(autocontrast)
    - 대비/선명도 보정
    Pillow만 사용하며, 실패해도 원본 스크린샷은 그대로 남는다."""
    if not ENABLE_IMAGE_PREPROCESS:
        return
    try:
        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        return
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            if img.width and img.width < IMAGE_UPSCALE_MIN_WIDTH:
                scale = min(IMAGE_UPSCALE_MIN_WIDTH / img.width, IMAGE_UPSCALE_MAX_SCALE)
                new_size = (round(img.width * scale), round(img.height * scale))
                img = img.resize(new_size, Image.LANCZOS)
            img = ImageOps.autocontrast(img, cutoff=IMAGE_AUTOCONTRAST_CUTOFF)
            img = ImageEnhance.Contrast(img).enhance(IMAGE_CONTRAST_FACTOR)
            img = ImageEnhance.Sharpness(img).enhance(IMAGE_SHARPNESS_FACTOR)
            img.save(path)
    except Exception as error:
        print(f"   이미지 전처리 실패({os.path.basename(path)}): {error}")


async def is_blocked(page):
    try:
        body_text = await page.locator('body').inner_text(timeout=BLOCKED_CHECK_TIMEOUT_MS)
        sample = f"{await page.title()} {body_text[:1500]}"
        return bool(BLOCKED_PATTERN.search(sample))
    except Exception:
        return False


async def warm_up(page, url):
    host = urlparse(url).hostname or ""
    warmup = WARMUP_URLS.get(host)
    if not warmup:
        return
    print(f"   워밍업 방문: {warmup}")
    try:
        await page.goto(warmup, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        await wait_for_network_settle(page)
    except Exception as error:
        print(f"   워밍업 실패(상세 페이지는 계속 진행): {error}")


async def wait_for_network_settle(page):
    """무조건 N초 자는 대신, 네트워크가 먼저 조용해지면 그 즉시 다음 단계로 넘어간다."""
    try:
        await page.wait_for_load_state("networkidle", timeout=NETWORK_SETTLE_TIMEOUT_MS)
    except Exception:
        pass


async def wait_for_manual_challenge(page):
    """표시 브라우저에서 사용자가 사이트의 정상 확인 절차를 마칠 시간을 준다."""
    blocked = await is_blocked(page)
    if HEADLESS or not blocked:
        return not blocked

    print("   보안 확인 화면입니다. 열린 Chrome에서 정상 확인 절차를 완료하세요.")
    deadline = time.time() + MANUAL_CHALLENGE_WAIT_SECONDS
    while time.time() < deadline:
        await page.wait_for_timeout(CHALLENGE_POLL_INTERVAL_MS)
        if not await is_blocked(page):
            print("   보안 확인 완료. 저장된 브라우저 세션을 다음 실행에도 재사용합니다.")
            return True
    return False


async def dismiss_consent(page):
    pattern = re.compile(
        r"accept all|allow all|i agree|got it|모두\s*수락|전체\s*동의|모두\s*동의|동의",
        re.IGNORECASE,
    )
    try:
        candidates = page.get_by_role("button", name=pattern)
        for index in range(min(await candidates.count(), CONSENT_MAX_BUTTONS)):
            button = candidates.nth(index)
            if await button.is_visible(timeout=CONSENT_VISIBLE_TIMEOUT_MS):
                await button.click(timeout=CONSENT_CLICK_TIMEOUT_MS)
                await page.wait_for_timeout(CONSENT_SETTLE_MS)
                return True
    except Exception:
        pass
    return False


async def expand_details(page):
    expanded = 0
    try:
        candidates = page.locator("button, [role=button], summary").filter(has_text=MORE_PATTERN)
        for index in range(min(await candidates.count(), DETAIL_EXPAND_MAX_BUTTONS)):
            target = candidates.nth(index)
            try:
                if await target.is_visible(timeout=DETAIL_EXPAND_VISIBLE_TIMEOUT_MS):
                    await target.click(timeout=DETAIL_EXPAND_CLICK_TIMEOUT_MS)
                    expanded += 1
                    await page.wait_for_timeout(DETAIL_EXPAND_SETTLE_MS)
            except Exception:
                continue
    except Exception:
        pass
    return expanded


async def wake_lazy_content(page):
    previous_height = 0
    stable = 0
    for _ in range(SCROLL_MAX_ATTEMPTS):
        try:
            height = await page.evaluate("document.documentElement.scrollHeight")
            await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        except Exception:
            break
        await page.wait_for_timeout(SCROLL_WAIT_MS)
        if height == previous_height:
            stable += 1
            if stable >= SCROLL_STABLE_ROUNDS:
                break
        else:
            stable = 0
            previous_height = height
    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


async def ensure_tables_ready(page):
    """스크롤이 멈춘 뒤에도 표가 하나도 안 잡히면, MISUMI 가격표처럼 스크롤 정지 후에야
    XHR로 늦게 채워지는 표일 수 있다."""
    try:
        if await page.locator("table").count() > 0:
            return
    except Exception:
        return

    for _ in range(TABLE_RETRY_ATTEMPTS):
        try:
            await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        except Exception:
            break
        await wait_for_network_settle(page)
        try:
            await page.locator("table").first.wait_for(
                state="attached", timeout=TABLE_WAIT_TIMEOUT_MS
            )
            break  # 표가 나타났다
        except Exception:
            continue  # 아직 없음 -> 다음 재시도

    try:
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


async def extract_tables(frame):
    return await frame.evaluate(
        """() => Array.from(document.querySelectorAll('table')).map((table, tableIndex) => ({
            table_index: tableIndex + 1,
            rows: Array.from(table.querySelectorAll('tr')).map(row =>
                Array.from(row.querySelectorAll('th,td')).map(cell => ({
                    text: cell.innerText.replace(/\\s+/g, ' ').trim(),
                    rowspan: Number(cell.getAttribute('rowspan') || 1),
                    colspan: Number(cell.getAttribute('colspan') || 1)
                }))
            ).filter(row => row.length)
        })).filter(table => table.rows.length)"""
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


async def save_page_sources(page):
    """DOM 텍스트와 테이블을 추출해 (table_count, dom_text, tables)를 반환한다."""
    text_sections = []
    tables = []
    for frame_index, frame in enumerate(page.frames):
        try:
            frame_text = (await frame.locator("body").inner_text(timeout=TEXT_EXTRACT_TIMEOUT_MS)).strip()
            if frame_text:
                label = "MAIN" if frame == page.main_frame else f"IFRAME {frame_index}"
                text_sections.append(f"[{label}]\n{frame_text}")
        except Exception:
            pass
        try:
            for table in await extract_tables(frame):
                table["frame_index"] = frame_index
                tables.append(table)
        except Exception:
            pass
    tables = merge_split_tables(tables)
    dom_text = "\n\n".join(text_sections)
    return len(tables), dom_text, tables


async def capture_ocr_assets(page, prefix, product_selector=None):
    """DOM으로 읽을 수 없는 이미지/Canvas만 개별 저장한다.
    product_selector가 주어지면 메인 프레임에서 해당 영역 안의 이미지만 스캔한다."""
    asset_dir = os.path.join(prefix, "assets")
    os.makedirs(asset_dir, exist_ok=True)
    manifest = []
    seen_sources = set()

    for frame_index, frame in enumerate(page.frames):
        if len(manifest) >= MAX_OCR_ASSETS_PER_PAGE:
            break
        # 메인 프레임에만 상품 영역 스코프를 적용한다.
        scope = product_selector if frame_index == 0 else None
        try:
            candidates = await frame.evaluate(_SCAN_MEDIA_JS, [MIN_OCR_ASSET_WIDTH, MIN_OCR_ASSET_HEIGHT, scope])
        except Exception:
            continue
        if not candidates:
            continue
        try:
            elements = frame.locator("img, canvas")
        except Exception:
            continue

        for item in candidates:
            if len(manifest) >= MAX_OCR_ASSETS_PER_PAGE:
                break
            # 쿼리 파라미터(CDN 리사이즈 등)가 달라도 같은 이미지로 처리한다.
            source = item["src"]
            if source:
                _p = urlparse(source)
                key = _p._replace(query="", fragment="").geturl()
            else:
                key = f"canvas:{frame_index}:{item['index']}:{item['width']}x{item['height']}"
            if key in seen_sources:
                continue
            seen_sources.add(key)

            filename = f"asset_{len(manifest) + 1:03d}_{item['tag']}.png"
            path = os.path.join(asset_dir, filename)
            try:
                # <img>는 브라우저 내부 fetch로 원본 다운로드 — element.screenshot()은
                # CSS overflow:hidden 등으로 이미지 상단이 잘릴 수 있다.
                # data:/blob: URL 또는 다운로드 실패 시 element.screenshot()으로 폴백.
                src = item.get("src", "")
                downloaded = False
                if item["tag"] == "img" and src and not src.startswith(("data:", "blob:")):
                    try:
                        b64 = await page.evaluate(
                            """async (src) => {
                                try {
                                    const r = await fetch(src, {credentials: 'include'});
                                    if (!r.ok) return null;
                                    const blob = await r.blob();
                                    return await new Promise(res => {
                                        const rd = new FileReader();
                                        rd.onloadend = () => res(rd.result);
                                        rd.readAsDataURL(blob);
                                    });
                                } catch (_) { return null; }
                            }""",
                            src,
                        )
                        if b64 and isinstance(b64, str) and "," in b64:
                            raw = base64.b64decode(b64.split(",", 1)[1])
                            with open(path, "wb") as f:
                                f.write(raw)
                            downloaded = True
                            print(f"   [fetch OK] {src[:80]} → {len(raw)//1024}KB")
                        else:
                            print(f"   [fetch FAIL] b64={type(b64)} src={src[:80]}")
                    except Exception as _e:
                        print(f"   [fetch ERR] ({src[:60]}): {_e}")
                # CORS·SSL 오류로 브라우저 fetch 실패 시 Python urllib로 재시도
                if not downloaded and item["tag"] == "img" and src and not src.startswith(("data:", "blob:")):
                    try:
                        _ssl_ctx = ssl.create_default_context()
                        _ssl_ctx.check_hostname = False
                        _ssl_ctx.verify_mode = ssl.CERT_NONE
                        _req = urllib.request.Request(src, headers={
                            "Referer": page.url,
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        })
                        def _fetch_sync():
                            with urllib.request.urlopen(_req, context=_ssl_ctx, timeout=30) as r:
                                return r.read()
                        raw = await asyncio.get_event_loop().run_in_executor(None, _fetch_sync)
                        with open(path, "wb") as f:
                            f.write(raw)
                        downloaded = True
                        print(f"   [urllib OK] {src[:80]} → {len(raw)//1024}KB")
                    except Exception as _e:
                        print(f"   [urllib ERR] ({src[:60]}): {_e}")
                if not downloaded:
                    element = elements.nth(item["index"])
                    await element.screenshot(
                        path=path, animations="disabled", timeout=ELEMENT_SCREENSHOT_TIMEOUT_MS
                    )
            except Exception:
                continue

            preprocess_image_for_ocr(path)
            manifest.append(
                {
                    "file": path,
                    "tag": item["tag"],
                    "src": item["src"],
                    "alt": item["alt"],
                    "frame_index": frame_index,
                    "width": item["width"],
                    "height": item["height"],
                }
            )

    manifest_path = os.path.join(prefix, "assets.json")
    with open(manifest_path, "w", encoding="utf-8") as output:
        json.dump(manifest, output, ensure_ascii=False, indent=2)
    return manifest


async def get_product_region_html(page, url):
    """사이트별 상품 본문 영역의 HTML을 반환한다 (context.md 작성용)."""
    host = urlparse(url).hostname or ""
    selectors = PRODUCT_REGION_SELECTORS.get(host, ["main"])
    for selector in selectors:
        try:
            region = page.locator(selector).first
            if not await region.is_visible(timeout=PRODUCT_REGION_VISIBLE_TIMEOUT_MS):
                continue
            box = await region.bounding_box()
            if not box or box["width"] < PRODUCT_REGION_MIN_WIDTH or box["height"] < PRODUCT_REGION_MIN_HEIGHT:
                continue
            return selector, await region.inner_html(timeout=TEXT_EXTRACT_TIMEOUT_MS)
        except Exception:
            continue
    return None, ""


def write_context_md(prefix, title, url, product_html, tables, dom_text):
    """DOM 텍스트·테이블·상품 영역을 LLM 친화적 Markdown 파일 하나로 통합 저장한다."""
    sections = [f"# {title or '(제목 없음)'}\n- URL: {url}"]

    if product_html:
        product_md = _html_to_md(product_html)
        if product_md:
            sections.append("## 상품 영역\n\n" + product_md)

    tables_md = _tables_to_markdown(tables)
    if tables_md:
        sections.append("## 규격 테이블\n" + tables_md)

    if dom_text:
        snippet = dom_text[:3000] + ("\n...(생략)" if len(dom_text) > 3000 else "")
        sections.append("## 전체 텍스트 (참고)\n\n" + snippet)

    with open(os.path.join(prefix, "context.md"), "w", encoding="utf-8") as output:
        output.write("\n\n".join(sections))


async def capture_one(page, url, index, total, output_dir):
    # 상품 하나당 전용 폴더({index}_{도메인}/) 하나에 저장한다.
    name = safe_name(url)
    prefix = os.path.join(output_dir, f"{index}_{name}")
    os.makedirs(prefix, exist_ok=True)
    print(f"\n[{index}/{total}] 접속: {url}")
    started = time.perf_counter()

    await warm_up(page, url)
    await page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    try:
        await page.wait_for_load_state("load", timeout=LOAD_STATE_TIMEOUT_MS)
    except Exception:
        pass
    await wait_for_network_settle(page)

    if await is_blocked(page) and not await wait_for_manual_challenge(page):
        elapsed = time.perf_counter() - started
        title = await page.title()
        metadata = {
            "url": url,
            "status": "blocked",
            "title": title,
            "elapsed_seconds": round(elapsed, 1),
        }
        with open(os.path.join(prefix, "metadata.json"), "w", encoding="utf-8") as output:
            json.dump(metadata, output, ensure_ascii=False, indent=2)
        print("   차단 화면이 유지되어 상품 캡처와 OCR 대상에서 제외했습니다.")
        print(f"   ⏱️  소요 시간: {elapsed:.1f}초")
        return "blocked"

    if await dismiss_consent(page):
        print("   쿠키 동의 창을 닫았습니다.")
    expanded = await expand_details(page)
    if expanded:
        print(f"   상세정보 버튼 {expanded}개를 펼쳤습니다.")
    await wake_lazy_content(page)
    await expand_details(page)
    await ensure_tables_ready(page)

    table_count, dom_text, tables = await save_page_sources(page)
    product_selector, product_html = await get_product_region_html(page, url)
    if product_selector:
        print(f"   상품 영역 감지: {product_selector} → 해당 영역 이미지만 캡처")
    ocr_assets = await capture_ocr_assets(page, prefix, product_selector)

    # 일부 사이트는 트래킹 파라미터(예: ?srsltid=...)가 붙으면 캡처 막바지에
    # 클라이언트 리다이렉트/팝업 등으로 페이지가 예기치 않게 닫혀 여기서부터
    # "Target page, context or browser has been closed" 오류가 난다. 이미
    # DOM 표·OCR 에셋은 위에서 다 수집됐으니, 마지막 title/url 조회만
    # 실패해도 그 데이터를 통째로 버리지 않도록 방어한다.
    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        final_url = page.url
    except Exception:
        final_url = url

    write_context_md(
        prefix=prefix,
        title=title,
        url=url,
        product_html=product_html,
        tables=tables,
        dom_text=dom_text,
    )

    elapsed = time.perf_counter() - started
    metadata = {
        "url": url,
        "status": "captured",
        "title": title,
        "final_url": final_url,
        "table_count": table_count,
        "ocr_asset_count": len(ocr_assets),
        "product_selector": product_selector,
        "context_file": os.path.join(prefix, "context.md"),
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(os.path.join(prefix, "metadata.json"), "w", encoding="utf-8") as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2)
    print(f"   캡처 완료: DOM 표 {table_count}개 / OCR 에셋 {len(ocr_assets)}개")
    print(f"   ⏱️  소요 시간: {elapsed:.1f}초")
    return "captured"


async def _run_capture_bot_async(run_ocr_and_extract=True, urls=None, output_dir=None):
    source = urls if urls is not None else TARGET_URLS
    urls = [
        url for url in source
        if not any(excluded.lower() in (urlparse(url).hostname or "").lower() for excluded in EXCLUDE_DOMAINS)
    ]
    if not urls:
        if source:
            print("캡처할 URL이 없습니다. 제외 도메인 목록을 확인하세요.")
        else:
            print("캡처할 URL이 없습니다. urls.txt를 확인하거나 터미널에서 URL을 직접 입력하세요.")
        return None

    if output_dir is None:
        output_dir = os.path.join(
            _ROOT, "crawl", "output", "cli_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        )
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    print(f"캡처 대상 {len(urls)}개 / 저장 위치: {output_dir}")

    pipeline_started = time.perf_counter()

    async with async_playwright() as playwright:
        # 실제 Chrome 프로필과 섞지 않는 전용 영구 프로필이다.
        context = await playwright.chromium.launch_persistent_context(
            BROWSER_PROFILE_DIR,
            channel="chrome",
            headless=HEADLESS,
            viewport=DEFAULT_VIEWPORT,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            args=["--start-maximized"],
        )
        await setup_resource_blocking(context)

        sem = asyncio.Semaphore(MAX_CONCURRENT_PAGES)
        total = len(urls)

        async def _capture_task(url, index):
            async with sem:
                page = await context.new_page()
                try:
                    return await capture_one(page, url, index, total, output_dir)
                except Exception as error:
                    print(f"   오류: {error}")
                    try:
                        error_dir = os.path.join(output_dir, f"{index}_{safe_name(url)}")
                        os.makedirs(error_dir, exist_ok=True)
                        await page.screenshot(
                            path=os.path.join(error_dir, "error.png"),
                            full_page=True,
                        )
                    except Exception:
                        pass
                    return "error"
                finally:
                    try:
                        await page.close()
                    except Exception:
                        pass

        tasks = [_capture_task(url, i) for i, url in enumerate(urls, 1)]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        results_raw = [
            "error" if isinstance(r, BaseException) else r
            for r in results_raw
        ]
        try:
            await context.close()
        except Exception:
            pass

    capture_elapsed = time.perf_counter() - pipeline_started
    results = [{"url": url, "status": status} for url, status in zip(urls, results_raw)]

    with open(os.path.join(output_dir, "capture_summary.json"), "w", encoding="utf-8") as output:
        json.dump(results, output, ensure_ascii=False, indent=2)
    print(f"\n캡처 완료: {output_dir}")
    print(f"⏱️  캡처 전체 소요 시간: {capture_elapsed:.1f}초 (평균 {capture_elapsed / len(urls):.1f}초/건)")

    if run_ocr_and_extract:
        from ocr import paddle_ocr
        from extract import extractor

        run_name = os.path.basename(output_dir)  # "cli_YYYYMMDD_HHMMSS"
        ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name)
        extract_dir = os.path.join(_ROOT, "extract", "output", run_name)

        paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)
        extractor.build_summary(output_dir, ocr_dir=ocr_dir, extract_dir=extract_dir)

    total_elapsed = time.perf_counter() - pipeline_started
    print(f"⏱️  전체 파이프라인 소요 시간: {total_elapsed:.1f}초")
    return output_dir


def run_capture_bot(run_ocr_and_extract=True, urls=None, output_dir=None):
    return asyncio.run(_run_capture_bot_async(
        run_ocr_and_extract=run_ocr_and_extract,
        urls=urls,
        output_dir=output_dir,
    ))


if __name__ == "__main__":
    run_capture_bot(run_ocr_and_extract=False)
