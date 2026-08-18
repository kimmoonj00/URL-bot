"""
캡처된 텍스트(DOM/표)에서 상품정보 추출에 불필요한 문자를 걸러내는 모듈.

상품명/모델번호/사이즈/사양은 결국 한글·영문·숫자(+기호)로 이뤄지므로,
페이지에 섞여 들어오는 일본어(히라가나/가타카나)나 한자는 이후 추출
단계(규칙 기반/LLM)에 잡음만 더한다. 다국어 사이트(Festo/Siemens 같은
글로벌 기업)의 언어 선택 메뉴("日本語 / 中文 / 한국어")나 다국어 병기
텍스트가 대표적인 예다.

중요한 제약: 유니코드에서 한자(CJK 통합 한자, U+4E00~U+9FFF)는 중국어/
일본어/한국어 한자 표기가 코드값을 공유한다. 즉 "중국어 한자만" 골라내는
방법은 없고, 한자 전체를 걸러낸다. 그 결과 한국 문서에 드물게 병기되는
한자(회사명 한자 표기 등)까지 같이 제거될 수 있다 — 상품정보에는 한자가
쓰이는 경우가 거의 없으므로 실용적으로 감수 가능한 트레이드오프다.

두 단계로 걸러낸다:
  1) 줄(line) 단위: 대상 문자 비율이 높은 줄은 통째로 버린다
     (언어선택 메뉴처럼 그 줄 자체가 불필요한 경우).
  2) 문자 단위: 남은 줄에서도 개별 문자만 제거한다
     (예: 나머지는 정상 텍스트인데 문자 하나가 섞여 들어온 경우).

모든 임계값은 config.py에서 조절한다(하드코딩 없음).
"""

import re

import config

# 히라가나, 가타카나(+음성확장, 반각), CJK 통합 한자(+확장A), 일본식 괄호기호.
# 한글(가-힣, 자모)과 영문·숫자·일반 기호는 여기 포함되지 않는다 — 안 건드림.
DISALLOWED_SCRIPT_PATTERN = re.compile(
    "["
    "\u3040-\u309f"  # 히라가나
    "\u30a0-\u30ff"  # 가타카나
    "\u31f0-\u31ff"  # 가타카나 음성 확장
    "\uff66-\uff9f"  # 반각 가타카나
    "\u4e00-\u9fff"  # CJK 통합 한자
    "\u3400-\u4dbf"  # CJK 통합 한자 확장 A
    "\u3010\u3011"   # 【 】
    "\u300c\u300d\u300e\u300f"  # 「 」 『 』
    "\u3008\u3009\u300a\u300b"  # 〈 〉 《 》
    "\uff1a\uff0c\uff0e\uff08\uff09\uff01\uff1f"  # 전각 ： ， 。 （ ） ！ ？
    "]"
)

_MULTI_SPACE_PATTERN = re.compile(r"[ \t]{2,}")


def clean_unwanted_scripts(text):
    """일본어/한자 등 상품정보에 불필요한 문자를 제거한 텍스트를 반환한다.
    config.FILTER_NON_KOREAN_SCRIPTS가 False면 원본을 그대로 반환한다."""
    if not config.FILTER_NON_KOREAN_SCRIPTS or not text:
        return text

    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue

        meaningful_chars = [c for c in stripped if not c.isspace()]
        disallowed_count = sum(1 for c in meaningful_chars if DISALLOWED_SCRIPT_PATTERN.match(c))

        if meaningful_chars and disallowed_count / len(meaningful_chars) >= config.FILTER_LINE_DROP_RATIO:
            # 줄 전체가 대상 문자 위주 -> 언어선택 메뉴 등으로 보고 줄째 버림
            continue

        new_line = DISALLOWED_SCRIPT_PATTERN.sub("", line)
        # 전각 공백(U+3000) 등 CJK 계열 공백도 일반 공백으로 정규화한다
        # (라벨을 지우고 나면 이런 공백만 덩그러니 남는 경우가 있다).
        new_line = "".join(" " if c.isspace() and c not in ("\n", "\t") else c for c in new_line)
        new_line = _MULTI_SPACE_PATTERN.sub(" ", new_line)
        cleaned_lines.append(new_line)

    return "\n".join(cleaned_lines)


def clean_table_cells(tables):
    """extract_tables()가 반환한 표 구조의 각 셀 text를 제자리에서 정리한다."""
    if not config.FILTER_NON_KOREAN_SCRIPTS:
        return tables
    for table in tables:
        for row in table.get("rows", []):
            for cell in row:
                cell["text"] = clean_unwanted_scripts(cell.get("text", ""))
    return tables
