import io
import os
import time
import requests
import urllib3
from dotenv import load_dotenv

from PIL import Image

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

IMAGE_DIR = "../capture/output"
OUT_DIR   = "output/upstage_dp"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY       = os.environ["UPSTAGE_API_KEY"]
REQUEST_DELAY = 2          # 이미지 간 대기(초)
MAX_BYTES     = 5 * 1024 * 1024  # Upstage 5MB 제한


# ── 1. 이미지 준비 (5MB 초과 시 리사이즈) ─────────────────────────────────────
# document-parse 는 타일 분할 시 표 구조가 잘릴 수 있어 전체 이미지를 한 번에 전송.
# 대신 5MB 초과 시 해상도를 단계적으로 낮춰 압축.

def _prepare_image(image_path: str) -> tuple[bytes, str]:
    """(image_bytes, mime_type) 반환. 5MB 초과 시 PNG 리사이즈."""
    if os.path.getsize(image_path) < MAX_BYTES:
        with open(image_path, "rb") as f:
            return f.read(), "image/png"

    img = Image.open(image_path).convert("RGB")
    for scale in [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]:
        buf = io.BytesIO()
        w = int(img.width * scale)
        h = int(img.height * scale)
        img.resize((w, h), Image.LANCZOS).save(buf, format="PNG", optimize=True)
        if buf.tell() < MAX_BYTES:
            size_mb = buf.tell() / 1024 / 1024
            orig_mb = os.path.getsize(image_path) / 1024 / 1024
            print(f"    리사이즈: {orig_mb:.1f}MB → {size_mb:.1f}MB (scale={scale})")
            return buf.getvalue(), "image/png"

    raise RuntimeError(f"5MB 이하로 압축 불가: {image_path}")


# ── 2. API 요청 ───────────────────────────────────────────────────────────────

def _request(image_bytes: bytes, mime: str, filename: str) -> dict:
    response = requests.post(
        "https://api.upstage.ai/v1/document-digitization",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"document": (filename, image_bytes, mime)},
        data={
            "model":          "document-parse-nightly",
            "mode":           "enhanced",
            "output_formats": '["markdown"]',
        },
        verify=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"API 오류 (status {response.status_code}): {response.text[:300]}")
    return response.json()


# ── 3. 응답 파싱 ──────────────────────────────────────────────────────────────

def _parse_response(result: dict) -> str:
    """응답 구조가 API 버전마다 다를 수 있어 여러 경로를 순서대로 시도."""
    # 방법 A: 최상위 content 필드
    top_content = result.get("content", {})
    if isinstance(top_content, dict) and top_content.get("markdown"):
        return top_content["markdown"]
    if isinstance(top_content, str) and top_content:
        return top_content

    # 방법 B: pages 배열
    pages = result.get("pages", [])
    if pages:
        parts = []
        for page in pages:
            md = page.get("markdown") or page.get("text") or page.get("html") or ""
            if md:
                parts.append(md.strip())
        if parts:
            return "\n\n".join(parts)

    # 방법 C: 응답 전체를 원시 덤프 (디버깅용)
    import json
    return json.dumps(result, ensure_ascii=False, indent=2)


# ── 4. 파이프라인 ─────────────────────────────────────────────────────────────

def run_ocr(image_path: str) -> str:
    image_bytes, mime = _prepare_image(image_path)
    filename = os.path.basename(image_path)
    result   = _request(image_bytes, mime, filename)
    return _parse_response(result)


def _out_path(image_path: str) -> str:
    rel = os.path.relpath(image_path, IMAGE_DIR)
    return os.path.join(OUT_DIR, os.path.splitext(rel)[0] + ".md")


def _find_images() -> list:
    imgs = []
    for root, _, files in os.walk(IMAGE_DIR):
        for f in files:
            if f.endswith(".png"):
                imgs.append(os.path.join(root, f))
    return sorted(imgs)


def process_image(image_path: str):
    print(f"\n  파일: {image_path}")
    start = time.time()
    try:
        text = run_ocr(image_path)
    except Exception as e:
        print(f"  ❌ 실패: {e}")
        return

    out = _out_path(image_path)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)

    elapsed = time.time() - start
    lines   = text.splitlines()
    print(f"  ✅ 완료 → {out} ({len(lines)}줄, {elapsed:.1f}초)")
    print("  미리보기 (앞 10줄):")
    for line in lines[:10]:
        print(f"    {line}")


def run_all():
    print("=" * 50)
    print("Upstage Document Parse  Enhanced mode")
    print("=" * 50)

    images = _find_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. capture/capture.py를 먼저 실행하세요.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for i, img in enumerate(images):
        process_image(img)
        if i < len(images) - 1:
            time.sleep(REQUEST_DELAY)

    print(f"\n저장 위치: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        process_image(sys.argv[1])
    else:
        run_all()
