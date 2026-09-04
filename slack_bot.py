import json
import os
import sys
import threading
import traceback
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

_lock = threading.Lock()
_dm_cache: dict = {}       # user_id → DM channel_id
_extracting: set = set()   # output_dir — 중복 Extract 방지

# 봇 시작 시 Chrome 워커 풀을 미리 준비한다.
# 첫 요청 전에 모든 워커가 대기 상태가 되어 응답 지연을 최소화한다.
from crawl.crawler import QueueFullError, _submit_crawl, ensure_worker_pool_started, get_pending_count
ensure_worker_pool_started()


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _send_dm(client, user_id: str, text: str, blocks=None) -> None:
    if user_id not in _dm_cache:
        res = client.conversations_open(users=user_id)
        _dm_cache[user_id] = res["channel"]["id"]
    kwargs = {"channel": _dm_cache[user_id], "text": text, "unfurl_links": False, "unfurl_media": False}
    if blocks:
        kwargs["blocks"] = blocks
    client.chat_postMessage(**kwargs)


def _src_emoji(source: str) -> str:
    return "🔵 DOM" if source != "ocr" else "🟠 OCR"


def _legend_line(ocr_confidence) -> str:
    """DOM/OCR 범례. OCR 신뢰도는 항목 하나하나가 아니라 그 상품 이미지
    전체의 PaddleOCR 평균 인식 신뢰도라서, 개별 항목이 아니라 여기 범례에
    한 번만 붙인다."""
    ocr_label = f"🟠 *OCR {ocr_confidence}%*" if ocr_confidence is not None else "🟠 *OCR*"
    return f"🔵 *DOM* — HTML 구조·표에서 추출    {ocr_label} — 이미지 인식 (오탈자 가능성 있음)"


def _url_preview(urls: list) -> str:
    """첫 URL + (외 n개) 형식"""
    if not urls:
        return ""
    if len(urls) == 1:
        return f"• {urls[0]}"
    return f"• {urls[0]} _(외 {len(urls) - 1}개)_"



def _button_value(run_name: str, run_ocr: bool, urls: list) -> str:
    """버튼 value JSON — run_name만 저장해 경로 의존성 제거, 2000자 제한 준수"""
    payload = {"run_name": run_name, "run_ocr": run_ocr, "urls": urls}
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= 2000:
        return encoded
    trimmed = urls[:]
    while trimmed and len(encoded) > 2000:
        trimmed.pop()
        payload["urls"] = trimmed
        encoded = json.dumps(payload, ensure_ascii=False)
    return encoded


# ── App Home ──────────────────────────────────────────────────────────────────

def _home_view() -> dict:
    return {
        "type": "home",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": "🤖 URL Bot"}},
            {"type": "section", "text": {"type": "mrkdwn", "text": "상품 URL을 입력하면 크롤링 → OCR → 정보 추출까지 자동으로 진행됩니다."}},
            {"type": "divider"},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "🔍 새 작업 시작"}, "style": "primary", "action_id": "open_run_modal"}
            ]}
        ]
    }


@app.event("app_home_opened")
def handle_app_home_opened(client, event):
    client.views_publish(user_id=event["user"], view=_home_view())


# ── 실행 모달 ─────────────────────────────────────────────────────────────────

@app.action("open_run_modal")
def open_run_modal(ack, body, client):
    ack()
    client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "callback_id": "run_modal_submit",
            "title": {"type": "plain_text", "text": "URL 입력"},
            "submit": {"type": "plain_text", "text": "실행"},
            "close": {"type": "plain_text", "text": "취소"},
            "blocks": [
                {
                    "type": "input",
                    "block_id": "urls_block",
                    "label": {"type": "plain_text", "text": "상품 URL"},
                    "hint": {"type": "plain_text", "text": "한 줄에 하나씩 입력하세요"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "urls_input",
                        "multiline": True,
                        "placeholder": {"type": "plain_text", "text": "https://kr.misumi-ec.com/...\nhttps://www.festo.com/..."}
                    }
                },
                {
                    "type": "input",
                    "block_id": "ocr_block",
                    "label": {"type": "plain_text", "text": "옵션"},
                    "optional": True,
                    "element": {
                        "type": "checkboxes",
                        "action_id": "ocr_checkbox",
                        "options": [
                            {
                                "text": {"type": "mrkdwn", "text": "*OCR 포함* — 이미지 속 텍스트도 인식"},
                                "value": "ocr"
                            }
                        ]
                    }
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": "⏱ URL당 크롤링 약 30초, OCR 포함 시 추가 1~3분 소요됩니다."}
                    ]
                }
            ]
        }
    )


@app.view("run_modal_submit")
def handle_run_modal_submit(ack, body, client):
    ack()

    user_id = body["user"]["id"]
    values = body["view"]["state"]["values"]

    raw_urls = values["urls_block"]["urls_input"]["value"] or ""
    urls = [u.strip() for u in raw_urls.splitlines() if u.strip().startswith("http")]

    ocr_block = values.get("ocr_block", {}).get("ocr_checkbox", {})
    run_ocr = len(ocr_block.get("selected_options", [])) > 0

    if not urls:
        _send_dm(client, user_id, "❌ 유효한 URL이 없습니다. `https://`로 시작하는 URL을 입력해주세요.")
        return

    threading.Thread(
        target=_run_pipeline,
        args=(user_id, urls, run_ocr, client),
        daemon=True,
    ).start()


# ── 파이프라인 ────────────────────────────────────────────────────────────────

def _run_pipeline(user_id: str, urls: list, run_ocr: bool, client) -> None:
    _now = datetime.now()
    run_name = "slack_" + _now.strftime("%Y%m%d_%H%M%S") + _now.strftime("%f")
    output_dir = os.path.join(_ROOT, "crawl", "output", run_name)
    ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name) if run_ocr else None

    # 워커 풀 큐에 등록 — 가득 찼으면 즉시 사용자 알림
    pending_before = get_pending_count()
    try:
        fut = _submit_crawl(urls, output_dir)
    except QueueFullError:
        _send_dm(client, user_id,
                 "⚠️ 현재 사용 인원이 너무 많습니다. 잠시 후 다시 시도해 주세요.")
        return

    ocr_tag = " (OCR 포함)" if run_ocr else ""
    busy_notice = "\n현재 사용 인원이 많아 시간이 조금 더 걸릴 수 있습니다." if pending_before > 0 else ""
    _send_dm(
        client, user_id,
        text=f"⏳ 크롤링 진행 중입니다{ocr_tag}.{busy_notice}",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text":
            f"⏳ *크롤링 진행 중입니다{ocr_tag}.*{busy_notice}\n{_url_preview(urls)}"
        }}]
    )

    # 워커가 크롤링을 완료할 때까지 이 스레드에서 블로킹 대기 (최대 10분)
    try:
        fut.result(timeout=600)
    except Exception as e:
        traceback.print_exc()
        _send_dm(client, user_id, f"❌ 처리 중 오류 발생:\n`{e}`")
        return

    # OCR은 Chrome 불필요 — 기존과 동일하게 이 스레드에서 실행
    if run_ocr and ocr_dir:
        try:
            from ocr import paddle_ocr
            paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)
        except Exception as e:
            traceback.print_exc()
            _send_dm(client, user_id, f"❌ OCR 처리 중 오류 발생:\n`{e}`")
            return

    ocr_tag = " (OCR 포함)" if run_ocr else ""
    _send_dm(
        client, user_id,
        text=f"✅ 크롤링 완료{ocr_tag}",
        blocks=[
            {"type": "section", "text": {"type": "mrkdwn", "text":
                f"✅ *크롤링 완료{ocr_tag}*\n{_url_preview(urls)}"
            }},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "📊 상품 정보 추출"}, "style": "primary",
                 "action_id": "run_extract",
                 "value": _button_value(run_name, run_ocr, urls)}
            ]}
        ]
    )


# ── Extract ───────────────────────────────────────────────────────────────────

@app.action("run_extract")
def handle_extract(ack, body, client):
    ack()
    user_id = body["user"]["id"]

    try:
        job_data = json.loads(body["actions"][0].get("value", "{}"))
    except (json.JSONDecodeError, KeyError):
        job_data = {}

    run_name = job_data.get("run_name")
    run_ocr = job_data.get("run_ocr", False)

    if not run_name:
        _send_dm(client, user_id, "❌ 이 버튼은 만료되었습니다. 새 작업을 시작해주세요.")
        return

    output_dir = os.path.join(_ROOT, "crawl", "output", run_name)
    ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name) if run_ocr else None

    if not os.path.isdir(output_dir):
        # archive.save()가 완료 후 crawl 폴더를 삭제하므로 이미 추출된 경우 여기에 해당
        index_path = os.path.join(_ROOT, "archive", "index.json")
        already_archived = False
        try:
            if os.path.isfile(index_path):
                with open(index_path, encoding="utf-8") as _f:
                    _idx = json.load(_f)
                already_archived = any(e.get("time") in run_name for e in _idx)
        except Exception:
            pass
        if already_archived:
            _send_dm(client, user_id, "✅ 이미 추출된 결과입니다. 새 작업을 시작하거나 아카이브를 확인해주세요.")
        else:
            _send_dm(client, user_id, "❌ 크롤링 결과를 찾을 수 없습니다. 새 작업을 시작해주세요.")
        return

    with _lock:
        if output_dir in _extracting:
            return
        _extracting.add(output_dir)

    threading.Thread(
        target=_run_extract,
        args=(user_id, output_dir, ocr_dir, client, output_dir),
        daemon=True,
    ).start()


def _run_extract(user_id: str, output_dir: str, ocr_dir, client, extract_key=None) -> None:
    try:
        from extract.extractor import build_summary
        by_domain = build_summary(output_dir, ocr_dir=ocr_dir)

        records = []
        for domain_records in by_domain.values():
            records.extend(domain_records)

        if not records:
            _send_dm(client, user_id, "❌ 추출 결과가 없습니다.")
            return

        for rec in records:
            _send_dm(client, user_id, text=rec.get("상품명", "결과"), blocks=_result_blocks(rec))

    except Exception as e:
        traceback.print_exc()
        _send_dm(client, user_id, f"❌ Extract 오류:\n`{e}`")
    finally:
        if extract_key:
            with _lock:
                _extracting.discard(extract_key)


def _result_blocks(rec: dict) -> list:
    _TEXT_LIMIT = 2900

    url = rec.get("URL", "")
    product_name = rec.get("상품명") or "(상품명 미확인)"
    manufacturer = rec.get("제조원", "")
    mfr_source = rec.get("제조원_source", "")
    variants = rec.get("variants", [])
    ocr_confidence = rec.get("OCR_평균신뢰도")

    blocks = [
        {"type": "context", "elements": [{"type": "mrkdwn", "text": _legend_line(ocr_confidence)}]},
        {"type": "header", "text": {"type": "plain_text", "text": f"📌 {product_name}"[:150]}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"• {url}"}},
    ]

    body_lines = []

    if manufacturer:
        src_tag = f" {_src_emoji(mfr_source)}" if mfr_source else ""
        body_lines.append(f"*제조원*: {manufacturer}{src_tag}")

    if not variants:
        if body_lines:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(body_lines)}})
        blocks.append({"type": "divider"})
        return blocks

    if body_lines:
        body_lines.append("")

    body_lines.append(f"*모델 ({len(variants)}개)*")

    show = variants[:15]
    for v in show:
        model = v.get("model") or "(모델번호 미확인)"
        model_src = v.get("model_source", "")
        m_tag = f" {_src_emoji(model_src)}" if model_src else ""
        body_lines.append(f"- *모델번호*: {model}{m_tag}")
        for spec in v.get("규격", []):
            txt = spec.get("text", "")
            s_tag = f" {_src_emoji(spec.get('source', ''))}" if spec.get("source") else ""
            if txt:
                body_lines.append(f"- {txt}{s_tag}")
        body_lines.append("")

    if len(variants) > 15:
        body_lines.append(f"_… 외 {len(variants) - 15}개_")

    body_text = "\n".join(body_lines)
    if len(body_text) > _TEXT_LIMIT:
        body_text = body_text[:_TEXT_LIMIT] + "\n…(생략됨)"

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body_text}})
    blocks.append({"type": "divider"})
    return blocks


if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("슬랙봇 시작 (Ctrl+C로 종료)")
    handler.start()
