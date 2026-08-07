import os
import io
import sys
import time

from PIL import Image
from google.cloud import vision

# 프로젝트 루트를 sys.path에 추가 (config.py 임포트용)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import IMAGE_DIR

VISION_DIR = "text"
MAX_BYTES = 8 * 1024 * 1024  # 8MB 초과 시 타일 분할
TILE_HEIGHT = 3000            # Cloud Vision은 이미지 크기 제한이 넓으므로 3000px

client = vision.ImageAnnotatorClient()


def _ocr_bytes(content: bytes) -> str:
    image = vision.Image(content=content)
    response = client.document_text_detection(image=image)
    if response.error.message:
        raise RuntimeError(f"Vision API 오류: {response.error.message}")
    return response.full_text_annotation.text or ""


def run_ocr(image_path: str) -> str:
    file_size = os.path.getsize(image_path)

    if file_size < MAX_BYTES:
        with open(image_path, "rb") as f:
            return _ocr_bytes(f.read())

    # 8MB 초과 → 타일 분할
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    parts, y, idx = [], 0, 1
    while y < height:
        bottom = min(y + TILE_HEIGHT, height)
        buf = io.BytesIO()
        img.crop((0, y, width, bottom)).save(buf, format="PNG")
        text = _ocr_bytes(buf.getvalue())
        if text.strip():
            parts.append(text.strip())
        print(f"    타일 {idx} ({y}~{bottom}px): {len(text.splitlines())}줄 인식")
        idx += 1
        y = bottom
    return "\n".join(parts)


def image_path_to_text_path(image_path: str) -> str:
    """output/세션폴더/파일.png → text/세션폴더/파일.txt"""
    relative = os.path.relpath(image_path, IMAGE_DIR)
    return os.path.join(VISION_DIR, os.path.splitext(relative)[0] + ".txt")


def find_captured_images():
    images = []
    for root, _, files in os.walk(IMAGE_DIR):
        for f in files:
            if f.endswith(".png"):
                images.append(os.path.join(root, f))
    return sorted(images)


def ocr_image(image_path: str):
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    file_size = os.path.getsize(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px  파일: {file_size / 1024 / 1024:.1f}MB")
    start = time.time()

    try:
        text = run_ocr(image_path)
    except Exception as e:
        print(f"  ❌ OCR 실패: {e}")
        return

    text_path = image_path_to_text_path(image_path)
    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    elapsed = time.time() - start
    print(f"  ✅ 완료 → {text_path} ({len(text.splitlines())}줄, {elapsed:.1f}초)")
    print(f"  미리보기: {text[:150].strip()}")


def ocr_all():
    print("=" * 50)
    print("Google Cloud Vision OCR (document_text_detection)")
    print("=" * 50)

    images = find_captured_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. main.py를 먼저 실행하세요.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for img_path in images:
        ocr_image(img_path)

    print(f"\n텍스트 저장 위치: {os.path.abspath(VISION_DIR)}")


if __name__ == "__main__":
    ocr_all()
