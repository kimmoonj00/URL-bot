import os

_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(_DIR), "crawl", "output")  # crawl 결과물 위치
CACHE_DIR = os.path.join(_DIR, "cache")  # 이미지별 OCR 캐시(최종 출력물 아님, .gitignore 처리)

OCR_TILE_HEIGHT = 1200
OCR_TILE_OVERLAP = 100
OCR_CONFIDENCE_THRESHOLD = 0.30
OCR_CACHE_ENABLED = True

# ── 표 영역 재인식 ────────────────────────────────────────────────────────────
# 일반 OCR는 배경이 균일한 규격표에서 검출이 행 전체를 한 줄로 뭉치거나
# 타일 경계에서 반쪽만 잡는다("050076200011.06.0125…"). 그래서 '연속된 표
# 행 구간'을 찾아 그 영역만 여유 있게 잘라 고배율로 확대(타일 없이 predict
# 1회)해 다시 인식하고, 깨끗해진 단어를 x좌표로 열에 배정해 탭 그리드로
# 재구성한다. 한글 셀은 kiwi로 띄어쓰기까지 복원한다.
OCR_TABLE_REOCR_ENABLED = True
OCR_TABLE_MIN_ROWS = 4            # 이만큼 연속으로 표스러운 행이 있어야 재인식
OCR_TABLE_MIN_COLS = 3            # 행당 정렬된 단어(셀) 수 하한
# 표 크롭을 이 목표 폭(px)이 되도록 확대한다. 작은 표(예: BUFFALO 렌치표
# ~330px)는 더 크게(강조박스가 글자 위를 지나가 "7"이 "/1"로 뭉개지던 것이
# 살아난다), 큰 표는 덜 키운다. 배율은 [MIN,MAX]로 제한.
OCR_TABLE_REOCR_TARGET_W = 2400
OCR_TABLE_REOCR_UPSCALE_MIN = 3.0
OCR_TABLE_REOCR_UPSCALE_MAX = 6.0
OCR_TABLE_REOCR_PAD = 20          # 크롭 상하좌우 여유(원본 px)
OCR_TABLE_DARK_LUMA_THRESHOLD = 110   # 크롭 평균 밝기 < 이 값이면 색 반전
OCR_TABLE_COL_SEP_MIN_GAP = 14    # 열 경계로 볼 최소 빈 간격(확대 크롭 기준 px)

# PaddleOCR 좌표 재조립 파라미터
OCR_IOU_THRESHOLD = 0.5
OCR_ROW_TOLERANCE = 0.6
OCR_COL_GAP_RATIO = 2.5
# 같은 행으로 묶였지만 간격이 표 열 수준(OCR_COL_GAP_RATIO)보다 훨씬 크면
# 표 열이 아니라 서로 무관한 캡션/라벨이 우연히 같은 y대에 걸린 것으로 보고
# 탭 대신 아예 줄바꿈으로 분리한다(예: 마케팅 이미지의 흩어진 문구들이
# 한 줄에 섞여 모델번호 등이 문장 중간에 묻히는 문제).
OCR_LINE_SPLIT_GAP_RATIO = 7.0
# 다열(multi-column) 레이아웃 분리 — 이미지 좌/우에 서로 무관한 내용(예: 왼쪽
# 상품 캡션 + 오른쪽 규격표)이 같은 y대에 걸쳐 있으면, 행 그룹핑이 y좌표만
# 보기 때문에 서로 다른 열의 텍스트가 한 줄로 섞여버린다(2026-08-23 navimro
# 상품에서 실측: 캡션 "③ SB-LWSS10"이 표의 "SB-LWSS9" 행과 한 줄로 섞임).
# 이미지 전체 폭 대비 이 비율 이상 비어 있는 세로 구간이 있으면 열 경계로
# 보고 좌/우를 먼저 나눠 각각 행 재조합한다. 자연스러운 문장 사이 공백과
# 구분하기 위한 최소 비율이며, _column_split_x()가 추가로 최소 글자폭
# 배수·상하 겹침 조건도 함께 확인한다.
OCR_COLUMN_GAP_MIN_RATIO = 0.06

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

# 검출/인식 모델을 명시적으로 고정한다 (2026-08-23 재검증).
# 과거엔 이름을 직접 지정하면 lang/ocr_version이 무시되고 캐시된 모델도
# 네트워크로 재확인하다 멈추는 문제가 있었지만(paddleocr==3.0.0 기준),
# 실제 설치된 paddleocr==3.7.0/paddlepaddle==3.3.1 환경에서 재검증한 결과
# 두 모델 모두 로컬 캐시를 즉시 사용하고 멈추지 않았다.
# 검증 결과(같은 타일 이미지 기준):
#   PP-OCRv3(기존)              : 예측 5.5초, "2.4GHZ"→"24GHZz" 오독, 공백 소실
#   PP-OCRv5 서버 검출(기본값)  : 예측 66.1초 (12배 느림, mobile 대비 과함)
#   PP-OCRv5 mobile 검출+인식    : 예측 7.6초, 오독 없음, 신뢰도 0.94~1.00
# → mobile 검출 모델은 그대로 두고 세대만 v3→v5로 올려 정확도를 개선하면서
#   속도는 거의 유지했다. get_engine()이 이 조합으로 먼저 시도하고,
#   실패하면 아래 OCR_FALLBACK_* 값으로 자동 재시도한다(안전망).
OCR_TEXT_DETECTION_MODEL_NAME = "PP-OCRv5_mobile_det"
OCR_TEXT_RECOGNITION_MODEL_NAME = "korean_PP-OCRv5_mobile_rec"

# get_engine()이 위 모델 조합으로 초기화 실패 시(모델 다운로드 불가 등)
# 재시도하는 안전망 조합 — 예전부터 검증된 lang 기반 자동 선택.
OCR_FALLBACK_OCR_VERSION = "PP-OCRv3"
