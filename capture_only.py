"""urls.txt의 URL들을 캡쳐만 수행하고, URL별 소요 시간을 측정해 출력한다.

OCR/LLM 없이 캡쳐 단계 자체의 성능을 확인하기 위한 용도.
"""
from __future__ import annotations

import os
import subprocess
import sys

if not sys.flags.utf8_mode:
    os.environ["PYTHONUTF8"] = "1"
    result = subprocess.run([sys.executable, "-X", "utf8", __file__, *sys.argv[1:]])
    sys.exit(result.returncode)

import time
from pathlib import Path

from capture import capture_url

BASE_DIR = Path(__file__).resolve().parent
URLS_FILE = BASE_DIR / "config" / "urls.txt"
CAPTURE_DIR = BASE_DIR / "output" / "captures"


def load_urls(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def run() -> None:
    urls = load_urls(URLS_FILE)
    if not urls:
        print(f"{URLS_FILE} 에 캡쳐할 URL을 한 줄에 하나씩 추가하세요.")
        return

    timings: list[tuple[str, float, bool, str]] = []
    for url in urls:
        print(f"[캡쳐] {url}")
        start = time.perf_counter()
        capture = capture_url(url, CAPTURE_DIR)
        elapsed = time.perf_counter() - start
        timings.append((url, elapsed, capture.ok, capture.error or ""))
        status = "성공" if capture.ok else f"실패: {capture.error}"
        print(f"  -> {elapsed:.1f}초, {status}")

    print("\n--- URL별 소요 시간 요약 ---")
    for url, elapsed, ok, error in timings:
        mark = "OK" if ok else "FAIL"
        print(f"{elapsed:7.1f}초  {mark}  {url}")

    total = sum(elapsed for _, elapsed, _, _ in timings)
    print(f"\n총 {len(urls)}건, 합계 {total:.1f}초, 평균 {total / len(urls):.1f}초")


if __name__ == "__main__":
    run()
