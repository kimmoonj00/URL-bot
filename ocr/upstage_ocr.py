import io
import os
import time
import requests
import urllib3
from dotenv import load_dotenv

from PIL import Image

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

IMAGE_DIR = "../capture/output"
OUT_DIR = "output/upstage_ocr"

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = os.environ["UPSTAGE_API_KEY"]
REQUEST_DELAY = 2    # 이미지 간 대기(초) - 회사 프록시 연속 차단 방지
TILE_DELAY    = 1    # 타일 간 대기(초)

MAX_BYTES   = 5 * 1024 * 1024  # Upstage 5MB 제한
TILE_HEIGHT = 2000

ROW_TOLERANCE = 0.6  # 평균 글자 높이 × 이 비율 이내면 같은 행으로 간주
COL_GAP_RATIO = 2.5  # 평균 글자 너비 × 이 비율 이상 간격이면 열 구분자(탭) 삽입


# ── 1. API 요청 ───────────────────────────────────────────────────────────────

def _request_bytes(image_bytes: bytes, filename: str = "image.png") -> dict:
    response = requests.post(
        "https://api.upstage.ai/v1/document-digitization",
        headers={"Authorization": f"Bearer {API_KEY}"},
        files={"document": (filename, image_bytes, "image/png")},
        data={"model": "ocr"},
        verify=False,
    )
    if response.status_code != 200:
        raise RuntimeError(f"API 오류 (status {response.status_code}): {response.text}")
    return response.json()


# ── 2. 단어별 좌표 추출 ───────────────────────────────────────────────────────

def _words_from_page(page_json: dict, y_offset: int = 0) -> list:
    words = []
    for word in page_json.get("words", []):
        text = word.get("text", "").strip()
        if not text:
            continue
        # Upstage는 camelCase(boundingBox) 사용 — 구버전 API는 bounding_box일 수 있어 둘 다 시도
        bbox = word.get("boundingBox") or word.get("bounding_box") or {}
        verts = bbox.get("vertices", [])
        if len(verts) < 2:
            continue
        xs = [v["x"] for v in verts if "x" in v]
        ys = [v["y"] for v in verts if "y" in v]
        if not xs or not ys:
            continue
        words.append({
            "text": text,
            "x1": min(xs),            "x2": max(xs),
            "y1": min(ys) + y_offset, "y2": max(ys) + y_offset,
            "xc": (min(xs) + max(xs)) / 2,
            "yc": (min(ys) + max(ys)) / 2 + y_offset,
            "h":  max(ys) - min(ys),
            "w":  max(xs) - min(xs),
        })
    return words


# ── 3. 행 그룹핑 ─────────────────────────────────────────────────────────────

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


# ── 4. 행 → 텍스트 ───────────────────────────────────────────────────────────

def _row_to_line(row: list) -> str:
    parts    = []
    prev_x2  = None
    for w in row:
        if prev_x2 is not None:
            gap    = w["x1"] - prev_x2
            char_w = w["w"] / max(len(w["text"]), 1)
            sep    = "\t" if gap > char_w * COL_GAP_RATIO else " "
            parts.append(sep)
        parts.append(w["text"])
        prev_x2 = w["x2"]
    return "".join(parts)


# ── 5. OCR 파이프라인 ─────────────────────────────────────────────────────────

def _pages_to_text(pages: list) -> str:
    """좌표 기반 재조합 실패 시 page["text"] 폴백"""
    return "\n".join(p.get("text", "") for p in pages if p.get("text")).strip()


def run_ocr(image_path: str) -> str:
    file_size = os.path.getsize(image_path)

    if file_size < MAX_BYTES:
        with open(image_path, "rb") as f:
            result = _request_bytes(f.read(), os.path.basename(image_path))
        pages = result.get("pages", [])
        all_words = []
        for page in pages:
            all_words.extend(_words_from_page(page))
        if all_words:
            rows = _group_rows(all_words)
            return "\n".join(_row_to_line(r) for r in rows)
        # 좌표 데이터 없으면 page["text"] 폴백
        print("    ⚠️  바운딩박스 없음 → page.text 폴백")
        return _pages_to_text(pages)

    # 5MB 초과 → 타일 분할 후 y 오프셋 보정으로 좌표 복원
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    all_words, fallback_texts, y, idx = [], [], 0, 1
    while y < height:
        bottom = min(y + TILE_HEIGHT, height)
        buf    = io.BytesIO()
        img.crop((0, y, width, bottom)).save(buf, format="PNG")
        result = _request_bytes(buf.getvalue(), f"tile_{idx}.png")
        pages = result.get("pages", [])
        tile_words = []
        for page in pages:
            tile_words.extend(_words_from_page(page, y_offset=y))
        if tile_words:
            all_words.extend(tile_words)
        else:
            fallback_texts.append(_pages_to_text(pages))
        print(f"    타일 {idx} ({y}~{bottom}px): {len(tile_words)}개 단어")
        idx += 1
        y = bottom
        if y < height:
            time.sleep(TILE_DELAY)

    if all_words:
        rows = _group_rows(all_words)
        return "\n".join(_row_to_line(r) for r in rows)
    print("    ⚠️  바운딩박스 없음 → page.text 폴백")
    return "\n".join(fallback_texts)


# ── 6. 실행 ──────────────────────────────────────────────────────────────────

def _out_path(image_path: str) -> str:
    rel = os.path.relpath(image_path, IMAGE_DIR)
    return os.path.join(OUT_DIR, os.path.splitext(rel)[0] + ".txt")


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
    print("Upstage OCR  좌표 기반 표 구조 재조립")
    print("=" * 50)

    images = _find_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. capture/main.py를 먼저 실행하세요.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for i, img in enumerate(images):
        process_image(img)
        if i < len(images) - 1:
            time.sleep(REQUEST_DELAY)

    print(f"\n저장 위치: {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    run_all()
