"""
캡처(crawl/crawler.py) + OCR(ocr/paddle_ocr.py) 결과물을 모아
상품별로 '정확한 상품명'과 '규격(모델번호/사이즈/사양)'을 뽑아내는 모듈.

입력: crawler.py가 만든 output/capture_YYYYMMDD_HHMMSS/ 폴더
      (상품마다 {index}_{domain}/ 전용 폴더가 있고 그 안에 metadata.json,
       dom.txt, tables.json, product_dom.txt 가 있다. paddle_ocr.py를
       먼저 돌렸다면 같은 폴더에 ocr_combined.txt 도 있다)
출력: 같은 폴더에 products_summary.json / products_summary.txt

규칙 기반(정규식 + 키워드 매칭)이라 100% 정확하지는 않다. 각 필드에 어떤
소스(table/dom/ocr/url/title)에서 나왔는지 함께 기록해 사람이 빠르게
검수할 수 있게 했다.
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
if _SELF not in sys.path:
    sys.path.insert(0, _SELF)  # qwen_extract import 경로용

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
    found = {"model": [], "size": [], "spec": []}

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
        "사이즈": [item["value"] for item in dedupe_keep_order(candidates["size"])],
        "사양": [item["value"] for item in dedupe_keep_order(candidates["spec"])],
    }


def build_record_with_qwen(url, metadata, crawl_prefix, dom_text, product_dom_text, ocr_text):
    import qwen_extract  # Ollama 미사용 시 requests 등 불필요한 의존성을 피하려 지연 import

    tables_text = _read_text(os.path.join(crawl_prefix, "tables.txt"))
    started = time.perf_counter()
    result = qwen_extract.extract_with_qwen(
        url=url,
        title=metadata.get("title", ""),
        product_dom_text=product_dom_text,
        tables_text=tables_text,
        ocr_text=ocr_text,
        dom_text=dom_text,
    )
    elapsed = time.perf_counter() - started
    print(f"   🤖 Qwen 추출: {url} ({elapsed:.1f}초)")

    if not result["product_name"] and not result["model"] and not result["size"] and not result["spec"]:
        # Qwen이 빈 결과를 준 경우(원문에서 못 찾았거나 응답이 비정상) 그대로 두지 않고
        # 규칙 기반으로 한 번 더 시도한다. 호출부(build_product_record)에서 처리한다.
        raise qwen_extract.QwenExtractionError(f"Qwen이 빈 결과를 반환함: {url}")

    return {
        "URL": url,
        "상태": "captured",
        "상품명": result["product_name"],
        "모델번호": result["model"],
        "사이즈": result["size"],
        "사양": result["spec"],
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
            "사이즈": [],
            "사양": [],
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
    """crawl_dir의 metadata를 읽고, ocr_dir의 OCR 텍스트를 합쳐 extract_dir에 요약 파일을 저장한다.
    extract_dir 미지정 시 extract/output/<run_name>/ 을 자동으로 사용한다."""
    if extract_dir is None:
        run_name = os.path.basename(os.path.abspath(crawl_dir))
        extract_dir = os.path.join(_ROOT, "extract", "output", run_name)
    os.makedirs(extract_dir, exist_ok=True)

    started = time.perf_counter()
    metadata_paths = sorted(glob.glob(os.path.join(crawl_dir, "*", "metadata.json")))
    if not metadata_paths:
        raise FileNotFoundError(f"'{crawl_dir}'에서 metadata.json 파일을 찾을 수 없습니다.")

    records = [build_product_record(path, crawl_dir, ocr_dir) for path in metadata_paths]

    json_path = os.path.join(extract_dir, "products_summary.json")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)

    text_path = os.path.join(extract_dir, "products_summary.txt")
    with open(text_path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(f"URL: {record['URL']}\n")
            handle.write(f"상태: {record['상태']}\n")
            if record["상태"] == "captured":
                handle.write(f"상품명: {record['상품명'] or '-'}\n")
                handle.write(f"모델번호: {', '.join(record['모델번호']) or '-'}\n")
                handle.write(f"사이즈: {', '.join(record['사이즈']) or '-'}\n")
                handle.write(f"사양: {', '.join(record['사양']) or '-'}\n")
            handle.write("\n")

    elapsed = time.perf_counter() - started
    print(f"상품정보 추출 완료: {len(records)}건 → {json_path}")
    print(f"⏱️  추출 소요 시간: {elapsed:.2f}초")
    return records


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
