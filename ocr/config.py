import os

_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(_DIR), "crawl", "output")  # crawl 결과물 위치

OCR_TILE_HEIGHT = 1200
OCR_TILE_OVERLAP = 100
# 이 높이(px)를 넘는 이미지는 타일링을 거쳐도 PaddleOCR 추론 중 메모리 부족으로
# 세그폴트가 나는 걸 실측했다 (이 환경 RAM 7.7GB 기준, danawa의 860x7998px
# 스택형 상세이미지에서 재현 — 프로세스 자체가 죽어 try/except로도 못 잡고
# 배치 전체가 중단됨). 이 높이를 넘는 이미지는 OCR을 건너뛰고 경고만 남긴다.
OCR_MAX_IMAGE_HEIGHT = 6000
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
# PP-OCRv3로 고정한다 (중요, 아래 두 문제 때문에 임의로 올리면 안 됨).
#   1. paddleocr 3.7.0 기준 기본 모델 세대(PP-OCRv5/v6)는 한국어 인식 모델이
#      없다. lang="korean"을 줘도 무시되고 엉뚱한(한글 안 되는) 모델로 인식해
#      한글이 다 깨지거나 아예 인식이 안 된다.
#   2. text_detection_model_name처럼 모델명을 직접 지정하면 paddleocr가
#      "lang과 ocr_version은 무시한다"는 경고를 내고 실제로 lang="korean"을
#      무시해버린다 (실측: PP-OCRv6_medium_rec 같은 비한국어 모델을 골라서
#      로컬 캐시에 없으면 네트워크 다운로드를 시도하다 실패함).
# 그래서 모델명을 직접 지정하지 않고, ocr_version="PP-OCRv3" + lang="korean"
# 조합만으로 paddleocr가 자동으로 "korean_PP-OCRv3_mobile_rec"를 고르게 한다.
# 실제 이미지로 검증: "솔레노이드코일", "장바구니에담기" 등 정상 인식 확인됨.
OCR_VERSION = "PP-OCRv3"
# 텍스트 방향 분류 모델도 문서방향보정과 같은 계열(PP-LCNet 분류 모델)이라
# 같은 oneDNN 버그를 낼 수 있어 기본은 꺼둔다.
OCR_USE_TEXTLINE_ORIENTATION = False
OCR_TEXT_DET_LIMIT_SIDE_LEN = 4000
OCR_TEXT_DET_LIMIT_TYPE = "max"
# 스캔 문서용 전처리. 웹페이지 스크린샷은 이미 똑바르므로 꺼둔다.
OCR_USE_DOC_ORIENTATION_CLASSIFY = False
OCR_USE_DOC_UNWARPING = False
