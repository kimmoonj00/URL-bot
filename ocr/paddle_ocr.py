import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # 한국어 Windows(cp949) 콘솔 인코딩으로는 이모지 등 일부 문자를 print()할 때
    # UnicodeEncodeError가 난다 (예: OCR 실패 메시지의 ❌). 현재 프로세스의
    # stdout/stderr 인코딩만 바꿔서 처리한다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import glob
import re
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

# paddlex는 site-packages 내부에 캐시해 둔 폰트 파일(PingFang-SC-Regular.ttf 등,
# 결과 시각화용이라 우리 텍스트 인식 결과와는 무관)이 없으면 import 시점에
# 곧바로 원격 다운로드를 시도한다. paddlex를 재설치할 때마다 이 캐시가
# 지워지는데, 이 네트워크는 그 다운로드 URL에서 SSL 인증서 검증에 실패해
# (자체 서명 인증서가 체인에 포함됨) import 자체가 죽는다. 로컬 폰트 파일을
# 지정해 다운로드 시도 자체를 건너뛰게 한다.
if not os.environ.get("PADDLE_PDX_LOCAL_FONT_FILE_PATH"):
    _local_font = r"C:\Windows\Fonts\malgun.ttf"
    if os.path.isfile(_local_font):
        os.environ["PADDLE_PDX_LOCAL_FONT_FILE_PATH"] = _local_font

# ocr_version별로 엔진을 따로 캐시한다 — 상품 페이지 언어에 따라
# PP-OCRv3(한국어 전용)와 PP-OCRv5(범용 다국어)를 다르게 골라 쓰기
# 때문이다 (detect_product_lang 참고).
_OCR_ENGINES = {}


def get_engine(ocr_version=None):
    """PaddleOCR 엔진은 로딩이 무거우니 ocr_version별 지연 초기화 +
    캐시한다. 설치된 paddleocr/paddlex 버전에 따라 일부 파라미터가
    없을 수 있어 TypeError가 나면 문제되는 파라미터를 하나씩 제거하며
    재시도한다."""
    ocr_version = ocr_version or config.OCR_VERSION
    if ocr_version in _OCR_ENGINES:
        return _OCR_ENGINES[ocr_version]

    from paddleocr import PaddleOCR

    kwargs = dict(
        use_textline_orientation=config.OCR_USE_TEXTLINE_ORIENTATION,
        # 스캔 문서용 전처리(카메라로 비스듬히 찍은 종이를 펴주는 기능). 웹페이지
        # 스크린샷은 이미 똑바르므로 꺼둔다. Windows oneDNN 환경에서 이 모델들이
        # "ConvertPirAttribute2RuntimeAttribute" 오류를 내는 버그도 이걸로 회피된다.
        use_doc_orientation_classify=config.OCR_USE_DOC_ORIENTATION_CLASSIFY,
        use_doc_unwarping=config.OCR_USE_DOC_UNWARPING,
        lang=config.OCR_LANG,
        # ocr_version을 아예 안 주면 paddleocr==3.0.0이 내부 기본 선택
        # 로직에서 응답 없이 멈추는 걸 실측했다 — 반드시 명시해야 한다.
        # 값 자체(PP-OCRv3 vs PP-OCRv5) 선택 기준은 ocr/config.py의
        # OCR_VERSION 주석과 detect_product_lang 참고.
        ocr_version=ocr_version,
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
            engine = PaddleOCR(**kwargs)
            _OCR_ENGINES[ocr_version] = engine
            return engine
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


_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_product_lang_cache = {}


def detect_product_lang(product_dir):
    """상품 폴더의 context.md(crawl/이 이미 만들어 둔 DOM 표+텍스트
    마크다운)를 보고 이 상품 페이지에 쓸 ocr_version을 고른다. 결과는
    상품 폴더 단위로 캐시한다 (같은 상품의 여러 이미지가 매번 파일을
    다시 읽지 않도록).

    마크다운 제목 줄("## 규격 테이블" 등)과 "- URL:" 줄은 페이지 실제
    언어와 무관하게 crawl/이 항상 한국어로 붙이는 고정 템플릿이라 셈에서
    뺀다 — 안 빼면 완전한 영문 페이지(지멘스 등)도 이 템플릿 글자들
    때문에 한글이 0개가 아니게 돼 항상 한국어로 잘못 판정된다(실측)."""
    if product_dir in _product_lang_cache:
        return _product_lang_cache[product_dir]

    ocr_version = config.OCR_VERSION  # 기본값(한국어). context.md가 없거나 판단이 애매하면 이걸 쓴다.
    context_path = os.path.join(product_dir, "context.md")
    if os.path.exists(context_path):
        with open(context_path, encoding="utf-8") as f:
            lines = f.readlines()
        text = "".join(
            line for line in lines
            if not line.lstrip().startswith("#") and not line.lstrip().startswith("- URL:")
        )
        hangul_count = len(_HANGUL_RE.findall(text))
        latin_count = len(_LATIN_RE.findall(text))
        hangul_ratio = hangul_count / max(hangul_count + latin_count, 1)
        # 한글 비율이 낮고(템플릿 잔여 글자 정도) 라틴 문자가 확실히 많을
        # 때만 외국어로 전환한다. 한글 비중이 있으면(한국어 UI + 영문
        # 모델명 등 흔한 패턴) 한국어 모델을 유지한다 — 자연스러운 한국어
        # 문장에는 그쪽이 훨씬 정확하다(ocr/config.py 주석 참고).
        if (hangul_ratio < config.OCR_LANG_DETECT_MAX_HANGUL_RATIO and
                latin_count >= config.OCR_LANG_DETECT_MIN_LATIN_CHARS):
            ocr_version = config.OCR_FOREIGN_LANG_OCR_VERSION

    _product_lang_cache[product_dir] = ocr_version
    return ocr_version


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


# ── 2.5. x축 큰 간격으로 좌우 블록 분리 ──────────────────────────────────────
# 실측: "왼쪽엔 제품 카드, 오른쪽엔 표"처럼 서로 다른 콘텐츠가 나란히
# 배치된 레이아웃(한국 이커머스에서 흔함)에서, 다음 단계인 y좌표 기반
# 행 그룹핑이 세로 위치가 겹치는 두 블록의 텍스트를 한 줄로 섞어버리는
# 걸 확인했다(나비엠알오 스펙표 예시). 행 그룹핑 전에 이미지 전체에서
# 거의 비어 있는 세로 띠(진짜 컬럼 경계)를 찾아 블록을 먼저 나누고,
# 블록마다 따로 행을 재조합한 뒤 왼쪽→오른쪽 순서로 이어 붙인다.

def _split_into_blocks(words: list) -> list:
    if not words:
        return [words]

    avg_h = sum(w["h"] for w in words) / len(words)
    min_x = min(w["x1"] for w in words)
    max_x = max(w["x2"] for w in words)
    width = max_x - min_x
    if width <= 0 or avg_h <= 0:
        return [words]

    bin_size = max(1.0, avg_h / 4)
    n_bins = int(width / bin_size) + 1
    covered = [False] * n_bins

    def bin_idx(x):
        return min(n_bins - 1, max(0, int((x - min_x) / bin_size)))

    for w in words:
        for b in range(bin_idx(w["x1"]), bin_idx(w["x2"]) + 1):
            covered[b] = True

    # 한 블록 안의 정상적인 열/단어 간격보다 훨씬 큰 빈 구간만 블록
    # 경계로 본다 (_row_to_line의 탭 판단 기준보다 더 큰 값).
    gap_threshold_bins = max(1, int((avg_h * 4) / bin_size))

    ranges, start, i = [], 0, 0
    while i < n_bins:
        if covered[i]:
            i += 1
            continue
        j = i
        while j < n_bins and not covered[j]:
            j += 1
        if j - i >= gap_threshold_bins:
            ranges.append((start, i))
            start = j
        i = j
    ranges.append((start, n_bins))

    if len(ranges) <= 1:
        return [words]

    blocks = []
    for lo, hi in ranges:
        x_lo, x_hi = min_x + lo * bin_size, min_x + hi * bin_size
        block_words = [w for w in words if x_lo <= w["xc"] < x_hi]
        if block_words:
            blocks.append(block_words)
    return blocks if blocks else [words]


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


# ── 4.5. 헤더 열 위치 기준 표 재조합 ──────────────────────────────────────────
# _row_to_line은 "한 행 안에서 단어 사이 간격"만 보고 열을 나누는데, 표의
# 두 열 사이 간격이 원래 좁게 인쇄돼 있으면(실측: 규격표에서 모델명과
# 바로 붙어 나오는 규격값) 그 행 안에서는 간격 자체가 없어 못 나눈다.
# 대신 표의 첫 행(헤더)에서 각 열이 실제로 어디 있는지(x중심좌표)를 먼저
# 파악해두고, 모든 행의 단어를 "가장 가까운 열"에 배정하는 방식이면 그
# 행의 로컬 간격과 무관하게 표 전체 구조를 따라간다.
#
# 다만 이 방식은 진짜 다열 표에서만 써야 한다 — 일반 문단이나 "라벨: 값"
# 한 줄짜리 스펙 목록("라벨: 값" 2열)에도 적용하면 오히려 망가진다(실측:
# 정상적인 라벨/값 탭 구분이 사라짐) — 2열짜리는 이미 _row_to_line의
# 간격 기반 판단이 잘 처리하므로 여기서는 3열 이상만 다룬다. 조건:
# (1) 데이터 행이 최소 3개는 있어야 하고(우연히 줄 2개인 문단 배제),
# (2) 헤더 열 수가 3~6개(표 열 수로 그럴듯한 범위, 2열 제외)여야 하고,
# (3) 모든 행에서 단어들이 왼쪽→오른쪽 순서대로 열 번호도 증가해야
#     한다(표라면 당연한 성질). 하나라도 안 맞으면 표가 아니라고 보고
#     None을 반환해 _row_to_line 방식으로 폴백한다.

def _reconstruct_table_rows(rows: list):
    if len(rows) < 3 or not (3 <= len(rows[0]) <= 6):
        return None

    anchors = [w["xc"] for w in rows[0]]
    assigned_rows = []
    for row in rows:
        assignments = []
        for w in row:
            idx = min(range(len(anchors)), key=lambda i: abs(w["xc"] - anchors[i]))
            assignments.append((idx, w))
        col_order = [idx for idx, _ in assignments]
        if col_order != sorted(col_order):
            return None  # 표라면 있어선 안 되는 순서 역전 — 표가 아니라고 보고 폴백
        assigned_rows.append(assignments)

    lines = []
    for assignments in assigned_rows:
        columns = [[] for _ in anchors]
        for idx, w in assignments:
            columns[idx].append(w)
        cells = []
        for col_words in columns:
            col_words.sort(key=lambda w: w["x1"])
            cells.append(" ".join(w["text"] for w in col_words))
        lines.append("\t".join(cells))
    return lines


# ── 4.5. 소형 텍스트 블록 확대 재인식 ────────────────────────────────────────
# 실측: 표처럼 촘촘하게 작은 글자(평균 높이 16px 미만)가 몰려 있는 블록은
# 원본 해상도 그대로면 거의 못 읽는다("SB-LWSS7 1.5,2,2.5,3,4,5,6"이
# "5E-L55715225345E"로 깨짐). 그 블록만 원본 이미지에서 잘라 확대(5배)한
# 뒤 같은 엔진으로 다시 인식하면 모델명·숫자 패턴이 훨씬 잘 잡힌다(실측
# 확인). 새 모델을 추가로 불러오지 않고 이미 로드된 엔진을 재사용하므로
# 안정성에는 영향이 없고, 이 블록에 한해 추론을 한 번 더 하는 비용만
# 든다.

_REOCR_MAX_AVG_HEIGHT = 20
_REOCR_UPSCALE = 5
_REOCR_PADDING = 4


def _reocr_small_text_block(img, block, engine):
    if not block:
        return block
    avg_h = sum(w["h"] for w in block) / len(block)
    if avg_h > _REOCR_MAX_AVG_HEIGHT:
        return block

    x1 = max(0, int(min(w["x1"] for w in block) - _REOCR_PADDING))
    y1 = max(0, int(min(w["y1"] for w in block) - _REOCR_PADDING))
    x2 = min(img.width, int(max(w["x2"] for w in block) + _REOCR_PADDING))
    y2 = min(img.height, int(max(w["y2"] for w in block) + _REOCR_PADDING))
    if x2 <= x1 or y2 <= y1:
        return block

    crop = img.crop((x1, y1, x2, y2))
    big = crop.resize((crop.width * _REOCR_UPSCALE, crop.height * _REOCR_UPSCALE), Image.LANCZOS)
    try:
        result = engine.predict(np.array(big))
    except Exception:
        return block
    new_words = _words_from_result(result)
    if not new_words:
        return block

    # 확대해서 인식한 좌표를 원본 이미지 좌표계로 되돌린다.
    for w in new_words:
        for key in ("x1", "x2", "xc"):
            w[key] = w[key] / _REOCR_UPSCALE + x1
        for key in ("y1", "y2", "yc"):
            w[key] = w[key] / _REOCR_UPSCALE + y1
        w["h"] /= _REOCR_UPSCALE
        w["w"] /= _REOCR_UPSCALE

    print(f"    소형 텍스트 블록 재인식(평균 높이 {avg_h:.1f}px): "
          f"{len(block)}개 → {len(new_words)}개 단어")
    return new_words


# ── 5. 파이프라인 ─────────────────────────────────────────────────────────────

def run_ocr(image_path, ocr_version=None):
    img = Image.open(image_path).convert("RGB")
    width, height = img.size
    ocr_version = ocr_version or config.OCR_VERSION
    is_korean = ocr_version == config.OCR_VERSION

    all_words = []
    y, tile_idx = 0, 1
    engine = get_engine(ocr_version)

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
    lines = []
    for block in _split_into_blocks(all_words):
        block = _reocr_small_text_block(img, block, engine)
        rows = _group_rows(block)
        table_lines = _reconstruct_table_rows(rows)
        if table_lines is not None:
            lines.extend(table_lines)
        else:
            for row in rows:
                lines.append(_row_to_line(row))
    # 행 재조합(탭/공백 구분)이 끝난 뒤에 띄어쓰기를 복원한다. 재조합 전에
    # 하면 문자 수가 바뀌어 열 간격 판단(_row_to_line의 char_w 계산)이
    # 틀어질 수 있어, 최종 줄 단위로만 적용한다. kiwipiepy는 한국어
    # 형태소 분석기라 외국어 모델(PP-OCRv5) 결과에는 적용하지 않는다.
    if is_korean:
        lines = [correct_spacing(line) for line in lines]
    return "\n".join(lines)


_ISOLATE_TIMEOUT_SEC = 300  # 상품 폴더 하나에 이미지가 여러 개일 수 있어 여유 있게 잡는다
# (180초로 줄여봤지만 정상 처리가 180초를 넘는 경우도 있어 오히려 더 자주
# 죽이고 재시도하게 돼 전체 시간이 늘어나는 걸 실측했다 — 300초가 낫다)
_ISOLATE_MAX_RETRIES = 3


def _ocr_one_inprocess(image_path, text_path, ocr_version=None):
    """이미지 하나를 현재 프로세스 안에서 OCR한다 (엔진을 새로 만들지
    않고 get_engine()의 캐시를 그대로 재사용). --batch 모드 안에서
    같은 상품의 이미지 여러 개를 한 엔진으로 처리할 때 쓴다."""
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px")
    start_time = time.perf_counter()

    try:
        text = run_ocr(image_path, ocr_version)
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


def _run_batch_isolated(pairs, ocr_version):
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
        args = [sys.executable, __file__, "--batch", ocr_version]
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


def _write_context_with_ocr(crawl_prefix, ocr_product_dir, ocr_text):
    """crawl/이 만든 context.md(DOM 표 + 전체 텍스트)에 OCR 텍스트 섹션을
    더해 ocr/output/ 쪽에 저장한다. extract/가 LLM 프롬프트로 그대로
    넘길 수 있는 통합 마크다운을 만들기 위함이다. crawl/output/의 원본
    context.md는 건드리지 않는다 — 각 단계는 자기 출력 폴더에만 쓰고
    상위 단계의 폴더는 읽기만 한다는 규칙을 지킨다."""
    src_path = os.path.join(crawl_prefix, "context.md")
    base_md = ""
    if os.path.exists(src_path):
        with open(src_path, encoding="utf-8") as f:
            base_md = f.read().rstrip()

    section = f"## OCR 추출 텍스트\n\n```\n{ocr_text}\n```\n"
    merged = f"{base_md}\n\n{section}" if base_md else f"# OCR 추출 텍스트\n\n{section}"

    with open(os.path.join(ocr_product_dir, "context.md"), "w", encoding="utf-8") as f:
        f.write(merged)


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
            ocr_version = detect_product_lang(crawl_prefix)
            if ocr_version != config.OCR_VERSION:
                print(f"\n  [{crawl_prefix}] 외국어 페이지로 감지 — {ocr_version} 사용")
            _run_batch_isolated(pending, ocr_version)
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
        ocr_text = "\n\n".join(chunks)
        with open(os.path.join(ocr_product_dir, "ocr_combined.txt"), "w", encoding="utf-8") as f:
            f.write(ocr_text)
        _write_context_with_ocr(crawl_prefix, ocr_product_dir, ocr_text)

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
    if len(sys.argv) >= 5 and sys.argv[1] == "--batch":
        # 격리 모드: 상품 하나(또는 그 일부)의 이미지들을 한 엔진으로
        # 처리한다 (_run_batch_isolated가 띄우는 자식 프로세스의
        # 진입점). sys.argv[2]가 ocr_version, 이후 image_path/text_path
        # 쌍이 번갈아 온다.
        _ocr_version = sys.argv[2]
        _pairs = list(zip(sys.argv[3::2], sys.argv[4::2]))
        for _image_path, _text_path in _pairs:
            if _is_cached(_image_path, _text_path):
                continue  # 같은 배치의 이전 시도에서 이미 처리됨
            _ocr_one_inprocess(_image_path, _text_path, _ocr_version)
        _exit_now(0)

    crawl_target = sys.argv[1] if len(sys.argv) > 1 else find_latest_capture_dir(
        os.path.join(_ROOT, "crawl", "output")
    )
    ocr_capture_dir(crawl_target)
