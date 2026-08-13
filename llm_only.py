"""output/results/의 OCR 텍스트(.txt) 파일들에 대해 LLM 추출만 수행해 확인한다."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from llm import extract_product_info_llm


def run(text_paths: list[str]) -> None:
    for text_path in text_paths:
        path = Path(text_path)
        raw_text = path.read_text(encoding="utf-8")
        print(f"\n[LLM] {path.name} ({len(raw_text)}자)")
        start = time.perf_counter()
        info = extract_product_info_llm(raw_text)
        elapsed = time.perf_counter() - start
        print(f"  -> {elapsed:.1f}초")
        print(f"  -> 상품명: {info.name}")
        print(f"  -> 규격/사양: {json.dumps(info.specs, ensure_ascii=False)}")


if __name__ == "__main__":
    run(sys.argv[1:])
