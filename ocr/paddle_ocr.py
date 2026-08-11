import os
import re
import time
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

IMAGE_DIR = "../capture/output"
OUT_DIR   = "output/paddle_ocr"

TILE_HEIGHT   = 2000
TILE_OVERLAP  = 150
IOU_THRESH    = 0.5
CONF_MIN      = 0.4
ROW_TOLERANCE = 0.7
COL_GAP_RATIO = 2.5

# text_det_limit_side_len: 탐지 해상도 상한 (낮을수록 빠름, 1920은 일반 폰트 충분)
# use_textline_orientation: 한국 전자상거래는 가로 텍스트만 → False로 속도 단축
ocr = PaddleOCR(
    use_textline_orientation=False,
    lang="korean",
    text_det_limit_side_len=1920,
    text_det_limit_type="max",
)


def find_captured_images():
    images = []
    for root, _, files in os.walk(IMAGE_DIR):
        for f in files:
            if f.endswith(".png"):
                images.append(os.path.join(root, f))
    return sorted(images)


def image_path_to_text_path(image_path):
    relative = os.path.relpath(image_path, IMAGE_DIR)
    base = os.path.join(OUT_DIR, os.path.splitext(relative)[0])
    path = base + ".txt"
    counter = 1
    while os.path.exists(path):
        path = f"{base} ({counter}).txt"
        counter += 1
    return path


# ── 1. 단어별 위치 추출 ───────────────────────────────────────────────────────

def _words_from_result(result, y_offset: int = 0) -> list:
    """PaddleOCR 3.x predict() 결과 구조:
    [{'dt_polys': [...], 'rec_texts': [...], 'rec_scores': [...]}]
    """
    words = []
    for page in result:
        polys  = page.get("dt_polys", [])
        texts  = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        for box, text, conf in zip(polys, texts, scores):
            if not text.strip() or conf < CONF_MIN:
                continue
            xs = [float(pt[0]) for pt in box]
            ys = [float(pt[1]) for pt in box]
            words.append({
                "text": text,
                "conf": conf,
                "x1": min(xs), "x2": max(xs),
                "y1": min(ys) + y_offset, "y2": max(ys) + y_offset,
                "xc": (min(xs) + max(xs)) / 2,
                "yc": (min(ys) + max(ys)) / 2 + y_offset,
                "h":  max(ys) - min(ys),
                "w":  max(xs) - min(xs),
            })
    return words


# ── 2. 오버랩 타일 중복 단어 제거 (IOU 기반) ─────────────────────────────────

def _iou(a: dict, b: dict) -> float:
    ix1 = max(a["x1"], b["x1"])
    iy1 = max(a["y1"], b["y1"])
    ix2 = min(a["x2"], b["x2"])
    iy2 = min(a["y2"], b["y2"])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (a["x2"] - a["x1"]) * (a["y2"] - a["y1"])
    area_b = (b["x2"] - b["x1"]) * (b["y2"] - b["y1"])
    return inter / (area_a + area_b - inter)


def _dedup(words: list) -> list:
    kept = []
    for w in sorted(words, key=lambda x: -x["conf"]):
        if not any(_iou(w, k) > IOU_THRESH for k in kept):
            kept.append(w)
    return kept


# ── 3. y 좌표로 행 그룹핑 ────────────────────────────────────────────────────

def _group_rows(words: list) -> list:
    if not words:
        return []

    avg_h = sum(w["h"] for w in words) / len(words)
    tol   = max(avg_h * ROW_TOLERANCE, 4)

    rows, cur = [], [sorted(words, key=lambda w: w["yc"])[0]]
    for word in sorted(words, key=lambda w: w["yc"])[1:]:
        row_yc = sum(w["yc"] for w in cur) / len(cur)
        if abs(word["yc"] - row_yc) <= tol:
            cur.append(word)
        else:
            rows.append(sorted(cur, key=lambda w: w["xc"]))
            cur = [word]
    if cur:
        rows.append(sorted(cur, key=lambda w: w["xc"]))
    return rows


# ── 4. 행 → 텍스트 (열 간격이 넓으면 탭 삽입) ──────────────────────────────

def _row_to_line(row: list) -> str:
    parts = []
    prev_x2 = None
    for w in row:
        if prev_x2 is not None:
            gap    = w["x1"] - prev_x2
            char_w = w["w"] / max(len(w["text"]), 1)
            sep    = "\t" if gap > char_w * COL_GAP_RATIO else " "
            parts.append(sep)
        parts.append(w["text"])
        prev_x2 = w["x2"]
    return "".join(parts)


# ── 5. 숫자 후처리 ───────────────────────────────────────────────────────────

def _fix_numbers(text: str) -> str:
    # "20.130원" → "20,130원"  (천단위 구분자 마침표 → 쉼표)
    text = re.sub(r'(\d+)\.(\d{3})(원)', r'\1,\2\3', text)
    # "17 890원" → "17,890원"  (천단위 공백 제거 후 쉼표)
    text = re.sub(r'(\d{2,3}) (\d{3})(원)', r'\1,\2\3', text)
    # "17 .890원" → "17,890원"  (공백+마침표 혼합)
    text = re.sub(r'(\d{2,3}) \.(\d{3})(원)', r'\1,\2\3', text)
    return text


# ── 6. 파이프라인 ─────────────────────────────────────────────────────────────

def run_ocr(image_path):
    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    all_words = []
    y, tile_idx = 0, 1

    while y < height:
        bottom = min(y + TILE_HEIGHT, height)
        tile   = np.array(img.crop((0, y, width, bottom)))
        result = ocr.predict(tile)           # 3.x: predict() / cls 인자 없음
        words  = _words_from_result(result, y_offset=y)
        all_words.extend(words)
        print(f"    타일 {tile_idx} ({y}~{bottom}px): {len(words)}개 단어")
        tile_idx += 1
        y = bottom if bottom >= height else bottom - TILE_OVERLAP

    all_words = _dedup(all_words)
    rows = _group_rows(all_words)
    return _fix_numbers("\n".join(_row_to_line(r) for r in rows))


def ocr_image(image_path):
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px")
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
    print("PaddleOCR (좌표 기반 표 구조 재조립)")
    print("=" * 50)

    images = find_captured_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. capture/main.py를 먼저 실행하세요.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for img in images:
        ocr_image(img)

    print(f"\n📄 텍스트 저장 위치: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    ocr_all()
