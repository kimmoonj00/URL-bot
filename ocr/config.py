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
# PP-OCRv3 + lang="korean"은 한국어 전용 인식 모델을 쓴다. 자연스러운
# 한국어 문장(마케팅 카피 등)에는 이게 가장 정확하다 — 실측상
# ocr_version="PP-OCRv5"(아래 OCR_FOREIGN_LANG_OCR_VERSION)로 바꾸면
# 범용 다국어 모델이 선택되는데, 이 모델은 영문·숫자/코드 위주 텍스트는
# 훨씬 정확하지만(예: 지멘스 영문 페이지, 규격표 모델번호) 자연스러운
# 한국어 문장은 한자로 오인식하는 경우가 많아 오히려 크게 나빠진다
# (실측: 다나와 마케팅 카피가 "早企 6 号" 같은 의미 없는 한자로 깨짐).
# 그래서 상품별로 언어를 감지해(detect_product_lang) 둘 중 하나를 고른다.
OCR_VERSION = "PP-OCRv3"
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

# 상품 폴더의 context.md(crawl/이 이미 만들어 둔 DOM 표+텍스트
# 마크다운)에서 한글 비율이 낮고 라틴 문자가 일정량 이상이면 외국어
# 페이지로 보고 OCR_FOREIGN_LANG_OCR_VERSION을 대신 쓴다. 실측 결과
# 한국어 사이트는 영문이 섞여도 한글 비율이 최소 36% 이상이었고,
# 순수 영문 사이트(지멘스)는 0.01%였다 — 그 사이 어디든 안전한
# 경계선이라 5%로 넉넉히 잡는다. 절대 개수 0으로 비교하지 않는 이유:
# crawl/이 페이지 언어와 무관하게 항상 붙이는 한국어 템플릿 글자
# ("...(생략)" 같은 잘림 표시 등)가 섞여 있어 완전한 영문 페이지도
# 한글이 0개가 아닌 경우가 있다(실측).
OCR_FOREIGN_LANG_OCR_VERSION = "PP-OCRv5"
OCR_LANG_DETECT_MIN_LATIN_CHARS = 30
OCR_LANG_DETECT_MAX_HANGUL_RATIO = 0.05

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
