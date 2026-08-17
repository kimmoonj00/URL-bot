"""
OCR로 넘어갈 이미지를 저장하기 전에 다듬어서 인식률을 높이는 전처리 모듈.

crawler.py가 스크린샷을 찍은 직후, 디스크에 쓰기 전에 이 모듈을 거친다.
Pillow만 사용해 의존성을 늘리지 않았다.

4단계로 처리한다:
  1) 화질 개선 — 너무 작은 이미지(아이콘/뱃지류)는 확대.
  2) 크기 상한 — 반대로 지나치게 큰 이미지(세로로 긴 상세페이지 배너 등)는 축소.
  3) 색감/대비 보정 — 채널별 히스토그램을 펴서 저대비/색편중 보정.
  4) 샤프닝 — 글자 경계를 또렷하게.

모든 임계값은 config.py에서 조절한다(하드코딩 없음).

preprocess_for_ocr()는 처리된 이미지 바이트와 함께 "무슨 처리를 했는지"
통계 딕셔너리를 반환한다. 이 통계를 호출한 쪽(crawler.py)이 metadata.json/
assets.json에 그대로 기록해두면, 실제로 캡처를 돌렸을 때 전처리가 각
이미지에 어떻게 적용됐는지 파일만 열어봐도 바로 확인할 수 있다 —
"실행해봐야 알 수 있다"는 문제를 없애기 위한 장치다.
"""

import io

from PIL import Image, ImageFilter, ImageOps

import config


def preprocess_for_ocr(image_bytes):
    """스크린샷 PNG 바이트를 받아 (처리된 PNG 바이트, 통계 dict)를 반환한다.
    config.OCR_PREPROCESS_ENABLED가 False면 원본을 그대로 반환한다."""
    if not config.OCR_PREPROCESS_ENABLED:
        return image_bytes, {"applied": False, "reason": "OCR_PREPROCESS_ENABLED=False"}

    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as error:
        return image_bytes, {"applied": False, "reason": f"이미지를 열지 못함: {error}"}

    original_size = image.size
    short_side = min(image.width, image.height) if image.width and image.height else 0

    if 0 < short_side < config.OCR_PREPROCESS_MIN_DIMENSION:
        image, action = _upscale_if_small(image)
    else:
        image, action = _downscale_if_huge(image)

    image, contrast_applied = _correct_contrast_and_color(image)
    image = _sharpen(image)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", compress_level=config.OCR_PREPROCESS_PNG_COMPRESS_LEVEL)
    stats = {
        "applied": True,
        "action": action,
        "contrast_corrected": contrast_applied,
        "original_size": list(original_size),
        "processed_size": list(image.size),
    }
    return buffer.getvalue(), stats


def _upscale_if_small(image):
    short_side = min(image.width, image.height)
    if short_side <= 0 or short_side >= config.OCR_PREPROCESS_MIN_DIMENSION:
        return image, "none"

    scale = min(
        config.OCR_PREPROCESS_MIN_DIMENSION / short_side,
        config.OCR_PREPROCESS_MAX_UPSCALE_FACTOR,
    )
    if scale <= 1:
        return image, "none"

    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, Image.LANCZOS), "upscaled"


def _downscale_if_huge(image):
    """긴 변을 OCR_PREPROCESS_MAX_DIMENSION에 맞추기만 하면, 세로로 아주 긴
    이미지(예: 쇼핑몰 상세페이지 통짜 배너 860x11393)의 짧은 변이 몇백 px로
    눌려버려 글자를 못 읽게 된다(실제 캡처에서 860x11393 -> 226x3000으로
    찌그러진 사례 확인). 짧은 변이 OCR_PREPROCESS_MIN_DIMENSION 밑으로는
    안 내려가게 하한을 같이 적용한다 — 그 결과 긴 변이 MAX_DIMENSION을
    넘을 수 있지만(원본보다는 여전히 훨씬 작음), 판독 가능한 폭을 지키는
    쪽이 OCR 정확도에 더 중요하다."""
    long_side = max(image.width, image.height)
    short_side = min(image.width, image.height)
    if long_side <= config.OCR_PREPROCESS_MAX_DIMENSION:
        return image, "none"

    scale = config.OCR_PREPROCESS_MAX_DIMENSION / long_side
    if short_side > 0:
        legible_scale = config.OCR_PREPROCESS_MIN_DIMENSION / short_side
        scale = min(max(scale, legible_scale), 1.0)
    new_size = (round(image.width * scale), round(image.height * scale))
    return image.resize(new_size, Image.LANCZOS), "downscaled"


def _correct_contrast_and_color(image):
    """이미 대비가 충분한 스크린샷(예: 흰 배경의 스펙표)까지 autocontrast를
    걸면 과보정으로 색이 뜨거나 글자 경계가 뭉개질 수 있고, 연산 시간도
    아깝다. 채널별 명암 범위가 이미 충분히 넓으면(=이미 잘 나온 이미지)
    건너뛴다."""
    try:
        if _has_sufficient_contrast(image):
            return image, False
        return ImageOps.autocontrast(image, cutoff=config.OCR_PREPROCESS_AUTOCONTRAST_CUTOFF), True
    except Exception:
        return image, False


def _has_sufficient_contrast(image):
    threshold = config.OCR_PREPROCESS_SKIP_CONTRAST_IF_RANGE_GTE
    for channel in image.split():
        low, high = channel.getextrema()
        if high - low < threshold:
            return False
    return True


def _sharpen(image):
    return image.filter(
        ImageFilter.UnsharpMask(
            radius=config.OCR_PREPROCESS_SHARPEN_RADIUS,
            percent=config.OCR_PREPROCESS_SHARPEN_PERCENT,
            threshold=config.OCR_PREPROCESS_SHARPEN_THRESHOLD,
        )
    )
