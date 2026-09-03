import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # 한국어 Windows(cp949) 콘솔 인코딩으로는 이모지 등 일부 문자를 print()할 때
    # UnicodeEncodeError가 난다 (예: OCR 실패 메시지의 ❌). 현재 프로세스의
    # stdout/stderr 인코딩만 바꿔서 처리한다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import glob
import json
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

_OCR_ENGINE = None


def _base_engine_kwargs():
    return dict(
        use_textline_orientation=config.OCR_USE_TEXTLINE_ORIENTATION,
        # 스캔 문서용 전처리(카메라로 비스듬히 찍은 종이를 펴주는 기능). 웹페이지
        # 스크린샷은 이미 똑바르므로 꺼둔다. Windows oneDNN 환경에서 이 모델들이
        # "ConvertPirAttribute2RuntimeAttribute" 오류를 내는 버그도 이걸로 회피된다.
        use_doc_orientation_classify=config.OCR_USE_DOC_ORIENTATION_CLASSIFY,
        use_doc_unwarping=config.OCR_USE_DOC_UNWARPING,
        text_det_limit_side_len=config.OCR_TEXT_DET_LIMIT_SIDE_LEN,
        text_det_limit_type=config.OCR_TEXT_DET_LIMIT_TYPE,
        text_recognition_batch_size=config.OCR_TEXT_RECOGNITION_BATCH_SIZE,
    )


def _build_engine(kwargs):
    """설치된 paddleocr/paddlex 버전에 따라 일부 파라미터가 없을 수 있어
    TypeError가 나면 문제되는 파라미터를 하나씩 제거하며 재시도한다."""
    from paddleocr import PaddleOCR

    kwargs = dict(kwargs)
    while True:
        try:
            return PaddleOCR(**kwargs)
        except TypeError as error:
            removed = False
            for key in ("enable_mkldnn", "text_detection_model_name",
                        "text_recognition_model_name", "text_recognition_batch_size"):
                if key in kwargs and key in str(error):
                    print(f"  (참고) 설치된 paddleocr 버전이 '{key}' 파라미터를 지원하지 않아 제외하고 재시도합니다.")
                    del kwargs[key]
                    removed = True
                    break
            if not removed:
                raise


def get_engine():
    """PaddleOCR 엔진은 로딩이 무거우니 지연 초기화 + 1회만 생성한다.

    검출/인식 모델을 명시적으로(PP-OCRv5 mobile 조합) 고정해 먼저 시도한다.
    2026-08-23 실측(같은 타일 기준): PP-OCRv3 대비 예측 시간은 5.5초→7.6초로
    소폭 늘지만 오독("2.4GHZ"→"24GHZz" 등)이 사라지고 신뢰도가 0.94~1.00으로
    오른다. paddleocr 기본값(버전 미지정 시 서버형 검출 모델)은 66초로 12배
    느려 쓰지 않는다. 이 조합 초기화가 실패하면(모델 다운로드 불가 등)
    과거부터 검증된 lang 기반 자동 선택(PP-OCRv3)으로 자동 폴백한다."""
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE

    kwargs = _base_engine_kwargs()
    if config.OCR_ENABLE_MKLDNN is not None:
        kwargs["enable_mkldnn"] = config.OCR_ENABLE_MKLDNN

    preferred = dict(kwargs, lang=config.OCR_LANG)
    if config.OCR_TEXT_DETECTION_MODEL_NAME:
        preferred["text_detection_model_name"] = config.OCR_TEXT_DETECTION_MODEL_NAME
    if config.OCR_TEXT_RECOGNITION_MODEL_NAME:
        preferred["text_recognition_model_name"] = config.OCR_TEXT_RECOGNITION_MODEL_NAME

    try:
        _OCR_ENGINE = _build_engine(preferred)
        return _OCR_ENGINE
    except Exception as error:
        print(f"  ⚠️  선호 OCR 모델 조합 초기화 실패({error}), "
              f"안전망 조합({config.OCR_FALLBACK_OCR_VERSION})으로 재시도합니다.")

    fallback = dict(kwargs, lang=config.OCR_LANG, ocr_version=config.OCR_FALLBACK_OCR_VERSION)
    _OCR_ENGINE = _build_engine(fallback)
    return _OCR_ENGINE


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


def image_cache_path(image_path, crawl_dir):
    """crawl_dir 내 이미지 경로를 이미지별 OCR 캐시 텍스트 경로로 변환한다.

    ocr/output/<run>/<product>/에는 상품당 ocr_asset.txt + product.md
    두 파일만 남기기로 했으므로(2026-08-23), 이미지별 중간 결과는 최종
    출력이 아닌 config.CACHE_DIR(ocr/cache/, git 제외) 아래에 보관한다.
    재실행 시 이미지 단위 캐시 재사용(속도)은 그대로 유지된다."""
    run_name = os.path.basename(os.path.abspath(crawl_dir))
    crawl_product_dir = product_prefix_for(image_path, crawl_dir)
    rel_product = os.path.relpath(crawl_product_dir, crawl_dir)
    out_dir = os.path.join(config.CACHE_DIR, run_name, rel_product)
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


# ── 2.5. 다열(multi-column) 레이아웃 분리 ────────────────────────────────────

def _column_split_x(words):
    """words 전체의 x축 상에서 서로 다른 열을 가르는 빈 구간이 있으면 그
    경계 x좌표를 반환한다. 없으면 None. (예: 왼쪽 캡션 영역 vs 오른쪽 표)"""
    if len(words) < 4:
        return None

    intervals = sorted((w["x1"], w["x2"]) for w in words)
    merged = [list(intervals[0])]
    for x1, x2 in intervals[1:]:
        if x1 <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], x2)
        else:
            merged.append([x1, x2])
    if len(merged) < 2:
        return None

    total_span = merged[-1][1] - merged[0][0]
    median_w = sorted(w["w"] for w in words)[len(words) // 2]

    best_gap, best_width = None, 0
    for i in range(len(merged) - 1):
        gap_start, gap_end = merged[i][1], merged[i + 1][0]
        width = gap_end - gap_start
        if width > best_width:
            best_gap, best_width = (gap_start, gap_end), width
    if best_gap is None:
        return None

    # 문장 사이 자연스러운 공백과 구분: 평균 글자폭의 여러 배 + 전체 폭 대비
    # 일정 비율 이상이어야 진짜 열 경계로 본다.
    if best_width < max(median_w * 4, total_span * config.OCR_COLUMN_GAP_MIN_RATIO):
        return None

    split_x = (best_gap[0] + best_gap[1]) / 2
    left = [w for w in words if w["xc"] < split_x]
    right = [w for w in words if w["xc"] >= split_x]
    if not left or not right:
        return None

    # 좌/우가 실제로 나란히 배치된 열인지: 세로 범위가 상당 부분 겹쳐야 한다
    # (안 겹치면 그냥 위아래로 떨어진 별개 블록일 뿐, 열이 아니다).
    ly1, ly2 = min(w["y1"] for w in left), max(w["y2"] for w in left)
    ry1, ry2 = min(w["y1"] for w in right), max(w["y2"] for w in right)
    overlap = max(0, min(ly2, ry2) - max(ly1, ry1))
    if overlap < 0.4 * min(ly2 - ly1, ry2 - ry1):
        return None

    return split_x


def _split_into_columns(words):
    """words를 좌→우 순서의 열 단위 그룹으로 나눈다. 열 경계가 없으면
    [words] 그대로 반환. 3열 이상도 대응하도록 재귀적으로 다시 나눠본다."""
    split_x = _column_split_x(words)
    if split_x is None:
        return [words]
    left = [w for w in words if w["xc"] < split_x]
    right = [w for w in words if w["xc"] >= split_x]
    return _split_into_columns(left) + _split_into_columns(right)


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


# ── 4.5. 표 영역 재인식 (크롭 → 고배율 → 열 그리드) ─────────────────────────

def _has_hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in s)


def _row_y(row: list) -> float:
    return sum(w["yc"] for w in row) / len(row)


def _find_table_run(rows: list):
    """행 목록에서 '연속으로 표처럼 보이는'(정렬된 단어 N개 이상) 가장 긴
    구간을 찾고, 그 위/아래로 세로 간격이 표의 행 간격과 비슷한 행은
    단어 수가 적어도(붙어 인식된 행) 구간에 포함시킨다. (start, end) 반환,
    조건 미달이면 None."""
    min_cols = config.OCR_TABLE_MIN_COLS
    best, i, n = None, 0, len(rows)
    while i < n:
        if len(rows[i]) < min_cols:
            i += 1
            continue
        j = i
        while j < n and len(rows[j]) >= min_cols:
            j += 1
        if best is None or (j - i) > (best[1] - best[0]):
            best = (i, j)
        i = j
    if not best or best[1] - best[0] < config.OCR_TABLE_MIN_ROWS:
        return None
    counts = [len(rows[k]) for k in range(*best)]
    # 진짜 표는 행마다 셀 수가 비슷하다. 폭이 크면(뉴스 스샷 몽타주 등 잡음이
    # 우연히 걸린 것) 재인식 대상에서 뺀다.
    if max(counts) < min_cols + 1 or max(counts) - min(counts) > min_cols:
        return None

    s, e = best
    ys = [_row_y(rows[k]) for k in range(s, e)]
    pitch = (ys[-1] - ys[0]) / max(1, len(ys) - 1)   # 표의 평균 행 간격
    while e < n and 1 <= len(rows[e]) and _row_y(rows[e]) - _row_y(rows[e - 1]) < pitch * 1.8:
        e += 1
    while s > 0 and 1 <= len(rows[s - 1]) and _row_y(rows[s]) - _row_y(rows[s - 1]) < pitch * 1.8:
        s -= 1
    return (s, e)


# 표 셀에서 "모델번호 + 붙어버린 첫 수치"를 떼어낸다. 머리와 꼬리 사이에
# 실제 구분(공백) 또는 소수점/콤마 수치의 시작이 있어야만 매칭 — 깔끔한
# 순수 숫자 모델번호("05007610001")를 "050076100"+"01"로 자르지 않도록.
_GLUED_CELL_RE = re.compile(
    r"^([A-Z][A-Z0-9]*(?:[-/][A-Z0-9]+)+|[A-Z]{2,}[A-Z0-9]*\d|\d{6,})"
    r"(?:\s+|(?=\d+[.,]\d))"
    r"([^\t]*\d[\d.,/][\d.,/]*.*)$"
)


def _column_edges(rows: list, x_left: float, x_right: float) -> list:
    """행들의 단어 [x1,x2]를 x축에 투영해 열 구분선(거의 아무 행도 덮지 않는
    빈 세로 띠)의 중앙 좌표 목록(양끝 포함)을 만든다. 헤더 셀은 데이터 셀과
    폭·위치가 달라 데이터 열 사이 틈을 가리므로, 첫 행(대개 헤더)을 빼고
    '단어 수가 가장 많은' 데이터 행들만으로 투영한다(행 단위 union)."""
    body = rows[1:] if len(rows) > 2 else rows
    max_wc = max(len(r) for r in body)
    ref = [r for r in body if len(r) == max_wc] or body
    span = int(round(x_right - x_left)) + 1
    if span < 10:
        return [x_left, x_right]
    cover = np.zeros(span, dtype=np.int32)
    for r in ref:                                    # 행마다 덮은 구간의 union을 +1
        mask = np.zeros(span, dtype=bool)
        for w in r:
            a = max(0, int(round(w["x1"] - x_left)))
            b = min(span, int(round(w["x2"] - x_left)))
            if b > a:
                mask[a:b] = True
        cover[mask] += 1
    tol = max(0, int(len(ref) * 0.25))               # 이 수 이하로 덮이면 '빈 띠'
    edges, i, min_gap = [x_left], 0, config.OCR_TABLE_COL_SEP_MIN_GAP
    while i < span:
        if cover[i] <= tol:
            j = i
            while j < span and cover[j] <= tol:
                j += 1
            if i > 0 and j < span and (j - i) >= min_gap:
                edges.append(x_left + (i + j) / 2.0)
            i = j
        else:
            i += 1
    edges.append(x_right)
    return edges


def _maybe_split_first_column(grid_rows: list) -> list:
    """대부분의 행에서 첫 칸이 "<모델번호> <나머지>" 꼴이면 첫 칸을 둘로
    쪼갠다 (열 사이에 실제 빈 틈이 없어 model·구성이 한 칸에 묶인 경우)."""
    matches = [_GLUED_CELL_RE.match(cells[0].strip()) if cells else None
               for cells in grid_rows]
    hits = sum(1 for m in matches if m)
    if hits < max(2, len(grid_rows) * 0.5):
        return grid_rows
    out = []
    for cells, m in zip(grid_rows, matches):
        if m:
            out.append([m.group(1), m.group(2).strip()] + list(cells[1:]))
        else:
            out.append([cells[0], ""] + list(cells[1:]))
    return out


def _fill_from_twin_row(grid_rows: list) -> list:
    """variant 표에서 '구성 리스트'(콤마가 가장 많은 칸)가 다른 행과 똑같은데
    어떤 칸이 비었거나 깨졌으면, 그 쌍둥이 행의 값을 가져와 채운다.
    (강조박스가 글자 위를 지나가 SB-LWSL7의 "7"·수량 "7"이 유실된 행을,
    구성이 동일한 SB-LWSS7 행에서 복원.) 채운 뒤 모델 끝 잡숫자도 정리."""
    if len(grid_rows) < 3:
        return grid_rows
    ncol = max(len(r) for r in grid_rows)
    body = [r for r in grid_rows if len(r) == ncol]
    if len(body) < 3:
        return grid_rows

    def list_key(row):
        cell = max(row[1:], key=lambda c: c.count(","), default="")
        return re.sub(r"\s+", "", cell) if cell.count(",") >= 3 else None

    keys = [list_key(r) for r in body]
    for i, r in enumerate(body):
        if keys[i] is None:
            continue
        twin = next((body[j] for j in range(len(body))
                     if j != i and keys[j] == keys[i]), None)
        if twin is None:
            continue
        for ci in range(1, ncol):
            cur, good = r[ci].strip(), twin[ci].strip()
            # 비었거나 구두점만 있는 칸만 채운다 (멀쩡한 값은 건드리지 않음)
            if good and (not cur or re.fullmatch(r"[^\w가-힣]+", cur)):
                r[ci] = good
                if re.fullmatch(r"\d{1,2}", good):          # 모델 끝 잡숫자 제거
                    r[0] = re.sub(rf"^(.+?{good})\d$", r"\1", r[0].strip())
    return grid_rows


def _grid_from_words(words: list):
    """재인식한 word들을 표 그리드(각 행 = 탭 구분 셀)로 재구성한다.
    한글이 든 셀은 kiwi로 띄어쓰기를 복원한다. 열이 부족하면 None."""
    rows = [r for r in _group_rows(words) if r]
    if len(rows) < 2:
        return None
    x_left = min(w["x1"] for r in rows for w in r)
    x_right = max(w["x2"] for r in rows for w in r)
    edges = _column_edges(rows, x_left, x_right)
    n_cols = len(edges) - 1
    if n_cols < config.OCR_TABLE_MIN_COLS - 1:
        return None

    grid_rows = []
    for r in rows:
        cells = [""] * n_cols
        for w in r:
            k = 0
            while k < n_cols - 1 and w["xc"] >= edges[k + 1]:
                k += 1
            cells[k] = (cells[k] + " " + w["text"]).strip() if cells[k] else w["text"]
        grid_rows.append(cells)

    grid_rows = _maybe_split_first_column(grid_rows)
    grid_rows = _fill_from_twin_row(grid_rows)
    if max(len(c) for c in grid_rows) < config.OCR_TABLE_MIN_COLS:
        return None
    # 영문/숫자가 든 셀이 MIN_COLS개 이상인 '멀쩡한' 행이 충분히 있어야
    # 진짜 표로 인정한다 (구두점만 흩어진 잡음 그리드 배제).
    solid = sum(1 for c in grid_rows
                if sum(bool(re.search(r"[0-9A-Za-z가-힣]", x)) for x in c) >= config.OCR_TABLE_MIN_COLS)
    if solid < config.OCR_TABLE_MIN_ROWS:
        return None

    lines = []
    for cells in grid_rows:
        cells = [correct_spacing(c) if _has_hangul(c) else c for c in cells]
        lines.append("\t".join(cells).rstrip("\t"))
    return "\n".join(lines)


def _reocr_table_run(img, table_rows: list):
    """table_rows가 차지하는 영역을 원본에서 잘라 고배율 확대(+어두우면 반전)
    후 타일 없이 1회 predict → 그리드 문자열. 실패하면 None."""
    pad = config.OCR_TABLE_REOCR_PAD
    x1 = max(0, int(min(w["x1"] for r in table_rows for w in r) - pad))
    y1 = max(0, int(min(w["y1"] for r in table_rows for w in r) - pad))
    x2 = min(img.width, int(max(w["x2"] for r in table_rows for w in r) + pad))
    y2 = min(img.height, int(max(w["y2"] for r in table_rows for w in r) + pad))
    # 작은 표일수록 크게 확대한다 (좁은 글씨·겹친 강조박스에서 "7"↔"/1" 같은
    # 오독을 줄인다). 목표 폭 기준, 배율은 [MIN, MAX]로 제한.
    up = max(config.OCR_TABLE_REOCR_UPSCALE_MIN,
             min(config.OCR_TABLE_REOCR_UPSCALE_MAX,
                 config.OCR_TABLE_REOCR_TARGET_W / max(1, x2 - x1)))
    crop = img.crop((x1, y1, x2, y2)).resize(
        (max(1, int((x2 - x1) * up)), max(1, int((y2 - y1) * up))), Image.LANCZOS)
    arr = np.array(crop)
    if float(arr.mean()) < config.OCR_TABLE_DARK_LUMA_THRESHOLD:
        arr = 255 - arr
    words = _words_from_result(get_engine().predict(np.ascontiguousarray(arr)))
    return _grid_from_words(words)


def _render_block(rows: list, img) -> str:
    """블록의 행들을 줄 텍스트로. 표 구간이 있으면 그 부분만 고배율 재인식
    그리드로 바꿔 넣는다."""
    run = _find_table_run(rows) if config.OCR_TABLE_REOCR_ENABLED else None
    if not run:
        return "\n".join(correct_spacing(_row_to_line(r)) for r in rows)

    grid = None
    try:
        grid = _reocr_table_run(img, rows[run[0]:run[1]])
    except Exception as error:
        print(f"    (표 재인식 건너뜀: {error})")

    parts = [correct_spacing(_row_to_line(r)) for r in rows[:run[0]]]
    if grid and grid.strip():
        print(f"    표 재인식: {run[1] - run[0]}행 → {len(grid.splitlines())}행 그리드")
        parts.append(grid)
    else:
        parts += [correct_spacing(_row_to_line(r)) for r in rows[run[0]:run[1]]]
    parts += [correct_spacing(_row_to_line(r)) for r in rows[run[1]:]]
    return "\n".join(parts)


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
    avg_conf = sum(w["conf"] for w in all_words) / len(all_words) if all_words else None
    # 열(column) 단위로 먼저 나눈 뒤 열마다 따로 행을 묶는다 — 안 그러면
    # 같은 y대에 있는 서로 다른 열(예: 좌측 캡션 vs 우측 표)의 텍스트가
    # 한 행으로 섞인다. 행 재조합·띄어쓰기 복원은 _render_block에서 한다.
    blocks = []
    for column_words in _split_into_columns(all_words):
        rows = _group_rows(column_words)
        if rows:
            blocks.append(_render_block(rows, img))
    return "\n\n".join(blocks), avg_conf


_ISOLATE_TIMEOUT_BASE_SEC = 60   # 프로세스 시작 + 엔진 로딩 여유
# 2026-08-23: 이미지 개수 기준 고정치(90초/장)였더니 타일 7~8장짜리
# 초대형 이미지(danawa asset_003: 실측 209초)에서 재시도 예산(150초)이
# 부족해 240초/150초 두 번 타임아웃 나고서야 3번째 시도에서 겨우
# 성공하는 걸 실측(총 488초 소요, ~180초 낭비). 이미지 1장의 실제
# 부하는 "타일 수"에 비례하므로(위 이미지는 7타일, 실측 최대 ~30초/타일)
# 이미지 개수 대신 예상 타일 수로 계산해 여유를 둔다.
_ISOLATE_TIMEOUT_PER_TILE_SEC = 45
_ISOLATE_MAX_RETRIES = 3


def _estimate_tile_count(image_path):
    """run_ocr()의 타일 분할과 동일한 기준(OCR_TILE_HEIGHT)으로 이미지
    하나가 몇 개 타일로 나뉠지 추정한다 (오버랩은 안전 마진으로 무시)."""
    try:
        with Image.open(image_path) as img:
            height = img.height
    except Exception:
        return 1
    return max(1, -(-height // config.OCR_TILE_HEIGHT))  # ceil division


def _ocr_one_inprocess(image_path, text_path):
    """이미지 하나를 현재 프로세스 안에서 OCR한다 (엔진을 새로 만들지
    않고 get_engine()의 캐시를 그대로 재사용). --batch 모드 안에서
    같은 상품의 이미지 여러 개를 한 엔진으로 처리할 때 쓴다."""
    print(f"\n  파일: {image_path}")
    img = Image.open(image_path)
    print(f"  이미지 크기: {img.width}x{img.height}px")
    start_time = time.perf_counter()

    try:
        text, avg_conf = run_ocr(image_path)
    except Exception as e:
        elapsed = time.perf_counter() - start_time
        print(f"  ❌ OCR 실패: {e}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return None

    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)
    # 이미지별 평균 인식 신뢰도를 사이드카 파일로 저장 — GPT가 만든 텍스트를
    # 거치면 값이 재구성/의역돼 특정 항목 하나에 신뢰도를 되짚어 붙일 수는
    # 없지만, "이 이미지에서 뽑은 OCR 텍스트가 전반적으로 얼마나 확실한가"는
    # 상품 단위로 집계해 Slack 결과에 보여줄 수 있다.
    if avg_conf is not None:
        with open(text_path + ".conf", "w", encoding="utf-8") as f:
            f.write(f"{avg_conf:.4f}")
    elif os.path.exists(text_path + ".conf"):
        os.remove(text_path + ".conf")

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
    """이미지들을 한 프로세스(한 엔진)로 처리한다.

    2026-08-23: 상품 폴더 단위로 매번 새 프로세스를 띄우던 것을, 캡처
    실행 전체의 미처리 이미지를 모아 한 번에 넘기도록 바꿨다. 상품이
    N개면 엔진 로딩(수 초)이 N번 반복되던 걸 정상 경로에서는 1번으로
    줄인다. 안전망은 그대로 유지된다 — 프로세스가 죽거나 타임아웃 나도
    아래 재시도 루프가 '아직 캐시 파일이 없는(=처리 안 된)' 이미지만
    골라 새 프로세스로 다시 보낸다. 이미지 단위 판별이라 어느 상품의
    이미지가 죽였든 그 이미지들만 재시도 대상이 되고, 이미 끝난 이미지는
    (다른 상품 것이어도) 영향받지 않는다 — 상품 단위였을 때와 동일한
    격리 보장이 유지된다.
    타임아웃은 남은 이미지들의 예상 타일 수 합계에 비례해 매번 다시
    계산한다 (세로로 아주 긴 이미지 하나가 타일 여러 장을 도는 경우까지
    감안한 여유치 — 이미지 개수만 보면 초대형 이미지에서 예산이 부족할
    수 있다)."""
    remaining = list(pairs)
    for attempt in range(1, _ISOLATE_MAX_RETRIES + 1):
        est_tiles = sum(_estimate_tile_count(image_path) for image_path, _ in remaining)
        timeout = _ISOLATE_TIMEOUT_BASE_SEC + _ISOLATE_TIMEOUT_PER_TILE_SEC * est_tiles
        args = [sys.executable, __file__, "--batch"]
        for image_path, text_path in remaining:
            args += [image_path, text_path]
        try:
            subprocess.run(args, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"    프로세스가 {timeout}초 동안 응답이 없어 종료합니다 "
                  f"({attempt}/{_ISOLATE_MAX_RETRIES})")

        remaining = [(i, t) for i, t in remaining if not _is_cached(i, t)]
        if not remaining:
            return
        if attempt < _ISOLATE_MAX_RETRIES:
            print(f"    {len(remaining)}개 남음, 재시도합니다 ({attempt}/{_ISOLATE_MAX_RETRIES})")


def _write_product_md(ocr_product_dir, crawl_prefix, ocr_chunks):
    """crawl_prefix/context.md(DOM/표/상품영역) 맨 아래에 이미지 OCR 결과를
    이어붙여 ocr_product_dir/product.md로 저장한다. extract/extractor.py가
    이 파일을 context+OCR 통합 컨텍스트로 읽는다. context.md가 없는
    상품(차단/에러 등)은 만들 내용이 없으므로 건너뛴다."""
    context_path = os.path.join(crawl_prefix, "context.md")
    if not os.path.exists(context_path):
        return False

    with open(context_path, encoding="utf-8") as f:
        parts = [f.read().rstrip()]

    if ocr_chunks:
        images_md = "\n\n".join(
            f"### 이미지 {i}\n\n{chunk}" for i, chunk in enumerate(ocr_chunks, 1)
        )
        parts.append("## 이미지 OCR\n\n" + images_md)

    os.makedirs(ocr_product_dir, exist_ok=True)
    with open(os.path.join(ocr_product_dir, "product.md"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts))
    return True


def ocr_capture_dir(crawl_dir, ocr_dir=None):
    """crawl_dir의 이미지를 OCR해 ocr_dir에 상품별 ocr_asset.txt +
    product.md 두 파일만 저장한다(2026-08-23, 최종 출력 정리).
    이미지별 중간 텍스트는 ocr/config.py:CACHE_DIR에 별도 보관해
    ocr_dir을 깨끗하게 유지하면서도 재실행 캐시는 그대로 활용한다.
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

    # 상품 폴더별로 그룹핑 — product.md/ocr_asset.txt를 상품 단위로 쓰기 위함.
    by_product = {}
    for image_path in images:
        by_product.setdefault(product_prefix_for(image_path, crawl_dir), []).append(image_path)

    pipeline_start = time.perf_counter()
    cache_hit_count = 0

    # 1단계: 캡처 실행 전체의 미처리 이미지를 모아 프로세스 1개(엔진 1회
    # 로딩)로 처리한다 (상품마다 프로세스를 새로 띄우던 것에서 개선).
    pending_all = []
    per_product_pairs = {}
    for crawl_prefix, product_images in by_product.items():
        pairs = [(img, image_cache_path(img, crawl_dir)) for img in product_images]
        per_product_pairs[crawl_prefix] = pairs
        for image_path, text_path in pairs:
            if _is_cached(image_path, text_path):
                print(f"\n  파일: {image_path}\n  (캐시 사용, OCR 생략)")
                cache_hit_count += 1
            else:
                pending_all.append((image_path, text_path))

    if pending_all:
        _run_batch_isolated(pending_all)
    ocr_count = len(pending_all)

    # 2단계: 상품별로 이미지 텍스트를 모아 ocr_asset.txt + product.md 저장.
    # context.md가 있는 상품은 이미지가 없거나 OCR이 비어도 product.md를 만든다
    # (extractor.py가 항상 product.md 우선으로 읽으므로 존재만으로 일관되게 둔다).
    combined_by_crawl_prefix = {}
    for crawl_prefix, pairs in per_product_pairs.items():
        chunks = []
        confs = []
        for _image_path, text_path in pairs:
            if os.path.exists(text_path):
                with open(text_path, encoding="utf-8") as f:
                    text = f.read().strip()
                if text:
                    chunks.append(text)
                    conf_path = text_path + ".conf"
                    if os.path.exists(conf_path):
                        with open(conf_path, encoding="utf-8") as f:
                            try:
                                confs.append(float(f.read().strip()))
                            except ValueError:
                                pass
        if chunks:
            combined_by_crawl_prefix[crawl_prefix] = chunks

        rel = os.path.relpath(crawl_prefix, crawl_dir)
        ocr_product_dir = os.path.join(ocr_dir, rel)
        if chunks:
            os.makedirs(ocr_product_dir, exist_ok=True)
            with open(os.path.join(ocr_product_dir, "ocr_asset.txt"), "w", encoding="utf-8") as f:
                f.write("\n\n".join(chunks))
            if confs:
                with open(os.path.join(ocr_product_dir, "ocr_confidence.json"), "w", encoding="utf-8") as f:
                    json.dump({"avg_confidence": round(sum(confs) / len(confs) * 100)}, f)
        _write_product_md(ocr_product_dir, crawl_prefix, chunks)

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
