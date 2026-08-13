import glob
import os
import sys
import time

import numpy as np
from PIL import Image

import config

os.environ.setdefault("FLAGS_use_mkldnn", "0")  # oneDNN Windows 호환성 버그 우회
# Paddle 3.x 기본 실행기(PIR)가 일부 oneDNN 연산자의 배열 속성 변환을
# 아직 완전히 지원하지 못해 "ConvertPirAttribute2RuntimeAttribute" 오류가 난다.
# 예전 실행기로 되돌려 이 변환 경로 자체를 타지 않게 한다.
os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")

_OCR_ENGINE = None


def get_engine():
    """PaddleOCR 엔진은 로딩이 무거우니 지연 초기화 + 1회만 생성한다.
    설치된 paddleocr/paddlex 버전에 따라 일부 파라미터가 없을 수 있어
    TypeError가 나면 문제되는 파라미터를 하나씩 제거하며 재시도한다."""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE

    from paddleocr import PaddleOCR

    kwargs = dict(
        use_textline_orientation=config.OCR_USE_TEXTLINE_ORIENTATION,
        # 스캔 문서용 전처리(카메라로 비스듬히 찍은 종이를 펴주는 기능). 웹페이지
        # 스크린샷은 이미 똑바르므로 꺼둔다. Windows oneDNN 환경에서 이 모델들이
        # "ConvertPirAttribute2RuntimeAttribute" 오류를 내는 버그도 이걸로 회피된다.
        use_doc_orientation_classify=config.OCR_USE_DOC_ORIENTATION_CLASSIFY,
        use_doc_unwarping=config.OCR_USE_DOC_UNWARPING,
        lang=config.OCR_LANG,
        text_det_limit_side_len=config.OCR_TEXT_DET_LIMIT_SIDE_LEN,
        text_det_limit_type=config.OCR_TEXT_DET_LIMIT_TYPE,
    )
    if config.OCR_TEXT_DETECTION_MODEL_NAME:
        kwargs["text_detection_model_name"] = config.OCR_TEXT_DETECTION_MODEL_NAME
    if config.OCR_ENABLE_MKLDNN is not None:
        kwargs["enable_mkldnn"] = config.OCR_ENABLE_MKLDNN

    while True:
        try:
            _OCR_ENGINE = PaddleOCR(**kwargs)
            return _OCR_ENGINE
        except TypeError as error:
            # 설치된 버전이 지원하지 않는 파라미터가 있으면 하나씩 제거하고 재시도
            removed = False
            for key in ("enable_mkldnn", "text_detection_model_name"):
                if key in kwargs and key in str(error):
                    print(f"  (참고) 설치된 paddleocr 버전이 '{key}' 파라미터를 지원하지 않아 제외하고 재시도합니다.")
                    del kwargs[key]
                    removed = True
                    break
            if not removed:
                raise


def find_latest_capture_dir(base=None):
    base = base or config.IMAGE_DIR
    candidates = sorted(glob.glob(os.path.join(base, "capture_*")))
    if not candidates:
        raise FileNotFoundError(f"'{base}'에서 capture_* 폴더를 찾을 수 없습니다. main.py를 먼저 실행하세요.")
    return candidates[-1]


def find_ocr_targets(capture_dir):
    """OCR 대상: main.py가 저장한 개별 이미지/Canvas 에셋(*_assets/*.png)은
    항상 대상에 포함한다(DOM으로 읽을 수 없는 것들이라 대안이 없음).
    상품 본문 스크린샷(*_product.png)은 같은 영역의 DOM 텍스트가 이미 충분히
    잡혔으면 OCR이 중복 작업이므로 건너뛴다 — 특히 세로로 긴 스크린샷일수록
    타일이 많아 시간이 크게 늘어나므로 이 스킵이 전체 소요시간에 큰 영향을 준다.
    전체 페이지 스크린샷은 DOM 텍스트와 대부분 중복돼 기본적으로 제외한다."""
    targets = []
    for assets_dir in sorted(glob.glob(os.path.join(capture_dir, "*_assets"))):
        for name in sorted(os.listdir(assets_dir)):
            if name.lower().endswith(".png"):
                targets.append(os.path.join(assets_dir, name))

    for product_png in sorted(glob.glob(os.path.join(capture_dir, "*_product.png"))):
        prefix = product_png[: -len("_product.png")]
        dom_path = prefix + "_product_dom.txt"
        dom_text = ""
        if os.path.exists(dom_path):
            with open(dom_path, encoding="utf-8") as handle:
                dom_text = handle.read().strip()
        if len(dom_text) < config.OCR_PRODUCT_SCREENSHOT_MIN_DOM_CHARS:
            targets.append(product_png)
        else:
            print(f"  (스킵) {product_png} — 상품 영역 DOM 텍스트가 이미 {len(dom_text)}자 있어 OCR 생략")
    return targets


def product_prefix_for(image_path, capture_dir):
    """이미지 경로에서 어떤 상품(prefix)에 속하는지 역산한다.
    '<prefix>_assets/asset_001_img.png' -> '<prefix>'
    '<prefix>_product.png' -> '<prefix>'"""
    if image_path.endswith("_product.png"):
        return image_path[: -len("_product.png")]
    parent = os.path.basename(os.path.dirname(image_path))
    if parent.endswith("_assets"):
        prefix_name = parent[: -len("_assets")]
        return os.path.join(capture_dir, prefix_name)
    return os.path.splitext(image_path)[0]


def image_output_path(image_path, capture_dir):
    out_dir = os.path.join(capture_dir, "ocr_text")
    relative = os.path.relpath(image_path, capture_dir)
    return os.path.join(out_dir, os.path.splitext(relative)[0] + ".txt")


# ── 1. 단어별 위치 추출 ───────────────────────────────────────────────────────

def _words_from_result(result, y_offset: int = 0) -> list:
    """PaddleOCR 3.x predict() 결과 구조:
    [{'dt_polys': [...], 'rec_texts': [...], 'rec_scores': [...]}]
    """
    words = []
    for page in result:
        polys = page.get("dt_polys", [])
        texts = page.get("rec_texts", [])
        scores = page.get("rec_scores", [])
        for box, text, conf in zip(polys, texts, scores):
            if not text.strip() or conf < config.OCR_CONFIDENCE_THRESHOLD:
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
                "h": max(ys) - min(ys),
                "w": max(xs) - min(xs),
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
        if not any(_iou(w, k) > config.OCR_IOU_THRESHOLD for k in kept):
            kept.append(w)
    return kept


# ── 3. y 좌표로 행 그룹핑 ────────────────────────────────────────────────────

def _group_rows(words: list) -> list:
    if not words:
        return []

    avg_h = sum(w["h"] for w in words) / len(words)
    tol = max(avg_h * config.OCR_ROW_TOLERANCE, 4)

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
            gap = w["x1"] - prev_x2
            char_w = w["w"] / max(len(w["text"]), 1)
            sep = "\t" if gap > char_w * config.OCR_COL_GAP_RATIO else " "
            parts.append(sep)
        parts.append(w["text"])
        prev_x2 = w["x2"]
    return "".join(parts)


# ── 5. 파이프라인 ─────────────────────────────────────────────────────────────

def run_ocr(image_path):
    img = Image.open(image_path).convert("RGB")
    width, height = img.size

    all_words = []
    y, tile_idx = 0, 1
    engine = get_engine()

    while y < height:
        bottom = min(y + config.OCR_TILE_HEIGHT, height)
        tile = np.array(img.crop((0, y, width, bottom)))
        result = engine.predict(tile)  # 3.x: predict() / cls 인자 없음
        words = _words_from_result(result, y_offset=y)
        all_words.extend(words)
        print(f"    타일 {tile_idx} ({y}~{bottom}px): {len(words)}개 단어")
        tile_idx += 1
        y = bottom if bottom >= height else bottom - config.OCR_TILE_OVERLAP

    all_words = _dedup(all_words)
    rows = _group_rows(all_words)
    return "\n".join(_row_to_line(r) for r in rows)


def ocr_image(image_path, text_path):
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px")
    start_time = time.perf_counter()

    try:
        text = run_ocr(image_path)
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        print(f"  ❌ OCR 실패: {e}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return None, elapsed

    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    elapsed = time.perf_counter() - start_time
    total_lines = len(text.splitlines())
    print(f"  ✅ OCR 완료 → {text_path} ({total_lines}줄)")
    print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
    if text.strip():
        print(f"  미리보기: {text[:150].strip()}")
    return text, elapsed


def ocr_capture_dir(capture_dir):
    print("=" * 50)
    print("PaddleOCR (좌표 기반 표 구조 재조립)")
    print("=" * 50)

    images = find_ocr_targets(capture_dir)
    if not images:
        print(f"❌ '{capture_dir}'에 OCR 대상 이미지가 없습니다. main.py를 먼저 실행하세요.")
        return {}

    print(f"총 {len(images)}개 이미지 발견\n")

    combined_by_prefix = {}
    pipeline_start = time.perf_counter()
    ocr_count, cache_hit_count = 0, 0

    for image_path in images:
        text_path = image_output_path(image_path, capture_dir)
        prefix = product_prefix_for(image_path, capture_dir)

        if config.OCR_CACHE_ENABLED and os.path.exists(text_path) and \
                os.path.getmtime(text_path) >= os.path.getmtime(image_path):
            with open(text_path, encoding="utf-8") as f:
                text = f.read()
            print(f"\n  파일: {image_path}\n  (캐시 사용, OCR 생략)")
            cache_hit_count += 1
        else:
            text, _ = ocr_image(image_path, text_path)
            ocr_count += 1
            if text is None:
                continue

        if text.strip():
            combined_by_prefix.setdefault(prefix, []).append(text.strip())

    # 상품(prefix)별로 모든 이미지의 OCR 텍스트를 하나로 합쳐 저장한다.
    # 이 파일이 extract_info.py의 입력으로 쓰인다.
    for prefix, chunks in combined_by_prefix.items():
        with open(prefix + "_ocr_combined.txt", "w", encoding="utf-8") as f:
            f.write("\n\n".join(chunks))

    total_elapsed = time.perf_counter() - pipeline_start
    print(f"\n📄 텍스트 저장 위치: {os.path.abspath(os.path.join(capture_dir, 'ocr_text'))}")
    print(f"   실제 OCR 실행: {ocr_count}개 / 캐시 재사용: {cache_hit_count}개")
    print(f"⏱️  OCR 전체 소요 시간: {total_elapsed:.1f}초")
    return combined_by_prefix


if __name__ == "__main__":
    target_dir = sys.argv[1] if len(sys.argv) > 1 else find_latest_capture_dir()
    ocr_capture_dir(target_dir)
