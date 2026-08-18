import os

_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(_DIR), "crawl", "output")  # crawl 결과물 위치

# 표/텍스트에서 "라벨: 값" 쌍을 찾을 때 규격 후보로 채택할 키워드
SPEC_LABEL_KEYWORDS = {
    "model": ["모델명", "모델번호", "모델", "형번", "품번", "제품번호", "제품코드",
              "model name", "model no", "model number", "model", "type", "type no",
              "part no", "part number", "p/n", "sku", "ordering code", "mlfb", "품목번호"],
    "규격": ["사이즈", "규격", "치수", "크기", "사양", "스펙", "제품사양",
             "size", "dimension", "dimensions", "specification", "spec"],
}

# 라벨 없이도 모델번호로 볼 수 있는 값 패턴
SPEC_VALUE_PATTERNS = [
    r"\b[A-Z]{1,6}[-/][A-Z0-9]{1,10}(?:[-/][A-Z0-9]{1,10})*\b",  # 예: T-8M3-1, DSBC-32
    r"\b\d{2,4}-\d{2,6}\b",  # 예: 500-033260
]

# "qwen": Ollama/Qwen LLM 추출 (정확도 높음, Ollama 필요)
# "rules": 정규식/키워드 규칙 기반 추출 (오프라인)
# Qwen 호출 실패 시 자동으로 rules로 폴백한다.
EXTRACTION_ENGINE = "qwen"

OLLAMA_BASE_URL = "http://localhost:11434"
# ollama list로 실제 받아둔 모델 태그를 확인하고 이름이 다르면 맞춰서 바꿀 것.
OLLAMA_MODEL = "qwen3:4b"
OLLAMA_TIMEOUT_SECONDS = 600
# 호출 사이에 모델을 메모리에 얼마나 유지할지.
OLLAMA_KEEP_ALIVE = "5m"
# 응답 최대 토큰 수.
OLLAMA_NUM_PREDICT = 800
# 프롬프트에 넣는 각 텍스트 소스의 최대 길이.
OLLAMA_MAX_SOURCE_CHARS = 4000
