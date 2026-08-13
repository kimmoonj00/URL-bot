"""
로컬 Ollama에서 구동 중인 Qwen에게 캡처된 텍스트를 보내
상품명/모델번호/사이즈/사양을 JSON으로 추출받는 모듈.

Ollama가 꺼져있거나 응답이 이상하면 예외를 던진다 — 호출하는 쪽
(extract_info.py)에서 이 예외를 잡아 규칙 기반 추출로 폴백한다.
"""

import json
import re

import requests

import config


class QwenExtractionError(Exception):
    pass


SYSTEM_PROMPT = (
    "너는 이커머스/산업용 부품 상세페이지에서 핵심 상품정보만 뽑아내는 추출기다. "
    "아래 규칙을 반드시 지켜라.\n"
    "1. 입력된 텍스트(DOM/표/OCR)에 실제로 등장하는 정보만 사용한다. 없는 내용을 지어내지 않는다.\n"
    "2. 결과는 오직 JSON 객체 하나만 출력한다. 설명, 코드블록 표시(```) 등 다른 텍스트는 절대 포함하지 않는다.\n"
    "3. JSON 스키마: "
    '{"product_name": "string", "model": ["string", ...], "size": ["string", ...], "spec": ["string", ...]}\n'
    "4. product_name은 사이트 이름이나 카테고리명이 아니라 실제 상품명만 담는다. "
    "느낌표가 들어간 광고 카피, 홍보 문구, 슬로건('~의 혁명', '최저가', '단 하나뿐인' 등)은 "
    "상품명이 아니므로 절대 쓰지 않는다. 카탈로그에 실릴 법한 공식 품명만 담는다.\n"
    "5. model은 이 페이지가 다루는 상품 자체의 모델번호/형번/품번만 담는다. 페이지에 여러 옵션이 "
    "표로 나열되어 있어도, 이 URL이 가리키는 특정 옵션의 모델번호만 담고 무관한 변형을 나열하지 않는다.\n"
    "6. size는 규격/치수/사이즈 정보를 담는다.\n"
    "7. 확실하지 않으면 해당 필드를 빈 문자열이나 빈 배열([])로 둔다. 애매하면 지어내지 말고 비워둬라."
)

USER_PROMPT_TEMPLATE = """URL: {url}

[페이지 제목]
{title}

[상품 영역 DOM 텍스트]
{product_dom}

[표 데이터]
{tables}

[이미지 OCR 텍스트]
{ocr}

[페이지 전체 DOM 텍스트 (참고용, 앞부분만)]
{dom}

위 정보를 바탕으로 JSON 하나만 출력해."""


def _truncate(text, limit=None):
    limit = limit or config.OLLAMA_MAX_SOURCE_CHARS
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit] + "\n...(생략)"
    return text or "(내용 없음)"


def _extract_json_object(raw_text):
    """모델이 JSON 앞뒤에 잡담을 붙이는 경우를 대비해 첫 { ~ 마지막 } 구간만 추린다."""
    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if not match:
        raise QwenExtractionError(f"응답에서 JSON을 찾지 못함: {raw_text[:200]!r}")
    return json.loads(match.group(0))


def call_ollama(messages):
    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "format": "json",
        "stream": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0,
            "num_predict": config.OLLAMA_NUM_PREDICT,
        },
    }
    try:
        response = requests.post(url, json=payload, timeout=config.OLLAMA_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.exceptions.ConnectionError as error:
        raise QwenExtractionError(
            f"Ollama({config.OLLAMA_BASE_URL})에 연결할 수 없습니다. "
            f"'ollama serve'가 실행 중인지, 모델이 'ollama pull {config.OLLAMA_MODEL}'로 "
            f"받아져 있는지 확인하세요. 원본 오류: {error}"
        ) from error
    except requests.exceptions.Timeout as error:
        raise QwenExtractionError(f"Ollama 응답 시간 초과({config.OLLAMA_TIMEOUT_SECONDS}초): {error}") from error
    except requests.exceptions.HTTPError as error:
        raise QwenExtractionError(f"Ollama 호출 실패({response.status_code}): {response.text[:300]}") from error

    body = response.json()
    content = body.get("message", {}).get("content", "")
    if not content.strip():
        raise QwenExtractionError(f"Ollama가 빈 응답을 반환함: {body}")
    return _extract_json_object(content)


def extract_with_qwen(url, title, product_dom_text, tables_text, ocr_text, dom_text):
    user_prompt = USER_PROMPT_TEMPLATE.format(
        url=url,
        title=title or "(제목 없음)",
        product_dom=_truncate(product_dom_text),
        tables=_truncate(tables_text),
        ocr=_truncate(ocr_text),
        # 전체 페이지 DOM은 메뉴/광고 등 상품과 무관한 텍스트가 섞여 작은 모델을
        # 혼란시킬 수 있어 참고용으로만 짧게 자른다. 핵심 정보는 대부분
        # product_dom/tables/ocr에 이미 담겨 있다.
        dom=_truncate(dom_text, limit=800),
    )
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    result = call_ollama(messages)

    if not isinstance(result, dict):
        raise QwenExtractionError(f"JSON 객체가 아닌 응답: {result!r}")

    def as_str_list(value):
        if value is None:
            return []
        if isinstance(value, str):
            items = [value]
        elif isinstance(value, list):
            items = [str(v) for v in value]
        else:
            items = [str(value)]
        # 중복 제거(순서 유지) + 비정상적으로 긴 값 방어(모델이 원문을 통째로
        # 베껴 쓰는 경우가 드물게 있어 값 하나가 지나치게 길면 잘라낸다).
        cleaned = []
        seen = set()
        for item in items:
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            cleaned.append(item[:150])
        return cleaned

    return {
        "product_name": str(result.get("product_name", "")).strip()[:200],
        "model": as_str_list(result.get("model")),
        "size": as_str_list(result.get("size")),
        "spec": as_str_list(result.get("spec")),
    }
