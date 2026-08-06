import os
import time
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

from config import IMAGE_DIR, TEXT_DIR

TILE_HEIGHT = 2000  # 타일 높이 (px) — 이 단위로 잘라서 OCR

ocr = PaddleOCR(use_angle_cls=True, lang="korean", det_limit_side_len=2000)


def find_captured_images():
    images = []
    for root, _, files in os.walk(IMAGE_DIR):
        for f in files:
            if f.endswith(".png"):
                images.append(os.path.join(root, f))
    return sorted(images)


def image_path_to_text_path(image_path):
    """output/세션폴더/파일.png → text/세션폴더/파일.txt"""
    relative = os.path.relpath(image_path, IMAGE_DIR)
    text_path = os.path.join(TEXT_DIR, os.path.splitext(relative)[0] + ".txt")
    return text_path


def extract_lines(result):
    lines = []
    for page in result:
        if not page:
            continue
        for line in page:
            text = line[1][0]
            if text.strip():
                lines.append(text.strip())
    return lines


def run_ocr(image_path):
    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    all_lines = []
    y = 0
    tile_idx = 1

    while y < height:
        bottom = min(y + TILE_HEIGHT, height)
        tile = np.array(img.crop((0, y, width, bottom)))
        result = ocr.ocr(tile, cls=True)
        lines = extract_lines(result)
        all_lines.extend(lines)
        print(f"    타일 {tile_idx} ({y}~{bottom}px): {len(lines)}줄 인식")
        tile_idx += 1
        y = bottom

    return "\n".join(all_lines)


def ocr_image(image_path):
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px → {-(-img.height // TILE_HEIGHT)}개 타일")
    start_time = time.time()

    try:
        text = run_ocr(image_path)
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ❌ OCR 실패: {e}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return

    text_path = image_path_to_text_path(image_path)
    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    elapsed = time.time() - start_time
    total_lines = len(text.splitlines())
    print(f"  ✅ OCR 완료 → {text_path} ({total_lines}줄)")
    print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
    print(f"  미리보기: {text[:150].strip()}")


def ocr_all():
    print("=" * 50)
    print("PaddleOCR (타일링 방식)")
    print("=" * 50)

    images = find_captured_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. main.py를 먼저 실행하세요.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for img in images:
        ocr_image(img)

    print(f"\n📄 텍스트 저장 위치: {os.path.abspath(TEXT_DIR)}")


if __name__ == "__main__":
    ocr_all()
