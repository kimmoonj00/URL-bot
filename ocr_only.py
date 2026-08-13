"""output/captures/의 최근 캡쳐 이미지들에 대해 OCR만 수행해 결과를 확인한다.

LLM 추출 전, OCR 인식 자체가 잘 되는지 점검하기 위한 용도.
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

from ocr import (
    PaddleOCREngine,
    correct_spacing,
    filter_by_confidence,
    reconstruct_table,
    run_tiled,
)

BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "output" / "results"

CONFIDENCE_THRESHOLD = 0.5


def run(image_paths: list[str]) -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    engine = PaddleOCREngine(lang="korean")

    for image_path in image_paths:
        path = Path(image_path)
        print(f"\n[OCR] {path.name}")
        start = time.perf_counter()
        boxes = run_tiled(engine, path)
        total = len(boxes)
        boxes = filter_by_confidence(boxes, CONFIDENCE_THRESHOLD)
        kept = len(boxes)
        elapsed = time.perf_counter() - start

        rows = reconstruct_table(boxes)
        raw_text = "\n".join(
            "\t".join(correct_spacing(cell) for cell in row) for row in rows
        )
        text_path = RESULT_DIR / f"{path.stem}.txt"
        text_path.write_text(raw_text, encoding="utf-8")

        avg_conf = sum(b.confidence for b in boxes) / kept if kept else 0.0
        print(f"  -> {elapsed:.1f}초, 박스 {total}개 중 {kept}개 유지 (평균 신뢰도 {avg_conf:.3f})")
        print(f"  -> 텍스트 저장: {text_path}")


if __name__ == "__main__":
    run(sys.argv[1:])
