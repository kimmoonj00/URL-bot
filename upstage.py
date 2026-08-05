import os
import time
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

API_KEY = "" # 발급 받은 API Key 등록
IMAGE_DIR = "output"
TEXT_DIR = "text"
REQUEST_DELAY = 2  # 이미지 간 대기(초) - 회사 프록시 연속 차단 방지


def find_captured_images():
    images = []
    for root, _, files in os.walk(IMAGE_DIR):
        for f in files:
            if f.endswith(".png"):
                images.append(os.path.join(root, f))
    return sorted(images)


def image_path_to_text_path(image_path):
    """output/세션폴더/파일.png → text/세션폴더/파일.txt"""
    relative = os.path.relpath(image_path, IMAGE_DIR)
    text_path = os.path.join(TEXT_DIR, os.path.splitext(relative)[0] + ".txt")
    return text_path


def ocr_request(image_path):
    """OCR API 요청"""
    with open(image_path, "rb") as f:
        return requests.post(
            "https://api.upstage.ai/v1/document-ai/ocr",
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"document": f},
            verify=False
        )


def test_ocr(image_path):
    """단일 이미지에 OCR 실행 후 text 폴더에 저장"""
    print(f"\n  파일: {image_path}")
    start_time = time.time()

    try:
        response = ocr_request(image_path)
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ❌ 연결 실패: {e}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return

    if response.status_code != 200:
        elapsed = time.time() - start_time
        print(f"  ❌ 실패 (status {response.status_code}): {response.text}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return

    result = response.json()
    pages = result.get("pages", [])
    all_text = ""
    for page in pages:
        # API 응답 구조에 따라 page.text (전체) 또는 words[].text (단어별) 중 하나가 존재
        if page.get("text"):
            all_text += page["text"] + "\n"
        else:
            for word in page.get("words", []):
                all_text += word.get("text", "") + " "
    all_text = all_text.strip()

    text_path = image_path_to_text_path(image_path)
    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(all_text)

    elapsed = time.time() - start_time
    print(f"  ✅ OCR 성공! → {text_path}")
    print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
    print(f"  미리보기: {all_text[:150].strip()}")


def test_ocr_all():
    """output 폴더의 모든 캡처 이미지에 OCR 실행"""
    print("=" * 50)
    print("Upstage Document OCR")
    print("=" * 50)

    images = find_captured_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. main.py를 먼저 실행하세요.")
        return

    print(f"총 {len(images)}개 이미지 발견\n")
    for i, img in enumerate(images):
        test_ocr(img)
        # 마지막 이미지가 아니면 다음 요청 전 대기
        if i < len(images) - 1:
            time.sleep(REQUEST_DELAY)

    print(f"\n📄 텍스트 저장 위치: {os.path.abspath(TEXT_DIR)}")


if __name__ == "__main__":
    test_ocr_all()
