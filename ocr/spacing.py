from kiwipiepy import Kiwi

_kiwi = Kiwi()


def correct_spacing(text: str) -> str:
    """PaddleOCR이 붙여 읽은 한국어 텍스트의 띄어쓰기를 복원한다.
    형태소 분석 기반이라 pykospacing(TensorFlow 의존)과 달리
    numpy/pandas 바이너리 호환성 문제를 일으키지 않는다."""
    if not text.strip():
        return text
    return _kiwi.space(text)
