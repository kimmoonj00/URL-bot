"""output/results/의 OCR 텍스트(.txt) 파일들에 대해 LLM 추출만 수행해
결과를 JSON 파일로 저장한다. 모델별로 비교할 수 있도록 파일명에 모델명을
붙인다 (예: foo.txt -> foo__qwen2.5-3b.json).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import time

from llm.extractor import MODEL, extract_product_info_llm


def run(text_paths: list[str], model: str) -> None:
    model_tag = model.replace(":", "-").replace("/", "-")

    for text_path in text_paths:
        path = Path(text_path)
        raw_text = path.read_text(encoding="utf-8")
        print(f"\n[LLM:{model}] {path.name} ({len(raw_text)}자)")
        start = time.perf_counter()
        info = extract_product_info_llm(raw_text, model=model)
        elapsed = time.perf_counter() - start

        result = {
            "model": model,
            "elapsed_sec": round(elapsed, 1),
            "name": info.name,
            "specs": info.specs,
        }
        out_path = path.with_name(f"{path.stem}__{model_tag}.json")
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"  -> {elapsed:.1f}초")
        print(f"  -> 상품명: {info.name}")
        print(f"  -> 규격/사양: {json.dumps(info.specs, ensure_ascii=False)}")
        print(f"  -> 저장: {out_path}")


if __name__ == "__main__":
    args = sys.argv[1:]
    model_arg = MODEL
    if args and args[0] == "--model":
        model_arg = args[1]
        args = args[2:]
    run(args, model_arg)
