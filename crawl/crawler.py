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

from config import (
    BASE_DIR,
    BROWSER_PROFILE_DIR,
    DEFAULT_VIEWPORT,
    EXCLUDE_DOMAINS,
    HEADLESS,
    MANUAL_CHALLENGE_WAIT_SECONDS,
    MAX_OCR_ASSETS_PER_PAGE,
    MIN_OCR_ASSET_HEIGHT,
    MIN_OCR_ASSET_WIDTH,
    PRODUCT_REGION_SELECTORS,
    TARGET_URLS,
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
        sample = f"{page.title()} {page.locator('body').inner_text(timeout=3000)[:1500]}"
        return bool(BLOCKED_PATTERN.search(sample))
    except Exception:
        return False


def warm_up(page, url):
    host = urlparse(url).hostname or ""
    warmup = WARMUP_URLS.get(host)
    if not warmup:
        return
    print(f"   워밍업 방문: {warmup}")
    try:
        page.goto(warmup, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(2000)
    except Exception as error:
        print(f"   워밍업 실패(상세 페이지는 계속 진행): {error}")


def wait_for_manual_challenge(page):
    """표시 브라우저에서 사용자가 사이트의 정상 확인 절차를 마칠 시간을 준다."""
    if HEADLESS or not is_blocked(page):
        return not is_blocked(page)

    print("   보안 확인 화면입니다. 열린 Chrome에서 정상 확인 절차를 완료하세요.")
    deadline = time.time() + MANUAL_CHALLENGE_WAIT_SECONDS
    while time.time() < deadline:
        page.wait_for_timeout(2000)
        if not is_blocked(page):
            print("   보안 확인 완료. 저장된 브라우저 세션을 다음 실행에도 재사용합니다.")
            return True
    return False


def dismiss_consent(page):
    pattern = re.compile(
        r"accept all|allow all|i agree|got it|모두\s*수락|전체\s*동의|모두\s*동의|동의",
        re.IGNORECASE,
    )
    try:
        candidates = page.get_by_role("button", name=pattern)
        for index in range(min(candidates.count(), 5)):
            button = candidates.nth(index)
            if button.is_visible(timeout=500):
                button.click(timeout=2000)
                page.wait_for_timeout(500)
                return True
    except Exception:
        pass
    return False


def expand_details(page):
    expanded = 0
    try:
        candidates = page.locator("button, [role=button], summary").filter(has_text=MORE_PATTERN)
        for index in range(min(candidates.count(), 8)):
            target = candidates.nth(index)
            try:
                if target.is_visible(timeout=300):
                    target.click(timeout=1500)
                    expanded += 1
                    page.wait_for_timeout(500)
            except Exception:
                continue
    except Exception:
        pass
    return expanded


def wake_lazy_content(page):
    previous_height = 0
    stable = 0
    for _ in range(18):
        try:
            height = page.evaluate("document.documentElement.scrollHeight")
            page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        except Exception:
            break
        page.wait_for_timeout(800)
        if height == previous_height:
            stable += 1
            if stable >= 3:
                break
        else:
            stable = 0
            previous_height = height
    try:
        page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass


def extract_tables(frame):
    return frame.evaluate(
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


def save_page_sources(page, prefix):
    text_sections = []
    tables = []
    for frame_index, frame in enumerate(page.frames):
        try:
            frame_text = frame.locator("body").inner_text(timeout=5000).strip()
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
    visible_text = "\n\n".join(text_sections)
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
    """DOM으로 읽을 수 없는 이미지/Canvas만 개별 저장한다."""
    asset_dir = os.path.join(prefix, "assets")
    os.makedirs(asset_dir, exist_ok=True)
    manifest = []
    seen_sources = set()

    for frame_index, frame in enumerate(page.frames):
        try:
            elements = frame.locator("img, canvas")
            count = elements.count()
        except Exception:
            continue
        for element_index in range(count):
            if len(manifest) >= MAX_OCR_ASSETS_PER_PAGE:
                break
            element = elements.nth(element_index)
            try:
                if not element.is_visible(timeout=300):
                    continue
                box = element.bounding_box()
                if not box:
                    continue
                if box["width"] < MIN_OCR_ASSET_WIDTH or box["height"] < MIN_OCR_ASSET_HEIGHT:
                    continue
                tag = element.evaluate("node => node.tagName.toLowerCase()")
                source = element.evaluate(
                    "node => node.tagName.toLowerCase() === 'img' ? (node.currentSrc || node.src || '') : ''"
                )
                key = source or f"canvas:{frame_index}:{element_index}:{round(box['width'])}x{round(box['height'])}"
                if key in seen_sources:
                    continue
                seen_sources.add(key)
                filename = f"asset_{len(manifest) + 1:03d}_{tag}.png"
                path = os.path.join(asset_dir, filename)
                element.screenshot(path=path, animations="disabled")
                manifest.append(
                    {
                        "file": path,
                        "tag": tag,
                        "src": source,
                        "alt": element.get_attribute("alt") or "",
                        "frame_index": frame_index,
                        "width": round(box["width"]),
                        "height": round(box["height"]),
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
    """사이트별 상품 본문만 별도 저장해 메뉴·광고가 OCR을 방해하지 않게 한다."""
    host = urlparse(url).hostname or ""
    selectors = PRODUCT_REGION_SELECTORS.get(host, ["main"])
    for selector in selectors:
        try:
            region = page.locator(selector).first
            if not region.is_visible(timeout=800):
                continue
            box = region.bounding_box()
            if not box or box["width"] < 300 or box["height"] < 150:
                continue
            path = os.path.join(prefix, "product.png")
            region.screenshot(path=path, animations="disabled")
            with open(os.path.join(prefix, "product_dom.txt"), "w", encoding="utf-8") as output:
                output.write(region.inner_text(timeout=5000))
            return path, selector
        except Exception:
            continue
    return None, None


def capture_one(page, url, index, total, output_dir):
    # 상품 하나당 파일을 흩뿌리지 않고 전용 폴더({index}_{도메인}/) 하나에 모은다.
    # 예: output_dir/1_kr_misumi-ec_com/{dom.txt, tables.json, assets/, metadata.json, ...}
    name = safe_name(url)
    prefix = os.path.join(output_dir, f"{index}_{name}")
    os.makedirs(prefix, exist_ok=True)
    print(f"\n[{index}/{total}] 접속: {url}")
    started = time.perf_counter()

    warm_up(page, url)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    try:
        page.wait_for_load_state("load", timeout=20000)
    except Exception:
        pass
    page.wait_for_timeout(2000)

    if is_blocked(page) and not wait_for_manual_challenge(page):
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
    expand_details(page)

    table_count = save_page_sources(page, prefix)
    ocr_assets = capture_ocr_assets(page, prefix)
    product_path, product_selector = capture_product_region(page, url, prefix)

    elapsed = time.perf_counter() - started
    metadata = {
        "url": url,
        "status": "captured",
        "title": page.title(),
        "final_url": page.url,
        "table_count": table_count,
        "ocr_asset_count": len(ocr_assets),
        "ocr_assets_manifest": os.path.join(prefix, "assets.json"),
        "product_screenshot": product_path,
        "product_selector": product_selector,
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(os.path.join(prefix, "metadata.json"), "w", encoding="utf-8") as output:
        json.dump(metadata, output, ensure_ascii=False, indent=2)
    print(f"   캡처 완료: DOM 표 {table_count}개 / OCR 에셋 {len(ocr_assets)}개")
    print(f"   ⏱️  소요 시간: {elapsed:.1f}초")
    return "captured"


def run_capture_bot(run_ocr_and_extract=True):
    urls = [
        url for url in TARGET_URLS
        if not any(excluded.lower() in (urlparse(url).hostname or "").lower() for excluded in EXCLUDE_DOMAINS)
    ]
    if not urls:
        print("캡처할 URL이 없습니다. urls.txt를 확인하세요.")
        return

    output_dir = os.path.join(
        _ROOT, "crawl", "output", "capture_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(BROWSER_PROFILE_DIR, exist_ok=True)
    print(f"캡처 대상 {len(urls)}개 / 저장 위치: {output_dir}")

    pipeline_started = time.perf_counter()
    results = []
    with sync_playwright() as playwright:
        # 실제 Chrome 프로필과 섞지 않는 전용 영구 프로필이다. 정상 로그인/보안 확인 상태만 재사용한다.
        context = playwright.chromium.launch_persistent_context(
            BROWSER_PROFILE_DIR,
            channel="chrome",
            headless=HEADLESS,
            viewport=DEFAULT_VIEWPORT,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            args=["--start-maximized"],
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
        # (paddleocr 미설치 환경에서는 이 단계에서 ImportError가 나므로 그 경우
        #  run_ocr_and_extract=False로 main.py만 먼저 돌리고 ocr/paddle_ocr.py를 따로 실행할 것)
        from ocr import paddle_ocr
        from extract import extract_info

        run_name = os.path.basename(output_dir)  # "capture_YYYYMMDD_HHMMSS"
        ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name)
        extract_dir = os.path.join(_ROOT, "extract", "output", run_name)

        paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)
        extract_info.build_summary(output_dir, ocr_dir=ocr_dir, extract_dir=extract_dir)

    total_elapsed = time.perf_counter() - pipeline_started
    print(f"⏱️  전체 파이프라인 소요 시간: {total_elapsed:.1f}초")


if __name__ == "__main__":
    run_capture_bot()
