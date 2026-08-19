import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # 한국어 Windows(cp949) 콘솔 인코딩으로는 이모지 등 일부 문자를 print()할 때
    # UnicodeEncodeError가 난다 (예: OCR 실패 메시지의 ❌). 현재 프로세스의
    # stdout/stderr 인코딩만 바꿔서 처리한다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import glob
import subprocess
import time

import numpy as np
from PIL import Image

import importlib.util as _ilu

_SELF = os.path.dirname(os.path.abspath(__file__))  # ocr/
_ROOT = os.path.dirname(_SELF)                       # 루트
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# crawler.py가 먼저 crawl/config.py를 sys.modules['config']에 등록하므로
# importlib으로 경로를 직접 지정해 캐시 충돌을 피한다.
_cfg = _ilu.spec_from_file_location("ocr_config", os.path.join(_SELF, "config.py"))
config = _ilu.module_from_spec(_cfg)
_cfg.loader.exec_module(config)

# `python ocr/paddle_ocr.py`로 직접 실행하면 ocr/가 상대 임포트의 부모
# 패키지로 인식 안 되므로, 위에서 sys.path에 넣어둔 루트 기준 절대 임포트로
# 가져온다.
from ocr.spacing import correct_spacing

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
        # ocr_version을 안 주면 paddleocr가 기본값으로 최신 세대(PP-OCRv5)
        # 모델을 쓰려 하는데, paddlepaddle==3.0.0은 그 모델 포맷(PIR)을 제대로
        # 못 읽어 응답 없이 멈추는 걸 실측했다(수 분간 진행 없음). PP-OCRv3는
        # paddlepaddle==3.0.0과 실제로 호환되는 마지막 세대라 이걸 명시한다.
        ocr_version="PP-OCRv3",
        text_det_limit_side_len=config.OCR_TEXT_DET_LIMIT_SIDE_LEN,
        text_det_limit_type=config.OCR_TEXT_DET_LIMIT_TYPE,
        text_recognition_batch_size=config.OCR_TEXT_RECOGNITION_BATCH_SIZE,
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
            for key in ("enable_mkldnn", "text_detection_model_name", "text_recognition_batch_size"):
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
    """OCR 대상: crawler.py가 상품 폴더({index}_{도메인}/)마다 저장한 개별
    이미지/Canvas 에셋(assets/*.png)과 상품 본문 스크린샷(product.png)만
    대상으로 한다. 전체 페이지 스크린샷은 DOM 텍스트와 대부분 중복돼
    기본적으로 제외해 시간을 아낀다."""
    targets = []
    for assets_dir in sorted(glob.glob(os.path.join(capture_dir, "*", "assets"))):
        for name in sorted(os.listdir(assets_dir)):
            if name.lower().endswith(".png"):
                targets.append(os.path.join(assets_dir, name))
    targets.extend(sorted(glob.glob(os.path.join(capture_dir, "*", "product.png"))))
    return targets


def product_prefix_for(image_path, capture_dir):
    """이미지 경로에서 어떤 상품 폴더에 속하는지 역산한다.
    '<capture_dir>/<product>/assets/asset_001_img.png' -> '<capture_dir>/<product>'
    '<capture_dir>/<product>/product.png' -> '<capture_dir>/<product>'"""
    if os.path.basename(image_path) == "product.png":
        return os.path.dirname(image_path)
    parent_dir = os.path.dirname(image_path)
    if os.path.basename(parent_dir) == "assets":
        return os.path.dirname(parent_dir)
    return parent_dir


def image_output_path(image_path, crawl_dir, ocr_dir):
    """crawl_dir 내 이미지 경로를 ocr_dir 내 텍스트 경로로 변환한다."""
    crawl_product_dir = product_prefix_for(image_path, crawl_dir)
    rel_product = os.path.relpath(crawl_product_dir, crawl_dir)
    out_dir = os.path.join(ocr_dir, rel_product, "ocr_text")
    relative = os.path.relpath(image_path, crawl_product_dir)
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
    # 행 재조합(탭/공백 구분)이 끝난 뒤에 띄어쓰기를 복원한다. 재조합 전에
    # 하면 문자 수가 바뀌어 열 간격 판단(_row_to_line의 char_w 계산)이
    # 틀어질 수 있어, 최종 줄 단위로만 적용한다.
    return "\n".join(correct_spacing(_row_to_line(r)) for r in rows)


_ISOLATE_TIMEOUT_SEC = 300  # 상품 폴더 하나에 이미지가 여러 개일 수 있어 여유 있게 잡는다
_ISOLATE_MAX_RETRIES = 3


def _ocr_one_inprocess(image_path, text_path):
    """이미지 하나를 현재 프로세스 안에서 OCR한다 (엔진을 새로 만들지
    않고 get_engine()의 캐시를 그대로 재사용). --batch 모드 안에서
    같은 상품의 이미지 여러 개를 한 엔진으로 처리할 때 쓴다."""
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
        return None

    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    elapsed = time.perf_counter() - start_time
    print(f"  ✅ OCR 완료 → {text_path} ({len(text.splitlines())}줄)")
    print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
    if text.strip():
        print(f"  미리보기: {text[:150].strip()}")
    return text


def _is_cached(image_path, text_path):
    return (config.OCR_CACHE_ENABLED and os.path.exists(text_path) and
            os.path.getmtime(text_path) >= os.path.getmtime(image_path))


def _run_batch_isolated(pairs):
    """같은 상품 폴더의 이미지들을 한 프로세스에서 처리한다 (엔진을 한
    번만 불러와 재사용). 이미지 하나마다 새 프로세스를 쓰면 이 환경에서
    엔진 로딩(수 초~수십 초)이 이미지 수만큼 반복돼 느려지는 걸 실측했다
    (예전 OCR 코드는 페이지 전체를 한 프로세스에서 한 엔진으로 처리해
    이미지가 커도 오래 안 걸렸다). 상품 폴더 단위로 묶으면 그 정도
    속도를 대부분 되찾으면서도, 프로세스가 죽거나 멈춰도 그 상품의
    이미지들만 영향받고 나머지 상품은 무관하게 유지된다. 이미 이
    프로세스 안에서 처리 완료된 이미지는 파일로 남으므로 재시도 시
    남은 것만 다시 보낸다."""
    remaining = list(pairs)
    for attempt in range(1, _ISOLATE_MAX_RETRIES + 1):
        args = [sys.executable, __file__, "--batch"]
        for image_path, text_path in remaining:
            args += [image_path, text_path]
        try:
            subprocess.run(args, timeout=_ISOLATE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            print(f"    프로세스가 {_ISOLATE_TIMEOUT_SEC}초 동안 응답이 없어 종료합니다 "
                  f"({attempt}/{_ISOLATE_MAX_RETRIES})")

        remaining = [(i, t) for i, t in remaining if not _is_cached(i, t)]
        if not remaining:
            return
        if attempt < _ISOLATE_MAX_RETRIES:
            print(f"    {len(remaining)}개 남음, 재시도합니다 ({attempt}/{_ISOLATE_MAX_RETRIES})")


def ocr_capture_dir(crawl_dir, ocr_dir=None):
    """crawl_dir의 이미지를 OCR해 ocr_dir에 텍스트를 저장한다.
    ocr_dir 미지정 시 ocr/output/<run_name>/ 을 자동으로 사용한다."""
    if ocr_dir is None:
        run_name = os.path.basename(os.path.abspath(crawl_dir))
        ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name)
    os.makedirs(ocr_dir, exist_ok=True)

    print("=" * 50)
    print("PaddleOCR (좌표 기반 표 구조 재조립)")
    print("=" * 50)

    images = find_ocr_targets(crawl_dir)
    if not images:
        print(f"❌ '{crawl_dir}'에 OCR 대상 이미지가 없습니다. main.py를 먼저 실행하세요.")
        return {}

    print(f"총 {len(images)}개 이미지 발견\n")

    # 상품 폴더별로 그룹핑 — 같은 상품의 이미지들을 한 프로세스에서 처리한다.
    by_product = {}
    for image_path in images:
        by_product.setdefault(product_prefix_for(image_path, crawl_dir), []).append(image_path)

    combined_by_crawl_prefix = {}
    pipeline_start = time.perf_counter()
    ocr_count, cache_hit_count = 0, 0

    for crawl_prefix, product_images in by_product.items():
        pending = []
        for image_path in product_images:
            text_path = image_output_path(image_path, crawl_dir, ocr_dir)
            if _is_cached(image_path, text_path):
                print(f"\n  파일: {image_path}\n  (캐시 사용, OCR 생략)")
                cache_hit_count += 1
            else:
                pending.append((image_path, text_path))

        if pending:
            _run_batch_isolated(pending)
            ocr_count += len(pending)

        chunks = []
        for image_path in product_images:
            text_path = image_output_path(image_path, crawl_dir, ocr_dir)
            if os.path.exists(text_path):
                with open(text_path, encoding="utf-8") as f:
                    text = f.read().strip()
                if text:
                    chunks.append(text)
        if chunks:
            combined_by_crawl_prefix[crawl_prefix] = chunks

    # 상품별로 OCR 텍스트를 합쳐 ocr_dir 내 대응 폴더에 저장한다.
    # extract_info.py가 이 파일을 읽는다.
    for crawl_prefix, chunks in combined_by_crawl_prefix.items():
        rel = os.path.relpath(crawl_prefix, crawl_dir)
        ocr_product_dir = os.path.join(ocr_dir, rel)
        os.makedirs(ocr_product_dir, exist_ok=True)
        with open(os.path.join(ocr_product_dir, "ocr_combined.txt"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(chunks))

    total_elapsed = time.perf_counter() - pipeline_start
    print(f"\n📄 OCR 텍스트 저장 위치: {os.path.abspath(ocr_dir)}")
    print(f"   실제 OCR 실행: {ocr_count}개 / 캐시 재사용: {cache_hit_count}개")
    print(f"⏱️  OCR 전체 소요 시간: {total_elapsed:.1f}초")
    return ocr_dir


def _exit_now(code):
    """작업은 끝났는데 프로세스가 안 죽고 멈추는 경우를 실측했다 (paddle
    네이티브 라이브러리가 인터프리터 종료 시 정리 단계에서 멈추는 것으로
    추정). sys.exit()은 이 정리 단계를 거치므로 못 피한다. os._exit()로
    정리 단계 자체를 건너뛰고 즉시 종료한다 (버퍼는 먼저 수동으로 비운다).
    --batch 프로세스는 어차피 _run_batch_isolated가 타임아웃으로
    감독하니, 이건 정상 종료를 더 빠르게 만드는 것일 뿐 안전망이
    이중으로 있다."""
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--batch":
        # 격리 모드: 상품 하나(또는 그 일부)의 이미지들을 한 엔진으로
        # 처리한다 (_run_batch_isolated가 띄우는 자식 프로세스의
        # 진입점). image_path/text_path 쌍이 번갈아 온다.
        _pairs = list(zip(sys.argv[2::2], sys.argv[3::2]))
        for _image_path, _text_path in _pairs:
            if _is_cached(_image_path, _text_path):
                continue  # 같은 배치의 이전 시도에서 이미 처리됨
            _ocr_one_inprocess(_image_path, _text_path)
        _exit_now(0)

    crawl_target = sys.argv[1] if len(sys.argv) > 1 else find_latest_capture_dir(
        os.path.join(_ROOT, "crawl", "output")
    )
    ocr_capture_dir(crawl_target)
