"""매우 긴 상세페이지 캡쳐 이미지를 겹치는 타일로 나눠 OCR을 수행하고,
좌표를 원본 이미지 기준으로 합치는 로직.

상세페이지 이미지는 세로 길이가 수만 픽셀에 달할 수 있어 한 번에 OCR을
돌리면 처리 시간이 급격히 늘어나거나 메모리 문제로 실패할 수 있다.
일정 높이로 겹치게 잘라 각각 처리한 뒤, 겹치는 영역은 위/아래 타일 중
가운데 지점을 기준으로 한쪽에만 귀속시켜 중복 없이 병합한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

import numpy as np
from PIL import Image

from .engine import PaddleOCREngine, TextBox

DEFAULT_TILE_HEIGHT = 3000
DEFAULT_OVERLAP = 200
# 이 높이 이하인 이미지는 타일링 없이 통째로 처리한다.
TILE_THRESHOLD = 3500


def _shift(box: TextBox, dy: float) -> TextBox:
    return TextBox(
        text=box.text,
        confidence=box.confidence,
        box=[[x, y + dy] for x, y in box.box],
    )


def run_tiled(
    engine: PaddleOCREngine,
    image_path: Path,
    tile_height: int = DEFAULT_TILE_HEIGHT,
    overlap: int = DEFAULT_OVERLAP,
) -> List[TextBox]:
    """이미지를 필요 시 타일로 나눠 OCR을 수행하고 좌표를 합쳐 반환한다."""
    with Image.open(image_path) as original:
        image = original.convert("RGB")
        width, height = image.size

        if height <= TILE_THRESHOLD:
            return engine.run(np.array(image))

        stride = tile_height - overlap
        boxes: List[TextBox] = []
        y_start = 0

        while True:
            y_end = min(y_start + tile_height, height)
            is_first = y_start == 0
            is_last = y_end >= height

            tile = image.crop((0, y_start, width, y_end))
            for box in engine.run(np.array(tile)):
                shifted = _shift(box, y_start)
                low = y_start if is_first else y_start + overlap / 2
                high = y_end if is_last else y_end - overlap / 2
                if low <= shifted.y_center <= high:
                    boxes.append(shifted)

            if is_last:
                break
            y_start += stride

    return boxes
