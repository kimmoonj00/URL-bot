import os

_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(_DIR), "crawl", "output")  # crawl 결과물 위치

OCR_TILE_HEIGHT = 1200
OCR_TILE_OVERLAP = 100
OCR_CONFIDENCE_THRESHOLD = 0.30
OCR_PADDLE_FALLBACK_THRESHOLD = 0.55
OCR_CACHE_ENABLED = True
OCR_FAST_MODE = True
OCR_MAX_INPUT_WIDTH = 1600
OCR_NUMERIC_REREAD = False
OCR_TABLE_FIRST = True
OCR_TABLE_MIN_WIDTH_RATIO = 0.20

# PaddleOCR 좌표 재조립 파라미터
OCR_IOU_THRESHOLD = 0.5
OCR_ROW_TOLERANCE = 0.6
OCR_COL_GAP_RATIO = 2.5

# PaddleOCR 엔진 초기화 파라미터
OCR_LANG = "korean"
# 텍스트 방향 분류 모델도 문서방향보정과 같은 계열(PP-LCNet 분류 모델)이라
# 같은 oneDNN 버그를 낼 수 있어 기본은 꺼둔다.
OCR_USE_TEXTLINE_ORIENTATION = False
OCR_TEXT_DET_LIMIT_SIDE_LEN = 4000
OCR_TEXT_DET_LIMIT_TYPE = "max"
# 스캔 문서용 전처리. 웹페이지 스크린샷은 이미 똑바르므로 꺼둔다.
OCR_USE_DOC_ORIENTATION_CLASSIFY = False
OCR_USE_DOC_UNWARPING = False
# oneDNN 가속을 아예 끈다. None으로 두면 파라미터 자체를 안 넘긴다.
OCR_ENABLE_MKLDNN = False
# 서버형 모델에서 oneDNN 오류가 재현됐을 때의 우회책. 빈 문자열/None이면 기본값 사용.
OCR_TEXT_DETECTION_MODEL_NAME = "PP-OCRv5_mobile_det"
OCR_USE_PADDLE_FALLBACK = False
