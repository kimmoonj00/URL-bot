"""
OCR로 넘어갈 이미지를 저장하기 전에 다듬어서 인식률을 높이는 전처리 모듈.

역할 분담상 Playwright(크롤링) 쪽 책임이라 main.py가 스크린샷을 찍은
직후, 디스크에 쓰기 전에 이 모듈을 거친다. Paddle OCR 쪽은 이미
다듬어진 이미지를 받는다.

무거운 이미지 처리 라이브러리(OpenCV 등)를 새로 추가하지 않고, 이미
프로젝트가 쓰고 있는 Pillow만으로 처리해 의존성을 늘리지 않았다.

3단계로 처리한다:
  1) 화질 개선 — 너무 작게 렌더링된 이미지(아이콘/뱃지류)는 글자가 뭉개져
     OCR이 잘 못 읽으므로 확대한다.
  2) 색감/대비 보정 — 채널별 히스토그램을 펴서 저대비이거나 색이 한쪽으로
     치우친 이미지를 보정한다.
  3) 샤프닝 — 글자 경계를 또렷하게 만든다.

모든 임계값/강도는 config.py에서 조절한다. 여기엔 숫자를 직접 박아두지
않는다(하드코딩 없음).
"""

import io

from PIL import Image, ImageFilter, ImageOps

import config


def preprocess_for_ocr(image_bytes):
    """스크린샷 PNG 바이트를 받아 OCR이 더 잘 읽도록 다듬은 PNG 바이트를 반환한다.
    config.OCR_PREPROCESS_ENABLED가 False면 원본을 그대로 반환한다(전처리가
    맞지 않는 이미지가 있을 수 있으니 언제든 한 줄로 끌 수 있게 했다)."""
    if not config.OCR_PREPROCESS_ENABLED:
        return image_bytes

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        # 손상되었거나 Pillow가 못 여는 이미지는 원본 그대로 넘긴다.
        return image_bytes

    image = _upscale_if_small(image)
    image = _correct_contrast_and_color(image)
    image = _sharpen(image)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upscale_if_small(image):
    """짧은 변이 기준치보다 작은 이미지만 확대한다. 이미 충분히 큰
    이미지는 손대지 않는다(불필요한 리샘플링으로 화질을 해치지 않기 위함).
    과도한 확대는 오히려 뭉개지므로 배율 상한을 둔다."""
    short_side = min(image.width, image.height)
    if short_side <= 0 or short_side >= config.OCR_PREPROCESS_MIN_DIMENSION:
        return image

    scale = min(
        config.OCR_PREPROCESS_MIN_DIMENSION / short_side,
        config.OCR_PREPROCESS_MAX_UPSCALE_FACTOR,
    )
    if scale <= 1:
        return image

    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, Image.LANCZOS)


def _correct_contrast_and_color(image):
    """자동 대비/색보정. RGB 채널을 각각 펴기 때문에(preserve_tone=False)
    대비 개선과 색편중(예: 노란빛이 도는 스캔 이미지) 보정을 동시에 한다."""
    try:
        return ImageOps.autocontrast(image, cutoff=config.OCR_PREPROCESS_AUTOCONTRAST_CUTOFF)
    except Exception:
        # 단색 이미지 등 일부 극단적인 경우 autocontrast가 실패할 수 있어 원본 유지.
        return image


def _sharpen(image):
    """언샤프 마스크로 글자 경계를 또렷하게 만든다."""
    return image.filter(
        ImageFilter.UnsharpMask(
            radius=config.OCR_PREPROCESS_SHARPEN_RADIUS,
            percent=config.OCR_PREPROCESS_SHARPEN_PERCENT,
            threshold=config.OCR_PREPROCESS_SHARPEN_THRESHOLD,
        )
    )
