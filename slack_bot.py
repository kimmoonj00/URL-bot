import os
import sys
import threading
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# user_id → job 상태 저장
user_jobs: dict = {}


# ── App Home ──────────────────────────────────────────────────────────────────

def _home_view(user_id: str) -> dict:
    job = user_jobs.get(user_id, {})
    status = job.get("status", "idle")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🤖 URL Bot"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "상품 URL을 입력하면 크롤링 → OCR → 정보 추출까지 자동으로 진행됩니다."}},
        {"type": "divider"},
    ]

    if status == "running":
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "⏳ *처리 중입니다...*\n완료되면 DM으로 알려드릴게요."}
        })
    elif status == "error":
        blocks += [
            {"type": "section", "text": {"type": "mrkdwn", "text": "❌ *오류가 발생했습니다.* DM을 확인하세요."}},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "🔍 다시 시작"}, "style": "primary", "action_id": "open_run_modal"}
            ]}
        ]
    else:
        if status == "done":
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "✅ *크롤링 완료!* DM에서 Extract를 실행하세요."}
            })
            blocks.append({"type": "divider"})

        blocks.append({
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "🔍 새 작업 시작"}, "style": "primary", "action_id": "open_run_modal"}
            ]
        })

    return {"type": "home", "blocks": blocks}


@app.event("app_home_opened")
def handle_app_home_opened(client, event):
    user_id = event["user"]
    # 봇 재시작 후 "처리 중" 상태가 남아있으면 초기화
    if user_jobs.get(user_id, {}).get("status") == "running":
        user_jobs.pop(user_id, None)
    client.views_publish(user_id=user_id, view=_home_view(user_id))


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
    ocr_options = values["ocr_block"]["ocr_checkbox"].get("selected_options", [])
    run_ocr = len(ocr_options) > 0

    if not urls:
        _send_dm(client, user_id, "❌ 유효한 URL이 없습니다. `https://`로 시작하는 URL을 입력해주세요.")
        return

    user_jobs[user_id] = {"status": "running"}
    client.views_publish(user_id=user_id, view=_home_view(user_id))

    threading.Thread(
        target=_run_pipeline,
        args=(user_id, urls, run_ocr, client),
        daemon=True,
    ).start()


# ── 파이프라인 ────────────────────────────────────────────────────────────────

def _send_dm(client, user_id: str, text: str, blocks=None):
    res = client.conversations_open(users=user_id)
    channel = res["channel"]["id"]
    kwargs = {"channel": channel, "text": text}
    if blocks:
        kwargs["blocks"] = blocks
    client.chat_postMessage(**kwargs)


def _run_pipeline(user_id: str, urls: list, run_ocr: bool, client):
    try:
        from crawl.crawler import run_capture_bot
        from ocr import paddle_ocr

        run_name = "slack_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(_ROOT, "crawl", "output", run_name)
        ocr_dir = os.path.join(_ROOT, "ocr", "output", run_name) if run_ocr else None

        run_capture_bot(run_ocr_and_extract=False, urls=urls, output_dir=output_dir)

        if run_ocr and ocr_dir:
            paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)

        user_jobs[user_id] = {"status": "done", "output_dir": output_dir, "ocr_dir": ocr_dir}
        client.views_publish(user_id=user_id, view=_home_view(user_id))

        ocr_tag = " (OCR 포함)" if run_ocr else ""
        url_list = "\n".join(f"• {u}" for u in urls)
        _send_dm(
            client, user_id,
            text=f"✅ 크롤링 완료{ocr_tag}",
            blocks=[
                {"type": "section", "text": {"type": "mrkdwn", "text": f"✅ *크롤링 완료{ocr_tag}*\n{url_list}"}},
                {"type": "actions", "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "📊 Extract 실행"}, "style": "primary", "action_id": "run_extract"}
                ]}
            ]
        )

    except Exception as e:
        user_jobs[user_id] = {"status": "error"}
        client.views_publish(user_id=user_id, view=_home_view(user_id))
        _send_dm(client, user_id, f"❌ 처리 중 오류 발생:\n`{e}`")


# ── Extract ───────────────────────────────────────────────────────────────────

@app.action("run_extract")
def handle_extract(ack, body, client):
    ack()
    user_id = body["user"]["id"]
    job = user_jobs.get(user_id, {})

    output_dir = job.get("output_dir")
    ocr_dir = job.get("ocr_dir")

    if not output_dir:
        _send_dm(client, user_id, "❌ 크롤링 결과가 없습니다. App Home에서 먼저 실행해주세요.")
        return

    # Extract 버튼 비활성화 (중복 클릭 방지)
    channel = body["container"]["channel_id"]
    message_ts = body["container"]["message_ts"]
    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="⏳ Extract 실행 중...",
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "⏳ *Extract 실행 중입니다...*"}}]
    )

    threading.Thread(
        target=_run_extract,
        args=(user_id, output_dir, ocr_dir, client),
        daemon=True,
    ).start()


def _run_extract(user_id: str, output_dir: str, ocr_dir, client):
    try:
        from extract.extractor import build_summary
        by_domain = build_summary(output_dir, ocr_dir=ocr_dir)

        records = []
        for domain_records in by_domain.values():
            records.extend(domain_records)

        if not records:
            _send_dm(client, user_id, "결과를 가져오지 못했습니다.")
            return

        for rec in records:
            _send_dm(client, user_id, text=rec.get("상품명", "결과"), blocks=_result_blocks(rec))

    except Exception as e:
        _send_dm(client, user_id, f"❌ Extract 오류:\n`{e}`")


def _result_blocks(rec: dict) -> list:
    blocks = []
    url = rec.get("URL", "")
    product_name = rec.get("상품명") or "(상품명 미확인)"
    manufacturer = rec.get("제조원", "")
    mfr_source = rec.get("제조원_source", "")
    variants = rec.get("variants", [])

    blocks.append({"type": "header", "text": {"type": "plain_text", "text": product_name[:150]}})
    blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"🔗 {url}"}})

    if manufacturer:
        badge = f" `{mfr_source.upper()}`" if mfr_source else ""
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*제조원*: {manufacturer}{badge}"}})

    if variants:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*모델 ({len(variants)}개)*"}})

        for v in variants[:10]:
            model = v.get("model", "")
            model_source = v.get("model_source", "")
            m_badge = f" `{model_source.upper()}`" if model_source else ""
            spec_lines = []
            for spec in v.get("규격", []):
                s_source = spec.get("source", "")
                s_badge = f" `{s_source.upper()}`" if s_source else ""
                spec_lines.append(f"  └ {spec.get('text', '')}{s_badge}")

            text = f"• `{model}`{m_badge}"
            if spec_lines:
                text += "\n" + "\n".join(spec_lines)
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})

        if len(variants) > 10:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"_… 외 {len(variants) - 10}개_"}})

    return blocks


if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    print("슬랙봇 시작 (Ctrl+C로 종료)")
    handler.start()
