"""OCR로 얻은 텍스트 박스들을 좌표 기반으로 표(행/열) 구조로 재구성하는 로직.

상품정보제공고시처럼 '라벨-값'이 행으로 나열된 표를 다시 읽어내기 위해,
같은 줄(y좌표가 겹치는)에 있는 박스들을 행으로 묶고,
행 안에서는 x좌표 간격이 크게 벌어지는 지점을 열 경계로 판단해 셀로 합친다.
"""
from __future__ import annotations

from statistics import median
from typing import List

from .engine import TextBox

Row = List[str]


def _group_rows(boxes: List[TextBox], row_overlap_ratio: float = 0.5) -> List[List[TextBox]]:
    """y좌표가 서로 겹치는 텍스트 박스들을 같은 행으로 묶는다."""
    ordered = sorted(boxes, key=lambda b: b.y_center)
    rows: List[List[TextBox]] = []

    for box in ordered:
        placed = False
        for row in rows:
            row_y_min = min(b.y_min for b in row)
            row_y_max = max(b.y_max for b in row)
            overlap = min(box.y_max, row_y_max) - max(box.y_min, row_y_min)
            union_height = max(box.height, row_y_max - row_y_min, 1.0)
            if overlap / union_height >= row_overlap_ratio:
                row.append(box)
                placed = True
                break
        if not placed:
            rows.append([box])

    rows.sort(key=lambda row: min(b.y_min for b in row))
    return rows


def _split_cells(row: List[TextBox], gap_factor: float = 1.6) -> Row:
    """한 행 내에서 x좌표 간격이 큰 지점을 열 경계로 보고 셀 단위로 합친다."""
    ordered = sorted(row, key=lambda b: b.x_min)
    median_height = median(b.height for b in ordered) or 1.0
    gap_threshold = median_height * gap_factor

    cells: List[List[TextBox]] = [[ordered[0]]]
    for prev, cur in zip(ordered, ordered[1:]):
        gap = cur.x_min - prev.x_max
        if gap > gap_threshold:
            cells.append([cur])
        else:
            cells[-1].append(cur)

    return [" ".join(b.text for b in cell).strip() for cell in cells]


def reconstruct_table(boxes: List[TextBox]) -> List[Row]:
    """텍스트 박스 목록을 [[셀, 셀, ...], ...] 형태의 표(행 목록)로 재구성한다."""
    if not boxes:
        return []
    rows = _group_rows(boxes)
    return [_split_cells(row) for row in rows]
