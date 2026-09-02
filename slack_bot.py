import asyncio
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
_extracting: set = set()   # (channel, message_ts) — 중복 Extract 방지


# ── 헬퍼 ──────────────────────────────────────────────────────────────────────

def _send_dm(client, user_id: str, text: str, blocks=None) -> None:
    if user_id not in _dm_cache:
        res = client.conversations_open(users=user_id)
        _dm_cache[user_id] = res["channel"]["id"]
    kwargs = {"channel": _dm_cache[user_id], "text": text}
    if blocks:
        kwargs["blocks"] = blocks
    client.chat_postMessage(**kwargs)


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
    try:
        from crawl.crawler import _run_capture_bot_async
        from ocr import paddle_ocr

        run_name = "slack_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(_ROOT, "crawl", "output", run_name)
        ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name) if run_ocr else None

        # 스레드마다 새 이벤트 루프 생성 — Bolt의 루프와 충돌 방지
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_capture_bot_async(
                run_ocr_and_extract=False, urls=urls, output_dir=output_dir
            ))
        finally:
            loop.close()

        if run_ocr and ocr_dir:
            paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)

        ocr_tag = " (OCR 포함)" if run_ocr else ""
        url_list = "\n".join(f"• {u}" for u in urls)
        _send_dm(
            client, user_id,
            text=f"✅ 크롤링 완료{ocr_tag}",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": f"✅ *크롤링 완료{ocr_tag}*\n{url_list}"}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "📊 Extract 실행"}, "style": "primary",
                     "action_id": "run_extract",
                     "value": json.dumps({"output_dir": output_dir, "ocr_dir": ocr_dir})}
                ]}
            ]
        )

    except Exception as e:
        traceback.print_exc()
        _send_dm(client, user_id, f"❌ 처리 중 오류 발생:\n`{e}`")


# ── Extract ───────────────────────────────────────────────────────────────────

@app.action("run_extract")
def handle_extract(ack, body, client):
    ack()
    user_id = body["user"]["id"]

    try:
        job_data = json.loads(body["actions"][0].get("value", "{}"))
    except (json.JSONDecodeError, KeyError):
        job_data = {}

    output_dir = job_data.get("output_dir")
    ocr_dir = job_data.get("ocr_dir")

    if not output_dir:
        _send_dm(client, user_id, "❌ 크롤링 결과를 찾을 수 없습니다. 새 작업을 시작해주세요.")
        return

    channel = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]
    extract_key = (channel, message_ts)

    with _lock:
        if extract_key in _extracting:
            return
        _extracting.add(extract_key)

    try:
        client.chat_update(
            channel=channel,
            ts=message_ts,
            text="⏳ Extract 실행 중...",
            blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "⏳ *Extract 실행 중입니다...*"}}]
        )
        threading.Thread(
            target=_run_extract,
            args=(user_id, output_dir, ocr_dir, client, extract_key),
            daemon=True,
        ).start()
    except Exception:
        with _lock:
            _extracting.discard(extract_key)
        raise


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

    # 헤더: 상품명 + 제조원 합산 150자 이내
    src_tag = f" ({mfr_source.upper()})" if mfr_source else ""
    mfr_part = f"  |  {manufacturer}{src_tag}" if manufacturer else ""
    header_text = (product_name + mfr_part)[:150]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"🔗 {url}"}},
    ]

    if not variants:
        return blocks

    show = variants[:15]

    # 규격 키 목록 수집 (순서 유지)
    spec_keys: list = []
    for v in show:
        for spec in v.get("규격", []):
            txt = spec.get("text", "")
            if ":" in txt:
                key = txt.split(":", 1)[0].strip()
                if key not in spec_keys:
                    spec_keys.append(key)

    if spec_keys:
        col_w = max(len(k) for k in spec_keys) + 2
        model_w = max((len(v.get("model", "")) for v in show), default=10) + 2
        header_row = f"{'모델번호':<{model_w}}" + "".join(f"{k:<{col_w}}" for k in spec_keys)
        sep = "-" * len(header_row)
        rows = [header_row, sep]
        for v in show:
            model = v.get("model", "")
            spec_map = {}
            for spec in v.get("규격", []):
                txt = spec.get("text", "")
                if ":" in txt:
                    k, val = txt.split(":", 1)
                    spec_map[k.strip()] = val.strip()
            rows.append(f"{model:<{model_w}}" + "".join(f"{spec_map.get(k, '-'):<{col_w}}" for k in spec_keys))

        table_text = "```\n" + "\n".join(rows) + "\n```"
    else:
        lines = [f"• `{v.get('model', '')}`" for v in show]
        table_text = "\n".join(lines)

    suffix = f"\n_… 외 {len(variants) - 15}개_" if len(variants) > 15 else ""
    body_text = f"*모델 {len(variants)}개*\n{table_text}{suffix}"

    # 3000자 제한 초과 시 잘라내기
    if len(body_text) > _TEXT_LIMIT:
        body_text = body_text[:_TEXT_LIMIT] + "\n…(생략됨)"

    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body_text}})
    return blocks


if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("슬랙봇 시작 (Ctrl+C로 종료)")
    handler.start()
