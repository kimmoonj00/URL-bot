"""URL 리스트 -> 캡쳐 -> OCR -> 상품명/규격·사양 추출까지 이어주는 파이프라인.

캡쳐 로직(capture 패키지)과 OCR/정보추출 로직(ocr 패키지)은 서로 독립적이며,
이 파일은 둘을 순서대로 호출해 연결하는 역할만 한다.
"""
from __future__ import annotations

import os
import subprocess
import sys

if not sys.flags.utf8_mode:
    # 한국어 Windows(cp949) 콘솔에서 Playwright가 내부적으로 사용하는 파이프
    # 통신이 로케일 인코딩을 기본값으로 사용해 한글 title 등이 깨지는 문제가
    # 있어, UTF-8 모드 자식 프로세스로 재실행한다.
    # (os.execv는 Windows에서 실제 exec가 아니라 에뮬레이션이라 불안정하므로
    # subprocess로 실행하고 종료코드를 그대로 넘긴다.)
    os.environ["PYTHONUTF8"] = "1"
    result = subprocess.run([sys.executable, "-X", "utf8", __file__, *sys.argv[1:]])
    sys.exit(result.returncode)

import csv
import json
from pathlib import Path

from capture import capture_url
from ocr import PaddleOCREngine, extract_product_info, reconstruct_table, run_tiled

BASE_DIR = Path(__file__).resolve().parent
URLS_FILE = BASE_DIR / "config" / "urls.txt"
CAPTURE_DIR = BASE_DIR / "output" / "captures"
RESULT_DIR = BASE_DIR / "output" / "results"


def load_urls(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def run() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    urls = load_urls(URLS_FILE)
    if not urls:
        print(f"{URLS_FILE} 에 캡쳐할 URL을 한 줄에 하나씩 추가하세요.")
        return

    engine = PaddleOCREngine(lang="korean")
    summary_rows = []

    for url in urls:
        print(f"[캡쳐] {url}")
        capture = capture_url(url, CAPTURE_DIR)
        if not capture.ok:
            print(f"  -> 캡쳐 실패: {capture.error}")
            summary_rows.append({"url": url, "name": "", "specs": "", "error": capture.error})
            continue
        print(f"  -> 이미지 저장: {capture.image_path}")

        print("[OCR] 텍스트 추출 중... (상세페이지가 길면 타일로 나눠 처리)")
        boxes = run_tiled(engine, capture.image_path)
        info = extract_product_info(boxes)

        rows = reconstruct_table(boxes)
        text_path = RESULT_DIR / f"{capture.image_path.stem}.txt"
        text_path.write_text(
            "\n".join("\t".join(cell for cell in row) for row in rows),
            encoding="utf-8",
        )
        print(f"  -> OCR 텍스트 저장: {text_path}")

        result = {
            "url": url,
            "title": capture.title,
            "image_path": str(capture.image_path),
            "name": info.name,
            "specs": info.specs,
        }
        result_path = RESULT_DIR / f"{capture.image_path.stem}.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  -> 상품명: {info.name}")
        print(f"  -> 규격/사양: {info.specs}")
        print(f"  -> 결과 저장: {result_path}")

        summary_rows.append(
            {
                "url": url,
                "name": info.name or "",
                "specs": json.dumps(info.specs, ensure_ascii=False),
                "error": "",
            }
        )

    csv_path = RESULT_DIR / "summary.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["url", "name", "specs", "error"])
        writer.writeheader()
        writer.writerows(summary_rows)
    print(f"\n요약 CSV: {csv_path}")


if __name__ == "__main__":
    run()
