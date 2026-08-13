"""OCR로 얻은 한글 텍스트는 띄어쓰기가 거의 다 사라진 채로 인식되는 경우가
많다 (예: '스웨즈락튜브피팅용'). 이런 텍스트는 사람도, LLM도 어절 경계를
파악하기 어려워 이후 정보 추출 정확도에 영향을 준다. kiwipiepy로 띄어쓰기를
복원해 가독성과 LLM 추출 정확도를 높인다.
"""
from __future__ import annotations

from kiwipiepy import Kiwi

_kiwi = Kiwi()


def correct_spacing(text: str) -> str:
    """붙어있는 한글 텍스트에 띄어쓰기를 복원한다.

    모델 코드/숫자/짧은 라벨처럼 띄어쓰기가 필요 없는 텍스트는 그대로
    유지되고, 긴 한글 문장 위주로 교정된다.
    """
    if not text:
        return text
    return _kiwi.space(text)
