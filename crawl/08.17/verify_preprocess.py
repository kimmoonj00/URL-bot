"""
브라우저나 인터넷 연결 없이, image_preprocess.py의 전처리 로직 자체가
의도대로 동작하는지 확인하는 검증 스크립트.

실행: python verify_preprocess.py

crawler.py를 통째로 돌려서 "OCR 정확도가 실제로 좋아졌는지"는 실제
사이트 캡처 후 ocr/paddle_ocr.py 결과로만 확인할 수 있지만, "전처리
함수 자체가 의도대로 확대/축소/보정하는가"는 이 스크립트로 브라우저 없이
바로 확인할 수 있다.
"""

import io

from PIL import Image, ImageDraw

import image_preprocess


def make_png(width, height, color=(120, 100, 80)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def check(label, width, height, expect):
    original = make_png(width, height)
    processed_bytes, stats = image_preprocess.preprocess_for_ocr(original)
    result = Image.open(io.BytesIO(processed_bytes))
    ok = expect(stats, result.size)
    mark = "✅" if ok else "❌"
    print(f"{mark} {label}: {width}x{height} -> {result.size[0]}x{result.size[1]}  action={stats.get('action')}")
    return ok


def check_contrast():
    image = Image.new("RGB", (500, 500), (120, 100, 80))
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, 400, 400], fill=(140, 120, 100))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    processed_bytes, stats = image_preprocess.preprocess_for_ocr(buffer.getvalue())
    result = Image.open(io.BytesIO(processed_bytes))
    before = max(image.split()[0].getextrema()) - min(image.split()[0].getextrema())
    after = max(result.split()[0].getextrema()) - min(result.split()[0].getextrema())
    ok = after > before and stats.get("contrast_corrected") is True
    mark = "✅" if ok else "❌"
    print(f"{mark} 색감/대비 보정(저대비 이미지엔 적용): R채널 범위 {before} -> {after}")
    return ok


def check_skip_contrast_when_already_good():
    # 이미 흑백에 가까운 고대비 이미지(흰 배경 + 검은 사각형)는 채널 범위가
    # 이미 넓으므로 autocontrast를 건너뛰어야 한다(과보정/연산 낭비 방지).
    image = Image.new("RGB", (500, 500), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([100, 100, 400, 400], fill=(0, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _, stats = image_preprocess.preprocess_for_ocr(buffer.getvalue())
    ok = stats.get("contrast_corrected") is False
    mark = "✅" if ok else "❌"
    print(f"{mark} 이미 대비가 충분한 이미지는 대비 보정을 건너뜀: contrast_corrected={stats.get('contrast_corrected')}")
    return ok


def main():
    results = []
    results.append(check("작은 아이콘 확대", 120, 60, lambda s, size: size[0] > 120 and s["action"] == "upscaled"))
    results.append(check("일반 크기 유지", 900, 600, lambda s, size: size == (900, 600) and s["action"] == "none"))
    results.append(check("세로로 긴 배너 축소(다나와 실사례, 짧은 변 판독가능하게 유지)", 860, 7998,
                          lambda s, size: min(size) >= 400 and s["action"] == "downscaled"))
    results.append(check("극단적으로 긴 배너(나비엠알오 실사례, 860x11393)", 860, 11393,
                          lambda s, size: min(size) >= 400 and s["action"] == "downscaled"))
    results.append(check("가로로 얇은 배너 (상쇄 버그 없어야 함)", 1262, 90,
                          lambda s, size: size[0] > 1262 and s["action"] == "upscaled"))
    results.append(check_contrast())
    results.append(check_skip_contrast_when_already_good())

    print()
    if all(results):
        print(f"전체 {len(results)}개 항목 모두 통과 — image_preprocess.py 로직 정상 확인.")
    else:
        print(f"⚠️  {results.count(False)}개 항목 실패 — image_preprocess.py 또는 config.py 값을 확인하세요.")


if __name__ == "__main__":
    main()
