"""
크롤/OCR/추출 결과를 archive/{source}/YYYY-MM-DD/HHMMSS/ 에 저장하는 공유 모듈.
slack_bot.py, server.py 등에서 동일하게 사용.
"""

import glob as _glob
import json
import os
import shutil
import threading

_ROOT = os.path.dirname(os.path.abspath(__file__))
_lock = threading.Lock()


def save(source: str, run_name: str, run_ocr: bool, by_domain: dict) -> str:
    """
    source: "slack" | "gui" | "cli"
    run_name: "slack_20260903_112218" 형식 (접두사_날짜_시간)
    run_ocr: OCR 실행 여부
    by_domain: build_summary() 반환값

    Returns: 생성된 archive 경로
    """
    parts = run_name.split("_")  # ["slack", "20260903", "112218"]
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
            domain_slug = slug_parts[1]       # "www_navimro_com"
            hostname = domain_slug.replace("_", ".")  # "www.navimro.com"

            domain_archive = os.path.join(archive_base, domain_slug)
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

            # LLM 결과 매칭
            records = by_domain.get(hostname) or next(
                (v for k, v in by_domain.items() if hostname in k or k in hostname), [])

            with open(os.path.join(domain_archive, "result.json"), "w", encoding="utf-8") as f:
                json.dump({"domain": hostname, "images": image_urls, "products": records},
                          f, ensure_ascii=False, indent=2)

            for rec in records:
                index_entries.append({
                    "source": source,
                    "date": date_str,
                    "time": raw_time,
                    "domain": hostname,
                    "product": rec.get("상품명", ""),
                    "models": [v.get("model", "") for v in rec.get("variants", []) if v.get("model")],
                    "url": rec.get("URL", ""),
                    "path": f"{source}/{date_str}/{raw_time}/{domain_slug}/result.json",
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
    for temp_dir in [crawl_base, ocr_base]:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
    for d in _glob.glob(os.path.join(_ROOT, "extract", "output", run_name + "*")):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)

    return archive_base
