"""캡쳐 이미지에서 재구성한 표(rows)로부터 상품명과 규격/사양 정보를 추출한다.

가격 정보는 이 파이프라인의 추출 대상이 아니므로, 가격으로 보이는 라벨은
규격/사양 표에 섞여 들어가지 않도록 걸러내는 용도로만 사용한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .engine import TextBox
from .table import Row, reconstruct_table

NAME_LABELS = ["상품명", "제품명", "품명", "모델명", "품목명"]
PRICE_LABELS = ["가격", "정가", "판매가", "할인가", "소비자가", "이벤트가", "쿠폰가", "즉시할인가"]


@dataclass
class ProductInfo:
    name: Optional[str] = None
    specs: Dict[str, str] = field(default_factory=dict)
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "specs": self.specs}


def _normalize(label: str) -> str:
    return label.replace(" ", "")


def _label_matches(label: str, keywords: List[str]) -> bool:
    label = _normalize(label)
    return any(_normalize(kw) in label for kw in keywords)


def _extract_name(rows: List[Row], boxes: List[TextBox]) -> Optional[str]:
    # 1) '상품명/제품명/품명/모델명' 같은 라벨-값 행을 우선적으로 찾는다.
    for row in rows:
        if len(row) >= 2 and _label_matches(row[0], NAME_LABELS):
            value = " ".join(cell for cell in row[1:]).strip()
            if value:
                return value

    # 2) 라벨을 못 찾으면 페이지 상단 30% 영역에서 글자 높이가 가장 큰
    #    텍스트(=폰트가 큰 제목일 가능성이 높음)를 상품명으로 추정한다.
    if not boxes:
        return None
    max_y = max(b.y_max for b in boxes)
    top_boxes = [b for b in boxes if b.y_center <= max_y * 0.3 and len(b.text.strip()) >= 2]
    if not top_boxes:
        return None
    best = max(top_boxes, key=lambda b: b.height)
    return best.text.strip() or None


def _extract_specs(rows: List[Row], name_value: Optional[str]) -> Dict[str, str]:
    """'라벨: 값' 형태의 2셀 행들을 규격/사양 후보로 모은다.

    가격 라벨, 상품명으로 이미 사용된 라벨/값, 라벨이 지나치게 긴(=일반
    문장일 가능성이 높은) 행은 제외한다.
    """
    specs: Dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        label = row[0].strip()
        value = " ".join(cell for cell in row[1:]).strip()
        if not label or not value:
            continue
        if _label_matches(label, PRICE_LABELS):
            continue
        if _label_matches(label, NAME_LABELS):
            continue
        if value == name_value:
            continue
        if len(label) > 12:
            continue
        specs[label] = value
    return specs


def extract_product_info(boxes: List[TextBox]) -> ProductInfo:
    rows = reconstruct_table(boxes)
    name = _extract_name(rows, boxes)
    specs = _extract_specs(rows, name)
    raw_text = " ".join(b.text for b in sorted(boxes, key=lambda b: (b.y_center, b.x_min)))
    return ProductInfo(name=name, specs=specs, raw_text=raw_text)
