import os
import subprocess
import sys
import time

if sys.platform == "win32":
    # PaddleOCR 네이티브 추론이 크래시(access violation 등)하면 Windows가
    # "python.exe이(가) 작동을 멈췄습니다" GUI 팝업을 띄우고, 사용자가 그
    # 팝업을 닫기 전까지 프로세스가 멈춘 채로 대기한다. 자동화된 배치
    # 실행에서는 이게 "그냥 멈춰버린 것"처럼 보이는 원인이었다 (실측).
    # SEM_NOGPFAULTERRORBOX로 이 프로세스에 한해서만 그 팝업을 끄고, 대신
    # 즉시 비정상 종료 코드로 빠지게 한다 (아래 재시도 루프가 이어받는다).
    # 시스템 전역 설정(레지스트리 등)은 건드리지 않는다.
    import ctypes
    SEM_NOGPFAULTERRORBOX = 0x0002
    ctypes.windll.kernel32.SetErrorMode(SEM_NOGPFAULTERRORBOX)

if __name__ == "__main__" and not sys.flags.utf8_mode:
    # 한국어 Windows(cp949) 콘솔 인코딩으로는 이모지 등 일부 문자를 print()할 때
    # UnicodeEncodeError가 난다 (예: OCR 완료 메시지의 ✅). UTF-8 모드 자식
    # 프로세스로 재실행해서 피한다.
    #
    # 이 재실행 구조에 재시도를 얹은 이유: 이 환경(RAM 7.7GB, GPU 없음)에서는
    # PaddleOCR 네이티브 추론이 드물게 죽는다 (segfault 등 비정상 종료 —
    # Python try/except로 못 잡고 프로세스 자체가 죽는다). OCR_CACHE_ENABLED
    # 덕분에 죽기 전까지 처리된 이미지는 이미 텍스트로 저장돼 있으므로,
    # 재시작하면 캐시를 건너뛰고 남은 이미지부터 이어서 처리된다.
    #
    # 재시도 사이에 대기 시간이 반드시 필요하다: PaddleOCR 엔진 초기화 자체가
    # 무거운 네이티브 메모리 할당이라, 크래시 직후 곧바로 재시작하면 OS가 이전
    # 프로세스의 메모리를 아직 회수하지 못한 상태라 "RuntimeError: resource
    # unavailable try again"으로 또 실패하거나 다시 segfault가 난다 (실측:
    # 대기 없이 연속 재시작 시 3회 중 2회 실패, 20초 대기 시 3회 중 3회 성공).
    os.environ["PYTHONUTF8"] = "1"
    _MAX_RETRIES = 10
    _RETRY_DELAY_SEC = 20
    result = None
    for _attempt in range(1, _MAX_RETRIES + 1):
        result = subprocess.run([sys.executable, "-X", "utf8", __file__, *sys.argv[1:]])
        if result.returncode == 0:
            sys.exit(0)
        print(f"OCR 프로세스가 비정상 종료됐습니다 (exit {result.returncode}). "
              f"{_RETRY_DELAY_SEC}초 대기 후 캐시를 활용해 이어서 재시도합니다 "
              f"({_attempt}/{_MAX_RETRIES}).")
        time.sleep(_RETRY_DELAY_SEC)
    sys.exit(result.returncode)

import glob
import time

import numpy as np
from PIL import Image

import importlib.util as _ilu

_SELF = os.path.dirname(os.path.abspath(__file__))  # ocr/
_ROOT = os.path.dirname(_SELF)                       # 루트
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# `python ocr/paddle_ocr.py`로 직접 실행하면 ocr/가 상대 임포트의 부모
# 패키지로 인식 안 되므로, 위에서 sys.path에 넣어둔 루트 기준 절대 임포트로
# 가져온다 (직접 실행/`from ocr import paddle_ocr` 양쪽 다 동작).
from ocr.spacing import correct_spacing

# crawler.py가 먼저 crawl/config.py를 sys.modules['config']에 등록하므로
# importlib으로 경로를 직접 지정해 캐시 충돌을 피한다.
_cfg = _ilu.spec_from_file_location("ocr_config", os.path.join(_SELF, "config.py"))
config = _ilu.module_from_spec(_cfg)
_cfg.loader.exec_module(config)

# 캐시 유효성 판단 기준 시각. 이미지 mtime만 보면 OCR 코드/설정을 고쳐도
# 예전 코드로 만든 결과를 계속 재사용해버린다 (실측: config.py 수정 후에도
# 캐시가 구버전 인식 결과를 그대로 서빙). 코드/설정 파일 자체의 mtime도
# 캐시 기준에 포함해, 둘 중 하나라도 바뀌면 캐시를 무효화한다.
_CODE_MTIME = max(
    os.path.getmtime(__file__),
    os.path.getmtime(os.path.join(_SELF, "config.py")),
    os.path.getmtime(os.path.join(_SELF, "spacing.py")),
)

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
        # ocr_version="PP-OCRv3"과 함께 줘야 lang="korean"이 실제로 반영된다.
        # text_detection_model_name처럼 모델명을 직접 지정하면 paddleocr가
        # lang/ocr_version을 통째로 무시해버리니 여기서는 절대 모델명을 넘기지
        # 않는다 (ocr/config.py의 OCR_VERSION 주석 참고).
        ocr_version=config.OCR_VERSION,
        text_det_limit_side_len=config.OCR_TEXT_DET_LIMIT_SIDE_LEN,
        text_det_limit_type=config.OCR_TEXT_DET_LIMIT_TYPE,
    )

    try:
        _OCR_ENGINE = PaddleOCR(**kwargs)
        return _OCR_ENGINE
    except TypeError as error:
        # 설치된 버전이 지원하지 않는 파라미터가 있으면 제거하고 한 번 더 시도
        if "ocr_version" in str(error):
            print("  (참고) 설치된 paddleocr 버전이 'ocr_version' 파라미터를 지원하지 않아 제외하고 재시도합니다.")
            del kwargs["ocr_version"]
            _OCR_ENGINE = PaddleOCR(**kwargs)
            return _OCR_ENGINE
        raise


# 실측: 이미지를 많이(20개 이상) 연속으로 처리하면 같은 이미지가 매번 배치
# 뒷부분에서만 "Unknown exception"으로 실패한다 (그 이미지만 단독 실행하면
# 항상 성공). 이 환경(RAM 7.7GB)에서 네이티브 추론 메모리가 프로세스 수명
# 동안 누적/파편화되는 것으로 보인다. N개마다 엔진을 통째로 버리고 새로
# 만들어 누적 상태를 주기적으로 정리한다. 모델 재로딩 비용(수 초)이 들지만
# 배치 뒷부분에서의 실패율을 크게 낮춘다.
_ENGINE_RECYCLE_EVERY = 15
_engine_use_count = 0


def reset_engine_if_due():
    global _OCR_ENGINE, _engine_use_count
    _engine_use_count += 1
    if _engine_use_count >= _ENGINE_RECYCLE_EVERY:
        _OCR_ENGINE = None
        _engine_use_count = 0
        import gc
        gc.collect()


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

    while y < height:
        engine = get_engine()  # 주기적으로 리셋되므로 타일마다 다시 받아온다
        bottom = min(y + config.OCR_TILE_HEIGHT, height)
        tile = np.array(img.crop((0, y, width, bottom)))
        result = engine.predict(tile)  # 3.x: predict() / cls 인자 없음
        reset_engine_if_due()
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


def ocr_image(image_path, text_path):
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px")
    start_time = time.perf_counter()

    if img.height > config.OCR_MAX_IMAGE_HEIGHT:
        # 타일링을 거쳐도 이 높이를 넘으면 메모리 부족으로 프로세스 자체가
        # 세그폴트로 죽는 걸 실측했다 (try/except로 못 잡음, 배치 전체 중단).
        # 크래시로 전체를 멈추느니 이 자산 하나만 건너뛴다.
        elapsed = time.perf_counter() - start_time
        print(f"  ⚠️  이미지가 너무 높아({img.height}px > {config.OCR_MAX_IMAGE_HEIGHT}px) 건너뜁니다 (세그폴트 방지)")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return None, elapsed

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

    # crawl 상품 폴더 경로를 키로 텍스트를 모은다.
    combined_by_crawl_prefix = {}
    pipeline_start = time.perf_counter()
    ocr_count, cache_hit_count = 0, 0

    for image_path in images:
        text_path = image_output_path(image_path, crawl_dir, ocr_dir)
        crawl_prefix = product_prefix_for(image_path, crawl_dir)

        if config.OCR_CACHE_ENABLED and os.path.exists(text_path) and \
                os.path.getmtime(text_path) >= max(os.path.getmtime(image_path), _CODE_MTIME):
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
            combined_by_crawl_prefix.setdefault(crawl_prefix, []).append(text.strip())

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


if __name__ == "__main__":
    crawl_target = sys.argv[1] if len(sys.argv) > 1 else find_latest_capture_dir(
        os.path.join(_ROOT, "crawl", "output")
    )
    ocr_capture_dir(crawl_target)
