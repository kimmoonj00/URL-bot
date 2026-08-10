import io
import os
import time
from dotenv import load_dotenv

from PIL import Image
from google.cloud import vision

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

IMAGE_DIR = "../capture/output"

# .env에 GOOGLE_APPLICATION_CREDENTIALS가 없으면 gcloud ADC 자동 감지로 폴백
if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    _adc = os.path.join(os.environ.get("APPDATA", ""), "gcloud", "application_default_credentials.json")
    if os.path.exists(_adc):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = _adc

TEXT_DIR = "output/google_ocr"
ROW_TOLERANCE = 0.6  # 평균 글자 높이 × 이 비율 이내면 같은 행으로 간주
COL_GAP_RATIO = 2.5  # 평균 글자 너비 × 이 비율 이상 간격이면 열 구분자(탭) 삽입

MAX_BYTES  = 8 * 1024 * 1024  # 8MB 초과 시 타일 분할
TILE_HEIGHT = 3000             # 타일 높이 (px)

client = vision.ImageAnnotatorClient()


# ── 1. 단어별 위치 추출 ───────────────────────────────────────────────────────

def _words_from_response(response, y_offset: int = 0) -> list[dict]:
    words = []
    for page in response.full_text_annotation.pages:
        for block in page.blocks:
            for para in block.paragraphs:
                for word in para.words:
                    text = "".join(s.text for s in word.symbols)
                    if not text.strip():
                        continue
                    vs = word.bounding_box.vertices
                    xs = [v.x for v in vs if hasattr(v, "x")]
                    ys = [v.y for v in vs if hasattr(v, "y")]
                    if not xs or not ys:
                        continue
                    words.append({
                        "text": text,
                        "x1": min(xs), "x2": max(xs),
                        "y1": min(ys) + y_offset, "y2": max(ys) + y_offset,
                        "xc": (min(xs) + max(xs)) / 2,
                        "yc": (min(ys) + max(ys)) / 2 + y_offset,
                        "h":  max(ys) - min(ys),
                        "w":  max(xs) - min(xs),
                    })
    return words


def _get_words(image_path: str) -> list[dict]:
    file_size = os.path.getsize(image_path)

    if file_size < MAX_BYTES:
        with open(image_path, "rb") as f:
            content = f.read()
        response = client.document_text_detection(vision.Image(content=content))
        if response.error.message:
            raise RuntimeError(f"Vision API 오류: {response.error.message}")
        return _words_from_response(response)

    # 8MB 초과 → 타일 분할 후 y 오프셋 보정으로 좌표 복원
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    words, y, idx = [], 0, 1
    while y < height:
        bottom = min(y + TILE_HEIGHT, height)
        buf = io.BytesIO()
        img.crop((0, y, width, bottom)).save(buf, format="PNG")
        response = client.document_text_detection(vision.Image(content=buf.getvalue()))
        if response.error.message:
            raise RuntimeError(f"Vision API 오류 (타일 {idx}): {response.error.message}")
        tile_words = _words_from_response(response, y_offset=y)
        words.extend(tile_words)
        print(f"    타일 {idx} ({y}~{bottom}px): {len(tile_words)}개 단어")
        idx += 1
        y = bottom
    return words


# ── 2. y 좌표로 행 그룹핑 ────────────────────────────────────────────────────

def _group_rows(words: list[dict]) -> list[list[dict]]:
    if not words:
        return []

    avg_h = sum(w["h"] for w in words) / len(words)
    tol   = max(avg_h * ROW_TOLERANCE, 4)   # 최소 4px 보장

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


# ── 3. 행 → 텍스트 (열 간격이 넓으면 탭 삽입) ──────────────────────────────

def _row_to_line(row: list[dict]) -> str:
    parts = []
    prev_x2 = None
    for w in row:
        if prev_x2 is not None:
            gap      = w["x1"] - prev_x2
            char_w   = w["w"] / max(len(w["text"]), 1)
            sep      = "\t" if gap > char_w * COL_GAP_RATIO else " "
            parts.append(sep)
        parts.append(w["text"])
        prev_x2 = w["x2"]
    return "".join(parts)


# ── 4. 파이프라인 ─────────────────────────────────────────────────────────────

def run_ocr(image_path: str) -> str:
    words = _get_words(image_path)
    rows  = _group_rows(words)
    return "\n".join(_row_to_line(r) for r in rows)


def _out_path(image_path: str) -> str:
    rel = os.path.relpath(image_path, IMAGE_DIR)
    return os.path.join(TEXT_DIR, os.path.splitext(rel)[0] + ".txt")


def _find_images() -> list[str]:
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
    print("Google Vision  좌표 기반 표 구조 재조립")
    print("=" * 50)

    images = _find_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for img in images:
        process_image(img)

    print(f"\n저장 위치: {os.path.abspath(TEXT_DIR)}")


if __name__ == "__main__":
    run_all()
