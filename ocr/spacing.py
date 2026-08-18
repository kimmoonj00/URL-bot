"""OCR로 얻은 한글 텍스트는 띄어쓰기가 거의 다 사라진 채로 인식되는 경우가
많다 (예: '스웨즈락튜브피팅용'). 이런 텍스트는 사람도, LLM(extract/)도 어절
경계를 파악하기 어려워 이후 정보 추출 정확도에 영향을 준다. kiwipiepy로
띄어쓰기를 복원해 가독성과 추출 정확도를 높인다.

kiwipiepy를 쓰는 이유: pykospacing은 TensorFlow를 딸려오면서 numpy를 2.x로
올려버려 paddlex(numpy==1.24.4 고정)와 충돌해 PaddleOCR을 통째로 깨뜨린다.
kiwipiepy는 순수 C++ 바인딩이라 이런 충돌이 없다.
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
