"""
캡처(crawl/crawler.py) + OCR(ocr/paddle_ocr.py) 결과물을 모아
상품별로 상품명·모델번호·사이즈·사양·가격을 뽑아내는 모듈.

입력: crawler.py가 만든 output/capture_YYYYMMDD_HHMMSS/ 폴더
출력: extract/output/capture_YYYYMMDD_HHMMSS/{domain}.json (사이트별)
      같은 도메인의 URL이 여러 개면 한 파일 안에 배열로 포함.
"""

import glob
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, unquote

import importlib.util as _ilu

_SELF = os.path.dirname(os.path.abspath(__file__))  # extract/
_ROOT = os.path.dirname(_SELF)                       # 루트
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# crawler.py가 먼저 crawl/config.py를 sys.modules['config']에 등록하므로
# importlib으로 경로를 직접 지정해 캐시 충돌을 피한다.
_cfg = _ilu.spec_from_file_location("extract_config", os.path.join(_SELF, "config.py"))
config = _ilu.module_from_spec(_cfg)
_cfg.loader.exec_module(config)

# 사이트 이름/구분자를 <title> 텍스트에서 잘라내기 위한 패턴.
# "상품명 - 사이트명", "상품명 | 사이트명", "카테고리 > 상품명::사이트명" 등을 처리한다.
TITLE_SPLIT_PATTERN = re.compile(r"\s*[|｜:：>›≫»]\s*|\s+-\s+")

LABEL_VALUE_LINE = re.compile(r"^\s*([^\t:：]{1,20}?)\s*[:：]\s*(\S.{0,120})\s*$")
LABEL_VALUE_TAB = re.compile(r"^\s*([^\t]{1,20})\t+(\S.{0,120})\s*$")

SPEC_VALUE_PATTERNS = [re.compile(p) for p in config.SPEC_VALUE_PATTERNS]


# ── LLM 추출 (Ollama / Qwen) ─────────────────────────────────────────────────

class QwenExtractionError(Exception):
    pass


# few-shot 예시: (user_input, assistant_output) 쌍
# 규칙만으로 Qwen이 놓치는 두 가지 패턴을 예시로 직접 보여준다.
FEW_SHOT_EXAMPLES = [
    # 예시 1: 다중 variant 테이블 → 모델별 규격 분리 + 라벨 유지
    (
        "URL: https://example.com/driver/\n\n"
        "[페이지 제목]\n일자 드라이버 (334)\n\n"
        "[페이지 컨텍스트 (상품 영역 · 규격 테이블 · 전체 텍스트)]\n"
        "## 규격 테이블\n\n"
        "| 두형 | 규격(mm) | 날장(mm) | 전장(mm) | 원산지 | 모델명 |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 일자 | 5 | 100 | 198 | 체코 | 05007610001 |\n"
        "| 일자 | 6 | 150 | 255 | 체코 | 05340330001 |\n\n"
        "[이미지 OCR 텍스트]\n(내용 없음)\n\n위 정보를 바탕으로 JSON 하나만 출력해.",
        '{"product_name": "일자 드라이버 (334)", "variants": ['
        '{"model": "05007610001", "규격": ["규격: 5mm", "날장: 100mm", "전장: 198mm", "원산지: 체코"]}, '
        '{"model": "05340330001", "규격": ["규격: 6mm", "날장: 150mm", "전장: 255mm", "원산지: 체코"]}]}',
    ),
    # 예시 2: 행정/물류 정보가 섞인 페이지 → 물리 규격만 추출
    (
        "URL: https://example.com/product/500-033260\n\n"
        "[페이지 제목]\nDPU - Device Programmer / Test Unit\n\n"
        "[페이지 컨텍스트 (상품 영역 · 규격 테이블 · 전체 텍스트)]\n"
        "모델: 500-033260\n"
        "무게: 4.321 lb\n"
        "치수: 18.95 x 25.75 x 6.70 IN\n"
        "PLM 상태: PM300:Active Product\n"
        "ECCN: AL:N / EAR99\n"
        "출하 소요일: 1 Day\n"
        "통관코드: 8537109170\n"
        "원산지: United States of America\n"
        "RoHS: 해당없음\n\n"
        "[이미지 OCR 텍스트]\n(내용 없음)\n\n위 정보를 바탕으로 JSON 하나만 출력해.",
        '{"product_name": "DPU - Device Programmer / Test Unit", "variants": ['
        '{"model": "500-033260", "규격": ["무게: 4.321 lb", "치수: 18.95 x 25.75 x 6.70 IN", "원산지: United States of America"]}]}',
    ),
]

SYSTEM_PROMPT = (
    "너는 이커머스/산업용 부품 상세페이지에서 핵심 상품정보만 뽑아내는 추출기다. "
    "아래 규칙을 반드시 지켜라.\n"
    "1. 입력된 텍스트(DOM/표/OCR)에 실제로 등장하는 정보만 사용한다. 없는 내용을 지어내지 않는다.\n"
    "2. 결과는 오직 JSON 객체 하나만 출력한다. 설명, 코드블록 표시(```) 등 다른 텍스트는 절대 포함하지 않는다.\n"
    "3. JSON 스키마: "
    '{"product_name": "string", "variants": [{"model": "string", "규격": ["string", ...]}, ...]}\n'
    "variants는 모델번호 하나당 항목 하나다. 모델번호가 1개이면 variants에 항목이 1개다. "
    "모델번호를 알 수 없으면 model을 빈 문자열(\"\")로 두고 알 수 있는 규격만 담는다.\n"
    "4. product_name은 사이트 이름이나 카테고리명이 아니라 실제 상품명만 담는다. "
    "느낌표가 들어간 광고 카피, 홍보 문구, 슬로건('~의 혁명', '최저가', '단 하나뿐인' 등)은 "
    "상품명이 아니므로 절대 쓰지 않는다. 카탈로그에 실릴 법한 공식 품명만 담는다.\n"
    "5. 각 variant의 model에는 그 변형의 모델번호/형번/품번만 담는다. "
    "페이지에 여러 옵션이 표로 나열되어 있으면 각 행(옵션)마다 variant 항목을 하나씩 만들고 "
    "그 행에만 해당하는 규격을 해당 variant의 규격 배열에 담는다. "
    "또한 product_name에 영문·숫자·하이픈·슬래시 조합의 코드(예: EQwear-EV3, MSFG-24/42-50/60-OD)가 "
    "포함되어 있으면 그 코드를 variants[0].model에도 반드시 포함한다. "
    "단, product_name에서 그 코드를 제거하지 않는다. product_name은 원래 표현을 그대로 유지한다.\n"
    "6. 각 variant의 규격에는 그 모델번호에만 해당하는 치수·크기·전압·전류·압력·온도·무게·재질·"
    "보호등급·호칭·색상·등급 등 물리적·기술적 특성을 담는다. "
    "통관코드, 수출통제 코드(ECCN/AL), 라이프사이클 상태, 내부 제품군 코드, 출하 소요일 등 행정적·물류적 정보는 제외한다. "
    "이미 조합 형식(예: 0.8×5.0×100mm)으로 표현된 값이 있으면 그 조합을 이루는 개별 수치(0.8mm, 5.0mm, 100mm)는 따로 추가하지 않는다.\n"
    "7. 각 variant의 model과 규격 항목은 그 상품을 직접 설명하는 단독 값이어야 한다. "
    "페이지 UI 버튼·메뉴 텍스트, 다른 상품과의 비교 목록, 탐색용 링크 텍스트는 상품 속성이 아니므로 절대 포함하지 않는다.\n"
    "8. 확실하지 않으면 해당 필드를 빈 문자열이나 빈 배열([])로 둔다. 애매하면 지어내지 말고 비워둬라."
)

USER_PROMPT_TEMPLATE = """URL: {url}

[페이지 제목]
{title}

[페이지 컨텍스트 (상품 영역 · 규격 테이블 · 전체 텍스트)]
{context}

[이미지 OCR 텍스트]
{ocr}

위 정보를 바탕으로 JSON 하나만 출력해."""


def _truncate(text, limit=None):
    limit = limit or config.OLLAMA_MAX_SOURCE_CHARS
    text = (text or "").strip()
    if len(text) > limit:
        return text[:limit] + "\n...(생략)"
    return text or "(내용 없음)"


def _extract_json_object(raw_text):
    """모델이 JSON 앞뒤에 잡담을 붙이거나 잘린 경우를 모두 처리한다."""
    from json_repair import repair_json

    match = re.search(r"\{.*\}", raw_text, re.DOTALL)
    if match:
        raw_json = match.group(0)
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError:
            return json.loads(repair_json(raw_json))

    # JSON이 잘려 닫는 }가 없는 경우 → repair_json으로 복구 시도
    stripped = raw_text.strip()
    if stripped.startswith("{"):
        repaired = repair_json(stripped)
        if repaired:
            return json.loads(repaired)

    raise QwenExtractionError(f"응답에서 JSON을 찾지 못함: {raw_text[:200]!r}")


_OLLAMA_CONNECT_RETRIES = 3
_OLLAMA_CONNECT_WAIT = 8  # 초

def call_gpt(messages):
    from openai import OpenAI
    if not config.OPENAI_API_KEY:
        raise QwenExtractionError("OPENAI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
    client = OpenAI(api_key=config.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=config.OPENAI_MODEL,
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
        max_tokens=config.OPENAI_MAX_TOKENS,
    )
    content = response.choices[0].message.content
    if not content or not content.strip():
        raise QwenExtractionError("GPT가 빈 응답을 반환함")
    return json.loads(content)


def call_ollama(messages):
    import requests

    url = f"{config.OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {
        "model": config.OLLAMA_MODEL,
        "messages": messages,
        "format": "json",
        "stream": False,
        "think": False,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
        "options": {
            "temperature": 0,
            "num_predict": config.OLLAMA_NUM_PREDICT,
            "num_ctx": 12288,
        },
    }
    for attempt in range(_OLLAMA_CONNECT_RETRIES):
        try:
            response = requests.post(url, json=payload, timeout=config.OLLAMA_TIMEOUT_SECONDS)
            response.raise_for_status()
            break
        except requests.exceptions.ConnectionError as error:
            if attempt < _OLLAMA_CONNECT_RETRIES - 1:
                print(f"   ⚠️  Ollama 연결 실패, {_OLLAMA_CONNECT_WAIT}초 후 재시도 ({attempt + 1}/{_OLLAMA_CONNECT_RETRIES - 1})...")
                time.sleep(_OLLAMA_CONNECT_WAIT)
                continue
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


def extract_with_gpt(url, title, context_text, ocr_text):
    user_prompt = USER_PROMPT_TEMPLATE.format(
        url=url,
        title=title or "(제목 없음)",
        context=_truncate(context_text, config.OPENAI_MAX_SOURCE_CHARS),
        ocr=_truncate(ocr_text, config.OPENAI_MAX_SOURCE_CHARS),
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_user, ex_assistant in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_assistant})
    messages.append({"role": "user", "content": user_prompt})
    result = call_gpt(messages)

    if not isinstance(result, dict):
        raise QwenExtractionError(f"JSON 객체가 아닌 응답: {result!r}")

    def as_str_list(value):
        if value is None:
            return []
        items = [value] if isinstance(value, str) else [str(v) for v in value] if isinstance(value, list) else [str(value)]
        cleaned, seen = [], set()
        for item in items:
            item = item.strip()
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item[:150])
        return cleaned

    product_name = str(result.get("product_name", "")).strip()[:200]
    variants_raw = result.get("variants")
    if isinstance(variants_raw, list) and variants_raw:
        variants = [
            {"model": str(v.get("model", "")).strip()[:200], "규격": as_str_list(v.get("규격"))}
            for v in variants_raw if isinstance(v, dict)
        ]
    else:
        models = as_str_list(result.get("model")) or [""]
        specs = as_str_list(result.get("규격"))
        variants = [{"model": m, "규격": specs} for m in models]

    return {"product_name": product_name, "variants": variants}


def extract_with_qwen(url, title, context_text, ocr_text):
    user_prompt = USER_PROMPT_TEMPLATE.format(
        url=url,
        title=title or "(제목 없음)",
        context=_truncate(context_text),
        ocr=_truncate(ocr_text),
    )
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex_user, ex_assistant in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": ex_user})
        messages.append({"role": "assistant", "content": ex_assistant})
    messages.append({"role": "user", "content": user_prompt})
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
        cleaned = []
        seen = set()
        for item in items:
            item = item.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            cleaned.append(item[:150])
        return cleaned

    product_name = str(result.get("product_name", "")).strip()[:200]

    # 새 스키마: variants 배열
    variants_raw = result.get("variants")
    if isinstance(variants_raw, list) and variants_raw:
        variants = []
        for v in variants_raw:
            if not isinstance(v, dict):
                continue
            model = str(v.get("model", "")).strip()[:200]
            specs = as_str_list(v.get("규격"))
            variants.append({"model": model, "규격": specs})
    else:
        # 구버전 응답(model + 규격 flat) 호환 처리
        models = as_str_list(result.get("model")) or [""]
        specs = as_str_list(result.get("규격"))
        variants = [{"model": m, "규격": specs} for m in models]

    return {
        "product_name": product_name,
        "variants": variants,
    }


# ── 규칙 기반 추출 ────────────────────────────────────────────────────────────

def _normalize_label(label):
    return re.sub(r"\s+", "", label).strip().lower()


def classify_label(label):
    """라벨 문자열이 SPEC_LABEL_KEYWORDS의 어느 카테고리(model/size/spec)에
    속하는지 판단한다. 매칭 안 되면 None."""
    norm = _normalize_label(label)
    if not norm:
        return None
    for category, keywords in config.SPEC_LABEL_KEYWORDS.items():
        for keyword in keywords:
            if _normalize_label(keyword) in norm:
                return category
    return None


def clean_title(raw_title, host):
    """<title> 텍스트에서 사이트명/구분자를 제거해 상품명만 남긴다."""
    if not raw_title:
        return ""
    parts = [p.strip() for p in TITLE_SPLIT_PATTERN.split(raw_title) if p.strip()]
    if not parts:
        return raw_title.strip()
    # 사이트명은 보통 가장 짧거나 host 문자열을 포함하는 조각이다. 그런 조각은 버린다.
    host_root = host.split(".")[0] if host else ""
    candidates = [
        p for p in parts
        if host_root.lower() not in p.lower().replace(" ", "")
    ]
    if not candidates:
        candidates = parts
    # 가장 긴 조각이 보통 실제 상품명이다 (사이트명은 짧게 붙는 경우가 많음).
    return max(candidates, key=len)


def extract_label_value_from_text(text):
    """DOM/OCR 텍스트 라인에서 'label: value' 또는 'label\tvalue' 패턴을 찾는다."""
    pairs = []
    if not text:
        return pairs
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = LABEL_VALUE_TAB.match(line) or LABEL_VALUE_LINE.match(line)
        if match:
            label, value = match.group(1).strip(), match.group(2).strip()
            if label and value:
                pairs.append((label, value))
    return pairs


def extract_label_value_from_table(table):
    """표 구조(rows: [[{text,...}, ...], ...])에서 라벨:값 쌍을 뽑는다.
    두 가지 표 형태를 모두 처리한다:
      A) 각 행이 2셀(라벨, 값)로 된 세로형 스펙 표
      B) 1행은 헤더(라벨들), 다음 행(들)은 그 아래 정렬된 값인 가로형 표
    """
    pairs = []
    rows = table.get("rows", [])
    if not rows:
        return pairs

    # A) 세로형: 모든 행이 2셀
    if all(len(row) == 2 for row in rows) and len(rows) >= 1:
        for row in rows:
            label = row[0]["text"].strip()
            value = row[1]["text"].strip()
            if label and value:
                pairs.append((label, value))
        return pairs

    # B) 가로형: 첫 행을 헤더로 보고 이후 행들과 열 인덱스로 매칭
    header = rows[0]
    data_rows = rows[1:]
    if data_rows and len(header) == len(data_rows[0]):
        for col_index, header_cell in enumerate(header):
            label = header_cell["text"].strip()
            values = [
                row[col_index]["text"].strip()
                for row in data_rows
                if col_index < len(row) and row[col_index]["text"].strip()
            ]
            if label and values:
                # 동일 열에 값이 여러 행 있으면 '/'로 합쳐 후보로 남긴다.
                pairs.append((label, " / ".join(dict.fromkeys(values))))
    return pairs


def extract_model_from_url(url):
    """URL 마지막 경로 조각이 모델번호처럼 보이면 폴백 후보로 사용한다.
    (스웨즈락 등 카탈로그성 사이트는 URL 자체에 모델번호를 담는 경우가 많다)"""
    path = unquote(urlparse(url).path).rstrip("/")
    if not path:
        return None
    last_segment = path.split("/")[-1]
    for pattern in SPEC_VALUE_PATTERNS:
        if pattern.fullmatch(last_segment) or pattern.search(last_segment):
            return last_segment
    return None


def find_product_name(metadata, product_dom_text, dom_text, host):
    """우선순위: 사이트별 선택자로 찾은 <title> 정제값 > 상품 영역 첫 줄 > DOM 첫 줄."""
    title = clean_title(metadata.get("title", ""), host)
    if title and len(title) >= 4:
        return title, "title"

    for source_name, text in (("product_dom", product_dom_text), ("dom", dom_text)):
        for line in (text or "").splitlines():
            line = line.strip()
            if len(line) >= 4:
                return line, source_name
    return "", "unknown"


def gather_spec_candidates(product_dom_text, tables, ocr_text):
    """여러 소스에서 label:value 후보를 모아 (category -> [(value, source), ...]) 형태로 반환."""
    found = {"model": [], "규격": []}

    for table in tables:
        for label, value in extract_label_value_from_table(table):
            category = classify_label(label)
            if category:
                found[category].append((value, f"table#{table.get('table_index')}"))

    for source_name, text in (("product_dom", product_dom_text), ("ocr", ocr_text)):
        for label, value in extract_label_value_from_text(text):
            category = classify_label(label)
            if category:
                found[category].append((value, source_name))

    return found


def dedupe_keep_order(items):
    seen = set()
    result = []
    for value, source in items:
        key = value.strip()
        if key and key not in seen:
            seen.add(key)
            result.append({"value": key, "source": source})
    return result


# ── 파이프라인 ────────────────────────────────────────────────────────────────

def _read_text(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    return ""


def _read_json(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    return default


def build_record_with_rules(url, metadata, host, dom_text, product_dom_text, tables, ocr_text):
    product_name, _name_source = find_product_name(metadata, product_dom_text, dom_text, host)
    candidates = gather_spec_candidates(product_dom_text, tables, ocr_text)

    model = [item["value"] for item in dedupe_keep_order(candidates["model"])]
    if not model:
        url_model = extract_model_from_url(url)
        if url_model:
            model = [url_model]

    specs = [item["value"] for item in dedupe_keep_order(candidates["규격"])]
    # 규칙 기반은 모델별 규격 분리가 불가능하므로 모든 모델이 같은 규격을 공유한다.
    if model:
        variants = [{"model": m, "규격": specs} for m in model]
    else:
        variants = [{"model": "", "규격": specs}]

    return {
        "URL": url,
        "상태": "captured",
        "상품명": product_name,
        "variants": variants,
    }


def build_record_with_gpt(url, metadata, context_text, ocr_text):
    started = time.perf_counter()
    result = extract_with_gpt(
        url=url,
        title=metadata.get("title", ""),
        context_text=context_text,
        ocr_text=ocr_text,
    )
    elapsed = time.perf_counter() - started
    print(f"   🤖 GPT 추출: {url} ({elapsed:.1f}초)")

    if not result["product_name"] and not result["variants"]:
        raise QwenExtractionError(f"GPT가 빈 결과를 반환함: {url}")

    return {
        "URL": url,
        "상태": "captured",
        "상품명": result["product_name"],
        "variants": result["variants"],
    }


def build_record_with_qwen(url, metadata, context_text, ocr_text):
    started = time.perf_counter()
    result = extract_with_qwen(
        url=url,
        title=metadata.get("title", ""),
        context_text=context_text,
        ocr_text=ocr_text,
    )
    elapsed = time.perf_counter() - started
    print(f"   🤖 Qwen 추출: {url} ({elapsed:.1f}초)")

    if not result["product_name"] and not result["variants"]:
        raise QwenExtractionError(f"Qwen이 빈 결과를 반환함: {url}")

    return {
        "URL": url,
        "상태": "captured",
        "상품명": result["product_name"],
        "variants": result["variants"],
    }


def build_product_record(metadata_path, crawl_dir, ocr_dir=None):
    crawl_prefix = os.path.dirname(metadata_path)
    metadata = _read_json(metadata_path, {})
    url = metadata.get("url", "")
    host = urlparse(url).hostname or ""

    if metadata.get("status") != "captured":
        return {
            "URL": url,
            "상태": metadata.get("status", "unknown"),
            "상품명": "",
            "variants": [],
        }

    context_text = _read_text(os.path.join(crawl_prefix, "context.md"))
    # 구버전 출력(context.md 없음) 하위 호환: 이전 파일들로 컨텍스트를 재조합한다.
    if not context_text:
        product_dom = _read_text(os.path.join(crawl_prefix, "product_dom.txt"))
        tables_txt = _read_text(os.path.join(crawl_prefix, "tables.txt"))
        dom_txt = _read_text(os.path.join(crawl_prefix, "dom.txt"))
        context_text = "\n\n".join(filter(None, [product_dom, tables_txt, dom_txt[:2000]]))

    # ocr 단계가 완료됐으면 context.md + OCR을 합친 product.md가 있다.
    # 있으면 그걸 통째로 쓰고, 없으면 crawl context.md만 쓴다.
    ocr_text = ""
    if ocr_dir:
        rel = os.path.relpath(crawl_prefix, crawl_dir)
        product_md = _read_text(os.path.join(ocr_dir, rel, "product.md"))
        if product_md:
            context_text = product_md  # context + OCR 통합본

    if config.EXTRACTION_ENGINE == "gpt":
        try:
            return build_record_with_gpt(url, metadata, context_text, ocr_text)
        except Exception as error:
            print(f"   ⚠️  GPT 추출 실패({error}) → 규칙 기반으로 대체합니다: {url}")
    elif config.EXTRACTION_ENGINE == "qwen":
        try:
            return build_record_with_qwen(url, metadata, context_text, ocr_text)
        except Exception as error:
            print(f"   ⚠️  Qwen 추출 실패({error}) → 규칙 기반으로 대체합니다: {url}")

    # rules-based 폴백: context_text를 dom_text로 사용 (product_dom은 context 안에 포함)
    started = time.perf_counter()
    result = build_record_with_rules(url, metadata, host, context_text, "", [], ocr_text)
    elapsed = time.perf_counter() - started
    print(f"   📋 규칙 기반 추출: {url} ({elapsed:.2f}초)")
    return result


def build_summary(crawl_dir, ocr_dir=None, extract_dir=None):
    """crawl_dir의 metadata를 읽고 상품 정보를 추출해 사이트별 JSON으로 저장한다.
    같은 도메인 URL이 여러 개면 한 파일 안에 배열로 모은다.
    extract_dir 미지정 시 extract/output/<run_name>/ 을 자동으로 사용한다."""
    if extract_dir is None:
        run_name = os.path.basename(os.path.abspath(crawl_dir))
        base_dir = os.path.join(_ROOT, "extract", "output", run_name)
        extract_dir = base_dir
        counter = 1
        while os.path.exists(extract_dir) and os.listdir(extract_dir):
            extract_dir = f"{base_dir}({counter})"
            counter += 1
    os.makedirs(extract_dir, exist_ok=True)

    started = time.perf_counter()
    metadata_paths = sorted(glob.glob(os.path.join(crawl_dir, "*", "metadata.json")))
    if not metadata_paths:
        raise FileNotFoundError(f"'{crawl_dir}'에서 metadata.json 파일을 찾을 수 없습니다.")

    # URL별 소요시간 측정
    records = []
    url_timings = []  # [(url, elapsed), ...]
    for path in metadata_paths:
        t0 = time.perf_counter()
        record = build_product_record(path, crawl_dir, ocr_dir)
        url_timings.append((record["URL"], time.perf_counter() - t0))
        records.append(record)

    # 도메인별로 묶어 {domain}.json 파일 저장 + 사이트별 소요시간 집계
    by_domain = {}
    site_elapsed = {}  # host -> 누적 소요시간
    for record, (_, elapsed) in zip(records, url_timings):
        host = urlparse(record["URL"]).hostname or "unknown"
        by_domain.setdefault(host, []).append(record)
        site_elapsed[host] = site_elapsed.get(host, 0.0) + elapsed

    for host, site_records in by_domain.items():
        slug = host.replace(".", "_")
        json_path = os.path.join(extract_dir, f"{slug}.json")
        with open(json_path, "w", encoding="utf-8") as handle:
            json.dump(site_records, handle, ensure_ascii=False, indent=2)
        print(f"  📄 {host} ({len(site_records)}개) → {json_path}")

    total_elapsed = time.perf_counter() - started

    # ── 사이트별 소요시간 요약 ──────────────────────────────────────────────────
    print()
    print("─" * 60)
    print(f"{'사이트':<35} {'URL 수':>5}  {'소요시간':>8}")
    print("─" * 60)
    for host, site_records in by_domain.items():
        t = site_elapsed.get(host, 0.0)
        print(f"  {host:<33} {len(site_records):>5}개  {t:>6.2f}초")
    print("─" * 60)
    print(f"  {'합계':<33} {len(records):>5}건  {total_elapsed:>6.2f}초")
    print("─" * 60)
    print()

    print(f"상품정보 추출 완료: {len(records)}건 / {len(by_domain)}개 사이트 → {extract_dir}")
    return by_domain


def find_latest_capture_dir(base=None):
    base = base or os.path.join(_ROOT, "crawl", "output")
    candidates = sorted(glob.glob(os.path.join(base, "capture_*")))
    if not candidates:
        raise FileNotFoundError(f"'{base}'에서 capture_* 폴더를 찾을 수 없습니다. main.py를 먼저 실행하세요.")
    return candidates[-1]


if __name__ == "__main__":
    crawl_target = sys.argv[1] if len(sys.argv) > 1 else find_latest_capture_dir()
    run_name = os.path.basename(os.path.abspath(crawl_target))
    ocr_target = os.path.join(_ROOT, "ocr", "output", run_name)
    build_summary(crawl_target, ocr_dir=ocr_target if os.path.exists(ocr_target) else None)
