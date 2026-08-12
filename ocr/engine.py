"""PaddleOCR 엔진 래퍼.

이 파일은 '이미지 -> (텍스트, 신뢰도, 좌표) 목록' 변환만 책임지고,
표 재구성이나 상품 정보 파싱 같은 의미 해석은 하지 않는다.
"""
from __future__ import annotations

import os

# Windows CPU 환경에서 paddlepaddle 3.x 기본 실행모드(mkldnn)가 일부 연산에서
# NotImplementedError(oneDNN PIR 속성 변환 미지원)를 던지는 문제가 있어 기본값을
# 끈다. paddleocr/paddlex를 import하기 전에 설정해야 반영된다.
os.environ.setdefault("PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT", "False")

from dataclasses import dataclass
from pathlib import Path
from typing import List, Union

import numpy as np
from paddleocr import PaddleOCR

ImageInput = Union[str, Path, np.ndarray]


@dataclass
class TextBox:
    text: str
    confidence: float
    box: List[List[float]]  # 좌상단부터 시계방향 4점 [[x,y],[x,y],[x,y],[x,y]]

    @property
    def x_min(self) -> float:
        return min(p[0] for p in self.box)

    @property
    def x_max(self) -> float:
        return max(p[0] for p in self.box)

    @property
    def y_min(self) -> float:
        return min(p[1] for p in self.box)

    @property
    def y_max(self) -> float:
        return max(p[1] for p in self.box)

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def y_center(self) -> float:
        return (self.y_min + self.y_max) / 2

    @property
    def x_center(self) -> float:
        return (self.x_min + self.x_max) / 2


class PaddleOCREngine:
    """PaddleOCR 인스턴스를 감싸 이미지 -> TextBox 리스트 변환만 제공한다.

    캡쳐 이미지는 이미 똑바로 서 있는 디지털 스크린샷이라 문서방향 분류/
    언워핑/텍스트라인 방향 보정 같은 전처리가 필요 없다. 기본으로 꺼서
    불필요한 모델 로딩·추론을 없애 속도를 높인다. 감지 모델의 입력 리사이즈
    한도(text_det_limit_side_len)와 인식 배치 크기도 조절 가능하게 열어둔다.

    주의: paddleocr==3.0.0 기준 기본 모델 세대인 PP-OCRv5는 한글 인식 모델이
    없어 lang="korean"이 무시되고 중국어/영어 모델로 인식이 깨진다
    (paddleocr/_pipelines/ocr.py의 `_get_ocr_model_names`가 PP-OCRv5일 때
    lang을 아예 보지 않음). 한글을 지원하는 PP-OCRv3 세대로 고정한다.
    """

    def __init__(
        self,
        lang: str = "korean",
        det_limit_side_len: int = 1536,
        rec_batch_size: int = 16,
    ):
        self._ocr = PaddleOCR(
            lang=lang,
            ocr_version="PP-OCRv3",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_limit_side_len=det_limit_side_len,
            text_det_limit_type="max",
            text_recognition_batch_size=rec_batch_size,
        )

    def run(self, image: ImageInput) -> List[TextBox]:
        src = str(image) if isinstance(image, (str, Path)) else image
        result = self._ocr.predict(src)
        if not result:
            return []

        page = result[0]
        texts = page.get("rec_texts") or []
        scores = page.get("rec_scores") or []
        raw_boxes = page.get("rec_boxes")
        raw_boxes = raw_boxes.tolist() if raw_boxes is not None else []

        text_boxes: List[TextBox] = []
        for text, score, box in zip(texts, scores, raw_boxes):
            x1, y1, x2, y2 = (float(v) for v in box)
            text_boxes.append(
                TextBox(
                    text=text,
                    confidence=float(score),
                    box=[[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                )
            )
        return text_boxes
