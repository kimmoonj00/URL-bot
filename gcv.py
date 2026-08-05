import os
import time
from google.cloud import vision

IMAGE_DIR = "output"
TEXT_DIR = "text"
REQUEST_DELAY = 2  # 이미지 간 대기(초)

# Google Cloud Console에서 발급한 서비스 계정 JSON 파일 경로
CREDENTIALS_PATH = "google_credentials.json"


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


def get_client():
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH
    return vision.ImageAnnotatorClient()


def ocr_request(client, image_path):
    with open(image_path, "rb") as f:
        content = f.read()
    image = vision.Image(content=content)
    return client.document_text_detection(image=image)


def run_ocr(client, image_path):
    print(f"\n  파일: {image_path}")
    start_time = time.time()

    try:
        response = ocr_request(client, image_path)
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"  ❌ 연결 실패: {e}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return

    if response.error.message:
        elapsed = time.time() - start_time
        print(f"  ❌ API 오류: {response.error.message}")
        print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
        return

    all_text = response.full_text_annotation.text.strip()

    text_path = image_path_to_text_path(image_path)
    os.makedirs(os.path.dirname(text_path), exist_ok=True)
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(all_text)

    elapsed = time.time() - start_time
    print(f"  ✅ OCR 성공! → {text_path}")
    print(f"  ⏱️  소요 시간: {elapsed:.1f}초")
    print(f"  미리보기: {all_text[:150].strip()}")


def run_ocr_all():
    print("=" * 50)
    print("Google Cloud Vision OCR")
    print("=" * 50)

    images = find_captured_images()
    if not images:
        print(f"❌ '{IMAGE_DIR}' 폴더에 이미지가 없습니다. main.py를 먼저 실행하세요.")
        return

    client = get_client()
    print(f"총 {len(images)}개 이미지 발견\n")

    for i, img in enumerate(images):
        run_ocr(client, img)
        if i < len(images) - 1:
            time.sleep(REQUEST_DELAY)

    print(f"\n📄 텍스트 저장 위치: {os.path.abspath(TEXT_DIR)}")


if __name__ == "__main__":
    run_ocr_all()
