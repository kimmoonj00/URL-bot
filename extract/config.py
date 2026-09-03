import os

_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGE_DIR = os.path.join(os.path.dirname(_DIR), "crawl", "output")

SPEC_LABEL_KEYWORDS = {
    "model": ["모델명", "모델번호", "모델", "형번", "품번", "제품번호", "제품코드",
              "model name", "model no", "model number", "model", "type", "type no",
              "part no", "part number", "p/n", "sku", "ordering code", "mlfb", "품목번호"],
    "manufacturer": ["제조원", "제조사", "제조업체", "생산자", "브랜드", "브랜드명", "메이커", "만든곳", "제조",
                     "manufacturer", "made by", "maker", "brand", "brand name"],
    "규격": ["사이즈", "규격", "치수", "크기", "사양", "스펙", "제품사양",
             "size", "dimension", "dimensions", "specification", "spec"],
}

SPEC_VALUE_PATTERNS = [
    r"\b[A-Z]{1,6}[-/][A-Z0-9]{1,10}(?:[-/][A-Z0-9]{1,10})*\b",
    r"\b\d{2,4}-\d{2,6}\b",
]

# "gpt":   OpenAI GPT-4o-mini (기본값)
# "rules": 정규식/키워드 규칙 기반 (GPT 오류·빈 응답 시 자동 폴백)
EXTRACTION_ENGINE = "gpt"

# ── OpenAI ────────────────────────────────────────────────────────────────────
# 프로젝트 루트의 .env 파일에 OPENAI_API_KEY=sk-... 를 넣어두면 자동으로 읽힙니다.
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL = "gpt-4o-mini"
OPENAI_MAX_TOKENS = 6000
OPENAI_MAX_SOURCE_CHARS = 20000
