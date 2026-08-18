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


SYSTEM_PROMPT = (
    "너는 이커머스/산업용 부품 상세페이지에서 핵심 상품정보만 뽑아내는 추출기다. "
    "아래 규칙을 반드시 지켜라.\n"
    "1. 입력된 텍스트(DOM/표/OCR)에 실제로 등장하는 정보만 사용한다. 없는 내용을 지어내지 않는다.\n"
    "2. 결과는 오직 JSON 객체 하나만 출력한다. 설명, 코드블록 표시(```) 등 다른 텍스트는 절대 포함하지 않는다.\n"
    "3. JSON 스키마: "
    '{"product_name": "string", "model": ["string", ...], "규격": ["string", ...]}\n'
    "4. product_name은 사이트 이름이나 카테고리명이 아니라 실제 상품명만 담는다. "
    "느낌표가 들어간 광고 카피, 홍보 문구, 슬로건('~의 혁명', '최저가', '단 하나뿐인' 등)은 "
    "상품명이 아니므로 절대 쓰지 않는다. 카탈로그에 실릴 법한 공식 품명만 담는다.\n"
    "5. model은 이 페이지가 다루는 상품 자체의 모델번호/형번/품번만 담는다. 페이지에 여러 옵션이 "
    "표로 나열되어 있어도, 이 URL이 가리키는 특정 옵션의 모델번호만 담고 무관한 변형을 나열하지 않는다. "
    "또한 product_name에 영문·숫자·하이픈·슬래시 조합의 코드(예: EQwear-EV3, MSFG-24/42-50/60-OD)가 "
    "포함되어 있으면 그 코드를 model에도 반드시 포함한다. "
    "단, model에 코드를 추가했다고 해서 product_name에서 그 코드를 제거하지 않는다. product_name은 원래 표현을 그대로 유지한다.\n"
    "6. 규격은 치수·크기·전압·전류·압력·온도·무게·재질·보호등급·호칭·색상·등급 등 "
    "이 상품의 물리적·기술적 특성과 선택 옵션에 해당하는 정보를 담는다. "
    "통관코드, 수출통제 코드(ECCN/AL), 라이프사이클 상태, 내부 제품군 코드, 출하 소요일 등 행정적·물류적 정보는 제외한다. "
    "이미 조합 형식(예: 0.8×5.0×100mm)으로 표현된 값이 있으면 그 조합을 이루는 개별 수치(0.8mm, 5.0mm, 100mm)는 따로 추가하지 않는다.\n"
    "7. model과 규격의 각 항목은 이 상품 자체를 직접 설명하는 단독 값이어야 한다. "
    "페이지 UI 버튼·메뉴 텍스트, 다른 상품과의 비교 목록, 탐색용 링크 텍스트는 상품 속성이 아니므로 절대 포함하지 않는다.\n"
    "8. 확실하지 않으면 해당 필드를 빈 문자열이나 빈 배열([])로 둔다. 애매하면 지어내지 말고 비워둬라."
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
        "규격": as_str_list(result.get("규격")),
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

    return {
        "URL": url,
        "상태": "captured",
        "상품명": product_name,
        "모델번호": model,
        "규격": [item["value"] for item in dedupe_keep_order(candidates["규격"])],
    }


def build_record_with_qwen(url, metadata, crawl_prefix, dom_text, product_dom_text, ocr_text):
    tables_text = _read_text(os.path.join(crawl_prefix, "tables.txt"))
    started = time.perf_counter()
    result = extract_with_qwen(
        url=url,
        title=metadata.get("title", ""),
        product_dom_text=product_dom_text,
        tables_text=tables_text,
        ocr_text=ocr_text,
        dom_text=dom_text,
    )
    elapsed = time.perf_counter() - started
    print(f"   🤖 Qwen 추출: {url} ({elapsed:.1f}초)")

    if not result["product_name"] and not result["model"] and not result["규격"]:
        # Qwen이 빈 결과를 준 경우(원문에서 못 찾았거나 응답이 비정상) 그대로 두지 않고
        # 규칙 기반으로 한 번 더 시도한다. 호출부(build_product_record)에서 처리한다.
        raise QwenExtractionError(f"Qwen이 빈 결과를 반환함: {url}")

    return {
        "URL": url,
        "상태": "captured",
        "상품명": result["product_name"],
        "모델번호": result["model"],
        "규격": result["규격"],
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
            "모델번호": [],
            "규격": [],
        }

    dom_text = _read_text(os.path.join(crawl_prefix, "dom.txt"))
    product_dom_text = _read_text(os.path.join(crawl_prefix, "product_dom.txt"))
    tables = _read_json(os.path.join(crawl_prefix, "tables.json"), [])

    # ocr_combined.txt는 ocr_dir(있으면) 또는 crawl_prefix에서 읽는다.
    if ocr_dir:
        rel = os.path.relpath(crawl_prefix, crawl_dir)
        ocr_text = _read_text(os.path.join(ocr_dir, rel, "ocr_combined.txt"))
    else:
        ocr_text = _read_text(os.path.join(crawl_prefix, "ocr_combined.txt"))

    if config.EXTRACTION_ENGINE == "qwen":
        try:
            return build_record_with_qwen(url, metadata, crawl_prefix, dom_text, product_dom_text, ocr_text)
        except Exception as error:
            print(f"   ⚠️  Qwen 추출 실패({error}) → 규칙 기반으로 대체합니다: {url}")

    started = time.perf_counter()
    result = build_record_with_rules(url, metadata, host, dom_text, product_dom_text, tables, ocr_text)
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
