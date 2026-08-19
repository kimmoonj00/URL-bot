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
# 인식 단계에서 텍스트 조각을 하나씩 순서대로 돌리지 않고 이 개수만큼
# 묶어서 한 번에 추론한다 (mooonjooo 브랜치 ocr/engine.py에서 확인).
# 안정성 구조(상품 폴더별 프로세스 격리)는 그대로 두고 순수하게 추론
# 속도만 올리는 옵션이라 크래시 방지 로직과 무관하다.
OCR_TEXT_RECOGNITION_BATCH_SIZE = 16
# 스캔 문서용 전처리. 웹페이지 스크린샷은 이미 똑바르므로 꺼둔다.
OCR_USE_DOC_ORIENTATION_CLASSIFY = False
OCR_USE_DOC_UNWARPING = False
# oneDNN 가속을 아예 끈다. None으로 두면 파라미터 자체를 안 넘긴다.
OCR_ENABLE_MKLDNN = False
# 서버형 모델에서 oneDNN 오류가 재현됐을 때의 우회책. 빈 문자열/None이면 기본값 사용.
# 모델명을 직접 지정하면 paddleocr가 lang/ocr_version을 무시하고, 로컬에 이미
# 캐시된 모델이 있어도 이 네트워크 환경(SSL 인증서 문제)에서 재확인/다운로드를
# 시도하다 응답 없이 멈추는 걸 실측했다. 그래서 비워서 기본값(lang 기반 자동
# 선택)을 쓰게 한다.
OCR_TEXT_DETECTION_MODEL_NAME = ""
OCR_USE_PADDLE_FALLBACK = False
