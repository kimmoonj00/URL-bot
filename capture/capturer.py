"""상품 URL을 열어 페이지 전체를 스크린샷으로 캡쳐하고 저장하는 로직.

OCR/파싱 로직과는 완전히 분리되어 있으며, 이 모듈의 결과물은
디스크에 저장된 이미지 파일(및 메타데이터)뿐이다.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from playwright.sync_api import Page, sync_playwright

# 상품 캡쳐를 가리는 팝업/배너/쿠키 안내 등을 제거하기 위한 선택자
POPUP_SELECTORS = [
    "[class*='popup' i]",
    "[class*='modal' i]",
    "[class*='layer' i]",
    "[id*='popup' i]",
    "[class*='banner' i]",
    "[class*='cookie' i]",
    "[class*='sticky' i]",
    "iframe[src*='ad']",
]


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


def _remove_popups(page: Page) -> None:
    for selector in POPUP_SELECTORS:
        try:
            page.evaluate(
                "(sel) => document.querySelectorAll(sel).forEach(el => el.remove())",
                selector,
            )
        except Exception:
            # 선택자가 페이지 구조와 맞지 않아도 캡쳐 자체는 계속 진행한다
            continue


def _autoscroll(page: Page, step: int = 800, wait_ms: int = 200, max_steps: int = 60) -> None:
    """lazy-load 콘텐츠가 전부 로드되도록 페이지 끝까지 스크롤한 뒤 맨 위로 복귀."""
    for _ in range(max_steps):
        reached_bottom = page.evaluate(
            """(step) => {
                const before = window.scrollY;
                window.scrollBy(0, step);
                return window.scrollY === before;
            }""",
            step,
        )
        page.wait_for_timeout(wait_ms)
        if reached_bottom:
            break
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(wait_ms)


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

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(
                viewport={"width": 1440, "height": 900},
                device_scale_factor=scale,
            )
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            title = page.title()

            _autoscroll(page)
            _remove_popups(page)
            page.wait_for_timeout(500)

            filename = f"{_slugify(title)}_{captured_at}.png"
            image_path = output_dir / filename
            page.screenshot(path=str(image_path), full_page=True)

            browser.close()

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
