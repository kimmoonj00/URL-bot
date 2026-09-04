"""
크롤/OCR/추출 결과를 archive/{source}/YYYY-MM-DD/HHMMSSmmm/ 에 저장하는 공유 모듈.
URL 하나당 폴더 하나 ({domain}_{short_uuid}) 구조로 저장.
slack_bot.py, server.py 등에서 동일하게 사용.
"""

import glob as _glob
import json
import os
import shutil
import threading
import uuid as _uuid

_ROOT = os.path.dirname(os.path.abspath(__file__))
_lock = threading.Lock()


def save(source: str, run_name: str, run_ocr: bool, by_domain: dict) -> str:
    """
    source: "slack" | "gui" | "cli"
    run_name: "slack_20260903_112218834" 형식 (접두사_날짜_시간밀리초)
    run_ocr: OCR 실행 여부
    by_domain: build_summary() 반환값

    Returns: 생성된 archive 경로
    """
    parts = run_name.split("_")  # ["slack", "20260903", "112218834"]
    if len(parts) < 3:
        raise ValueError(f"run_name 형식 오류: {run_name}")
    raw_date, raw_time = parts[1], parts[2]
    date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

    archive_base = os.path.join(_ROOT, "archive", source, date_str, raw_time)
    os.makedirs(archive_base, exist_ok=True)

    crawl_base = os.path.join(_ROOT, "crawl", "output", run_name)
    ocr_base = os.path.join(_ROOT, "ocr", "output", run_name) if run_ocr else None

    # meta.json
    all_urls = [rec.get("URL", "") for recs in by_domain.values() for rec in recs]
    with open(os.path.join(archive_base, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"run_name": run_name, "source": source, "run_ocr": run_ocr,
                   "created_at": f"{date_str}T{raw_time}", "urls": all_urls},
                  f, ensure_ascii=False, indent=2)

    index_entries = []

    if os.path.isdir(crawl_base):
        for entry in os.scandir(crawl_base):
            if not entry.is_dir():
                continue
            slug_parts = entry.name.split("_", 1)
            if len(slug_parts) < 2:
                continue
            domain_slug = slug_parts[1]           # "www_navimro_com"
            hostname = domain_slug.replace("_", ".")  # "www.navimro.com"

            # 이 서브폴더에 해당하는 URL 읽기
            meta_path = os.path.join(crawl_base, entry.name, "metadata.json")
            entry_url = ""
            if os.path.isfile(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    entry_url = json.load(f).get("url", "")

            # URL에 매칭되는 LLM 레코드 찾기
            domain_records = by_domain.get(hostname) or next(
                (v for k, v in by_domain.items() if hostname in k or k in hostname), [])
            record = next((r for r in domain_records if r.get("URL") == entry_url), None)
            if record is None and domain_records:
                record = domain_records[0]

            # URL별 고유 폴더: {domain_slug}_{short_uuid}
            short_id = _uuid.uuid4().hex[:6]
            folder_name = f"{domain_slug}_{short_id}"
            domain_archive = os.path.join(archive_base, folder_name)
            os.makedirs(domain_archive, exist_ok=True)

            # product.md 복사 (OCR 있으면 OCR 버전, 없으면 crawl의 context.md)
            src_md = (os.path.join(ocr_base, entry.name, "product.md")
                      if ocr_base else os.path.join(crawl_base, entry.name, "context.md"))
            if os.path.isfile(src_md):
                shutil.copy2(src_md, os.path.join(domain_archive, "product.md"))

            # 이미지 URL 수집 (100px 이상만)
            image_urls = []
            assets_path = os.path.join(crawl_base, entry.name, "assets.json")
            if os.path.isfile(assets_path):
                with open(assets_path, encoding="utf-8") as f:
                    assets = json.load(f)
                image_urls = [a["src"] for a in assets
                              if a.get("src", "").startswith("http")
                              and a.get("width", 0) >= 100]

            with open(os.path.join(domain_archive, "result.json"), "w", encoding="utf-8") as f:
                json.dump({"domain": hostname, "url": entry_url,
                           "images": image_urls, "product": record or {}},
                          f, ensure_ascii=False, indent=2)

            if record:
                index_entries.append({
                    "source": source,
                    "date": date_str,
                    "time": raw_time,
                    "domain": hostname,
                    "url": entry_url,
                    "product": record.get("상품명", ""),
                    "models": [v.get("model", "") for v in record.get("variants", []) if v.get("model")],
                    "path": f"{source}/{date_str}/{raw_time}/{folder_name}/result.json",
                })

    # index.json 업데이트 (thread-safe)
    if index_entries:
        index_path = os.path.join(_ROOT, "archive", "index.json")
        with _lock:
            existing = []
            if os.path.isfile(index_path):
                with open(index_path, encoding="utf-8") as f:
                    existing = json.load(f)
            existing.extend(index_entries)
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)

    # temp 폴더 삭제
    ocr_cache = os.path.join(_ROOT, "ocr", "cache", run_name)
    for temp_dir in [crawl_base, ocr_base, ocr_cache]:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
    for d in _glob.glob(os.path.join(_ROOT, "extract", "output", run_name + "*")):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    return archive_base


def save_crawl(source: str, run_name: str, run_ocr: bool, crawl_dir: str, ocr_dir: str = None) -> str:
    """Extract 없이 Crawl(+OCR) 결과를 archive에 저장. result.json의 product는 {} 로 저장.
    temp 폴더(crawl/ocr output)는 저장 후 삭제한다."""
    parts = run_name.split("_")
    if len(parts) < 3:
        raise ValueError(f"run_name 형식 오류: {run_name}")
    raw_date, raw_time = parts[1], parts[2]
    date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

    archive_base = os.path.join(_ROOT, "archive", source, date_str, raw_time)
    os.makedirs(archive_base, exist_ok=True)

    all_urls = []

    if os.path.isdir(crawl_dir):
        for entry in sorted(os.scandir(crawl_dir), key=lambda e: e.name):
            if not entry.is_dir():
                continue
            slug_parts = entry.name.split("_", 1)
            if len(slug_parts) < 2:
                continue
            domain_slug = slug_parts[1]
            hostname = domain_slug.replace("_", ".")

            meta_path = os.path.join(crawl_dir, entry.name, "metadata.json")
            entry_url = ""
            title = ""
            status = ""
            elapsed = 0
            if os.path.isfile(meta_path):
                with open(meta_path, encoding="utf-8") as f:
                    meta_data = json.load(f)
                entry_url = meta_data.get("url", "")
                title = meta_data.get("title", "")
                status = meta_data.get("status", "")
                elapsed = meta_data.get("elapsed_seconds", 0)

            if entry_url:
                all_urls.append(entry_url)

            short_id = _uuid.uuid4().hex[:6]
            folder_name = f"{domain_slug}_{short_id}"
            domain_archive = os.path.join(archive_base, folder_name)
            os.makedirs(domain_archive, exist_ok=True)

            src_md = (os.path.join(ocr_dir, entry.name, "product.md")
                      if ocr_dir and os.path.isdir(ocr_dir) else None)
            if not src_md or not os.path.isfile(src_md):
                src_md = os.path.join(crawl_dir, entry.name, "context.md")
            if os.path.isfile(src_md):
                shutil.copy2(src_md, os.path.join(domain_archive, "product.md"))

            # OCR 평균 신뢰도(ocr_confidence.json)도 함께 보관 — temp ocr_dir을
            # 곧 삭제하므로 여기서 복사해두지 않으면 이후 추출 단계에서
            # 조회할 방법이 없어진다.
            if ocr_dir and os.path.isdir(ocr_dir):
                conf_src = os.path.join(ocr_dir, entry.name, "ocr_confidence.json")
                if os.path.isfile(conf_src):
                    shutil.copy2(conf_src, os.path.join(domain_archive, "ocr_confidence.json"))

            image_urls = []
            assets_path = os.path.join(crawl_dir, entry.name, "assets.json")
            if os.path.isfile(assets_path):
                with open(assets_path, encoding="utf-8") as f:
                    assets = json.load(f)
                image_urls = [a["src"] for a in assets
                              if a.get("src", "").startswith("http")
                              and a.get("width", 0) >= 100]

            with open(os.path.join(domain_archive, "result.json"), "w", encoding="utf-8") as f:
                json.dump({"domain": hostname, "url": entry_url, "title": title,
                           "status": status, "elapsed_seconds": elapsed,
                           "images": image_urls, "product": {}},
                          f, ensure_ascii=False, indent=2)

    with open(os.path.join(archive_base, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"run_name": run_name, "source": source, "run_ocr": run_ocr,
                   "created_at": f"{date_str}T{raw_time}", "urls": all_urls},
                  f, ensure_ascii=False, indent=2)

    ocr_cache = os.path.join(_ROOT, "ocr", "cache", run_name)
    for temp_dir in [crawl_dir, ocr_dir, ocr_cache]:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    return archive_base


def update_extract(archive_base: str, by_domain: dict):
    """기존 archive에 LLM 추출 결과를 업데이트하고 index.json에 추가한다."""
    meta_path = os.path.join(archive_base, "meta.json")
    source, date_str, raw_time = "gui", None, None
    if os.path.isfile(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        source = meta.get("source", "gui")
        run_name = meta.get("run_name", "")
        parts = run_name.split("_")
        if len(parts) >= 3:
            raw_date = parts[1]
            raw_time = parts[2]
            date_str = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

    index_entries = []

    for folder_name in sorted(os.listdir(archive_base)):
        domain_dir = os.path.join(archive_base, folder_name)
        if not os.path.isdir(domain_dir):
            continue
        result_path = os.path.join(domain_dir, "result.json")
        if not os.path.isfile(result_path):
            continue

        with open(result_path, encoding="utf-8") as f:
            result = json.load(f)

        entry_url = result.get("url", "")
        hostname = result.get("domain", "")

        domain_records = by_domain.get(hostname) or next(
            (v for k, v in by_domain.items() if hostname in k or k in hostname), [])
        record = next((r for r in domain_records if r.get("URL") == entry_url), None)
        if record is None and domain_records:
            record = domain_records[0]

        if record:
            result["product"] = record
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            if date_str and raw_time:
                index_entries.append({
                    "source": source,
                    "date": date_str,
                    "time": raw_time,
                    "domain": hostname,
                    "url": entry_url,
                    "product": record.get("상품명", ""),
                    "models": [v.get("model", "") for v in record.get("variants", []) if v.get("model")],
                    "path": f"{source}/{date_str}/{raw_time}/{folder_name}/result.json",
                })

    if index_entries:
        index_path = os.path.join(_ROOT, "archive", "index.json")
        with _lock:
            existing = []
            if os.path.isfile(index_path):
                with open(index_path, encoding="utf-8") as f:
                    existing = json.load(f)
            existing.extend(index_entries)
            with open(index_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
