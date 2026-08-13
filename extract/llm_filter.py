import os
import re
import sys
import time
from pathlib import Path

try:
    import ollama
except ImportError:
    print("❌ ollama 패키지가 없습니다.")
    print("   설치: pip install ollama")
    print("   그리고 https://ollama.com 에서 Ollama 앱도 설치해야 합니다.")
    sys.exit(1)

# ── 설정 ─────────────────────────────────────────────────────────────────────
MODEL   = "qwen3:1.7b"
BASE    = Path(__file__).parent
OCR_DIR = BASE.parent / "ocr" / "output"
OUT_DIR = BASE / "output"

SYSTEM_PROMPT = (
    "당신은 MRO 산업 쇼핑몰 OCR 텍스트에서 상품 정보만 정확히 추출하는 어시스턴트입니다. "
    "숫자, 모델번호, 규격 수치는 절대 변경하지 않고 원문 그대로 복사합니다. "
    "출력에 설명·주석·제거 안내 등은 절대 포함하지 않습니다."
)


# ── 프롬프트 생성 ─────────────────────────────────────────────────────────────
def build_prompt(ocr_text: str) -> str:
    return f"""아래는 MRO 산업 쇼핑몰 페이지를 OCR로 추출한 텍스트입니다.
다음 형식에 맞춰 메인 상품 정보만 추출해주세요.

[출력 형식 - 반드시 이 형식만 사용]
상품명: ___
브랜드: ___
모델번호/형번: ___
규격:
  - [속성명]: [값]
  - [속성명]: [값]
제품 설명: ___

[규칙]
- 규격 항목은 원문에 있는 기술 사양(치수, 재질, 전압, 전류, 압력, 용량 등)을 모두 나열
- 페이지에 서로 다른 독립 상품이 여러 개인 경우에만 위 형식을 상품별로 반복
- 동일 상품의 크기·재질 변형(variant)은 하나로 묶어 규격 내에서 구분
- 사이드바·연관상품·추천상품은 별도 상품으로 취급하지 않음
- 원문에 없는 항목은 해당 줄 자체를 생략 ("없음" 기재 금지)
- 숫자·모델번호·규격 수치는 원문 그대로 복사. 절대 바꾸거나 추가하지 말 것
- 원문에 없는 내용을 유추하거나 지어내지 말 것

[무시할 내용]
- 가격, 재고, 출하일, 배송비
- 네비게이션, 검색창, 로그인/회원가입 버튼
- 배송 안내, 반품·교환 안내, 환불 정책
- 광고, 이벤트, 리뷰, 평점, 법적 고지, 푸터
- UI 텍스트 ("모두 삭제", "Add to cart", "Log in to see price", "Pieces" 등)

--- 입력 시작 ---
{ocr_text}
--- 입력 끝 ---

추출 결과:"""


# ── Qwen3 <think> 태그 제거 ───────────────────────────────────────────────────
def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


# ── Ollama 연결 확인 ──────────────────────────────────────────────────────────
def check_ollama():
    try:
        models = [m.model for m in ollama.list().models]
        if not any(MODEL in m for m in models):
            print(f"⚠️  '{MODEL}' 모델이 없습니다.")
            print(f"   설치: ollama pull {MODEL}")
            sys.exit(1)
    except Exception:
        print("❌ Ollama에 연결할 수 없습니다.")
        print("   Ollama 앱이 실행 중인지 확인하세요: https://ollama.com")
        sys.exit(1)


# ── LLM 필터링 실행 ───────────────────────────────────────────────────────────
def run_filter(txt_path: Path) -> str:
    ocr_text = txt_path.read_text(encoding="utf-8")
    print(f"  📄 입력: {len(ocr_text.splitlines())}줄", end="  ", flush=True)

    t = time.time()
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": build_prompt(ocr_text)},
        ],
        options={"temperature": 0.0, "num_predict": 3000},
    )
    elapsed = time.time() - t

    result = strip_thinking(response["message"]["content"])
    print(f"→ 출력: {len(result.splitlines())}줄  ⏱️  {elapsed:.1f}초")
    return result


# ── 결과 저장 ─────────────────────────────────────────────────────────────────
def save_result(txt_path: Path, result: str) -> Path:
    relative = txt_path.relative_to(OCR_DIR)
    out_path = OUT_DIR / Path(*relative.parts[1:])  # 엔진명 폴더(paddle_ocr 등) 제거
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counter = 1
    final = out_path
    while final.exists():
        final = out_path.with_stem(f"{out_path.stem} ({counter})")
        counter += 1
    final.write_text(result, encoding="utf-8")
    return final


# ── OCR 파일 목록 수집 ────────────────────────────────────────────────────────
def find_ocr_files() -> list[Path]:
    if not OCR_DIR.exists():
        return []
    return sorted(OCR_DIR.rglob("*.txt"))


# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    print("=" * 55)
    print("  LLM 노이즈 필터 (Ollama + Qwen3)")
    print("=" * 55)

    check_ollama()

    files = find_ocr_files()
    if not files:
        print(f"\n❌ OCR 파일이 없습니다: {OCR_DIR}")
        print("   ocr/paddle_ocr.py 또는 ocr/google_ocr.py 를 먼저 실행하세요.")
        return

    print(f"\n📂 {len(files)}개 파일 처리 시작\n")

    total_start = time.time()
    for i, f in enumerate(files, 1):
        site = f.stem
        print(f"\n[{i}/{len(files)}] [{site}]")
        t = time.time()
        result = run_filter(f)
        out = save_result(f, result)
        elapsed = time.time() - t
        print(f"  💾 저장 → {out.relative_to(OUT_DIR.parent)}")
        print(f"  소요 시간: {elapsed:.1f}초")

    total_elapsed = time.time() - total_start
    print(f"\n🎉 완료  ⏱️  전체 {total_elapsed:.1f}초")
    print(f"📁 결과 위치: {OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
