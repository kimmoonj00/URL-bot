"""
브라우저나 인터넷 연결 없이, text_filter.py의 일본어/한자 필터링 로직이
의도대로 동작하는지 확인하는 검증 스크립트.

실행: python verify_text_filter.py
"""

import text_filter


def check(label, text, condition):
    result = text_filter.clean_unwanted_scripts(text)
    ok = condition(result)
    mark = "✅" if ok else "❌"
    print(f"{mark} {label}")
    print(f"    입력: {text!r}")
    print(f"    출력: {result!r}")
    return ok


def main():
    results = []

    results.append(check(
        "한글/영문/숫자만 있는 정상 텍스트는 그대로 유지",
        "육각 볼트 SUS304 M10x30\n모델번호: HXNSMH-SUS-M10-30",
        lambda r: r == "육각 볼트 SUS304 M10x30\n모델번호: HXNSMH-SUS-M10-30",
    ))
    results.append(check(
        "순수 일본어/중국어 줄은 통째로 삭제",
        "한국어\n日本語\n中文\nEnglish",
        lambda r: "日本語" not in r and "中文" not in r and "한국어" in r and "English" in r,
    ))
    results.append(check(
        "일부만 일본어가 섞인 줄은 유효 정보(한글/숫자)는 보존",
        "규격 32mm ネジ穴付き",
        lambda r: "규격" in r and "32mm" in r and "ネジ" not in r,
    ))
    results.append(check(
        "일본어 라벨 + 전각기호도 제거되고 값은 남음",
        "型番：DSBC-32-25-PPVA-N3　サイズ：32mm",
        lambda r: "型番" not in r and "サイズ" not in r and "：" not in r
        and "DSBC-32-25-PPVA-N3" in r and "32mm" in r,
    ))
    results.append(check(
        "순수 영어 모델번호는 원본 그대로",
        "Model: DSBC-32-25-PPVA-N3\nSize: 32 mm",
        lambda r: r == "Model: DSBC-32-25-PPVA-N3\nSize: 32 mm",
    ))
    results.append(check(
        "표 셀 정리(clean_table_cells)도 동작",
        None,
        lambda r: True,
    ) if False else None)

    table_cell_ok = True
    tables = [{"table_index": 1, "rows": [[{"text": "サイズ"}, {"text": "32mm"}]]}]
    cleaned = text_filter.clean_table_cells(tables)
    if cleaned[0]["rows"][0][0]["text"] != "" or cleaned[0]["rows"][0][1]["text"] != "32mm":
        table_cell_ok = False
    mark = "✅" if table_cell_ok else "❌"
    print(f"{mark} 표 셀 정리(clean_table_cells)도 동일하게 동작")
    results.append(table_cell_ok)

    results = [r for r in results if r is not None]
    print()
    if all(results):
        print(f"전체 {len(results)}개 항목 모두 통과 — text_filter.py 로직 정상 확인.")
    else:
        print(f"⚠️  {results.count(False)}개 항목 실패.")


if __name__ == "__main__":
    main()
