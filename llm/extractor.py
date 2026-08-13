"""Ollama로 로컬 LLM(Qwen2.5)을 호출해 OCR 원본 텍스트에서
상품명과 규격/사양만 추출하는 로직.

좌표 기반 휴리스틱(ocr/parser.py)은 사이트마다 다른 표 구조(다중 열
그리드, 라벨-값이 아닌 형태)와 네비게이션/배너 텍스트 혼입에 취약해,
텍스트 의미를 이해해 걸러낼 수 있는 LLM으로 대체한다.
"""
from __future__ import annotations

import json

import ollama

from ocr.parser import ProductInfo

MODEL = "qwen2.5:3b"

SYSTEM_PROMPT = """너는 이커머스 상품 상세페이지를 OCR로 읽은 텍스트에서 상품 정보를 추출하는 도우미다.
입력 텍스트에는 실제 상품 정보 외에 로그인/회원가입/검색/장바구니, 네비게이션 메뉴,
광고 배너, 추천상품/함께보면좋은상품, 배송·반품·교환 안내, 상품평/문의, 회사소개,
사업자등록번호 같은 상품과 무관한 텍스트가 섞여 있다. 이런 텍스트는 모두 무시하고
실제 상품명과 규격/사양(모델명, 크기, 색상, 재질, 원산지 등)만 추출해라.

반드시 아래 JSON 형식으로만 답하라:
{"name": "상품명 문자열 또는 null", "specs": {"규격 라벨": "값", ...}}"""


def extract_product_info_llm(raw_text: str, model: str = MODEL) -> ProductInfo:
    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": raw_text},
        ],
        format="json",
        options={"temperature": 0, "num_ctx": 16384},
    )
    content = response["message"]["content"]

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return ProductInfo(name=None, specs={}, raw_text=raw_text)

    name = data.get("name") or None
    specs = data.get("specs") or {}
    if not isinstance(specs, dict):
        specs = {}
    return ProductInfo(name=name, specs=specs, raw_text=raw_text)
