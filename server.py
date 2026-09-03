import asyncio
import json
import os
import queue
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # 한국어 Windows(cp949) 콘솔 인코딩으로는 crawl/crawler.py 등이 출력하는
    # 이모지(⏱️ 등)를 print()할 때 UnicodeEncodeError가 난다. _LogCapture가
    # 원본 stdout에도 그대로 이어 쓰기 때문에, 리다이렉트 전에 원본 stdout
    # 자체의 인코딩을 미리 바꿔둬야 한다(ocr/paddle_ocr.py와 동일한 처리).
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

app = FastAPI()

# 메모리 내 job 저장소 (서버 재시작 시 초기화됨)
jobs: dict = {}

JOB_TTL_HOURS = 1
_CLEANUP_INTERVAL = 600  # 10분마다 체크


def _delete_job_files(job: dict):
    for key in ("output_dir", "ocr_dir"):
        d = job.get(key)
        if d and os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    if job.get("output_dir"):
        run_name = os.path.basename(job["output_dir"])
        extract_dir = os.path.join(_ROOT, "extract", "output", run_name)
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)


def _cleanup_loop():
    while True:
        time.sleep(_CLEANUP_INTERVAL)
        cutoff = datetime.now() - timedelta(hours=JOB_TTL_HOURS)
        expired = [
            jid for jid, j in list(jobs.items())
            if j["status"] in ("done", "error")
            and datetime.fromisoformat(j["created_at"]) < cutoff
        ]
        for jid in expired:
            job = jobs.pop(jid, None)
            if job:
                _delete_job_files(job)
        if expired:
            print(f"[cleanup] {len(expired)}개 job 만료 삭제 (TTL {JOB_TTL_HOURS}h)")


def _cleanup_gui_dirs():
    """gui_* 디렉토리만 정리한다. cli_* (main.py 결과)는 절대 건드리지 않는다."""
    for base in (
        os.path.join(_ROOT, "crawl", "output"),
        os.path.join(_ROOT, "ocr", "output"),
        os.path.join(_ROOT, "extract", "output"),
    ):
        if not os.path.isdir(base):
            continue
        for name in os.listdir(base):
            if name.startswith("gui_"):
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)


@app.on_event("startup")
async def start_cleanup():
    _cleanup_gui_dirs()  # 이전 세션 gui_* 파일 정리
    threading.Thread(target=_cleanup_loop, daemon=True).start()


class RunRequest(BaseModel):
    urls: list[str]
    ocr: bool = False


class ExtractRequest(BaseModel):
    job_id: str


class _LogCapture:
    """print() 출력을 job 로그 큐로 리다이렉트하면서 원본 stdout에도 유지한다."""

    errors = "replace"

    def __init__(self, log_queue: queue.Queue, original):
        self._q = log_queue
        self._orig = original
        self.encoding = getattr(original, "encoding", "utf-8")

    def write(self, text: str):
        if text.strip():
            self._q.put(text.rstrip("\n"))
        self._orig.write(text)

    def flush(self):
        self._orig.flush()

    def isatty(self):
        return False

    def fileno(self):
        return self._orig.fileno()


def _run_pipeline(job_id: str, urls: list, run_ocr: bool):
    job = jobs[job_id]
    log_q = job["log_queue"]
    original_stdout = sys.stdout
    sys.stdout = _LogCapture(log_q, original_stdout)

    try:
        from crawl.crawler import run_capture_bot

        # GUI 실행은 gui_날짜/ 접두사 — main.py의 cli_날짜/와 구별해 TTL 정리 대상임
        gui_run_name = "gui_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = os.path.join(_ROOT, "crawl", "output", gui_run_name)
        run_capture_bot(run_ocr_and_extract=False, urls=urls, output_dir=output_dir)
        job["output_dir"] = output_dir

        if run_ocr and output_dir:
            from ocr import paddle_ocr

            ocr_dir = os.path.join(_ROOT, "ocr", "output", gui_run_name)
            paddle_ocr.ocr_capture_dir(output_dir, ocr_dir)
            job["ocr_dir"] = ocr_dir

        job["status"] = "done"
    except Exception as exc:
        log_q.put(f"[오류] {exc}")
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        sys.stdout = original_stdout
        log_q.put(None)  # 스트리밍 종료 신호


@app.post("/api/run")
async def run_job(req: RunRequest):
    urls = [u.strip() for u in req.urls if u.strip().startswith("http")]
    if not urls:
        raise HTTPException(status_code=400, detail="유효한 URL을 입력하세요.")

    job_id = uuid.uuid4().hex[:8]
    jobs[job_id] = {
        "id": job_id,
        "status": "running",
        "urls": urls,
        "ocr": req.ocr,
        "log_queue": queue.Queue(),
        "output_dir": None,
        "ocr_dir": None,
        "error": None,
        "created_at": datetime.now().isoformat(),
    }

    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, urls, req.ocr),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream_logs(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job을 찾을 수 없습니다.")

    job = jobs[job_id]
    log_q = job["log_queue"]

    async def generate():
        while True:
            try:
                line = log_q.get_nowait()
                if line is None:
                    payload = {"type": "done", "status": job["status"]}
                    if job.get("error"):
                        payload["error"] = job["error"]
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    break
                yield f"data: {json.dumps({'type': 'log', 'text': line}, ensure_ascii=False)}\n\n"
            except queue.Empty:
                if job["status"] in ("done", "error"):
                    yield f"data: {json.dumps({'type': 'done', 'status': job['status']}, ensure_ascii=False)}\n\n"
                    break
                await asyncio.sleep(0.1)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/jobs")
async def list_jobs():
    return [
        {
            "id": j["id"],
            "status": j["status"],
            "urls": j["urls"],
            "ocr": j["ocr"],
            "created_at": j["created_at"],
        }
        for j in sorted(jobs.values(), key=lambda x: x["created_at"], reverse=True)
    ]


@app.get("/api/jobs/{job_id}/results")
async def job_results(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job을 찾을 수 없습니다.")

    output_dir = jobs[job_id].get("output_dir")
    ocr_dir = jobs[job_id].get("ocr_dir")
    if not output_dir or not os.path.isdir(output_dir):
        raise HTTPException(status_code=404, detail="결과 디렉터리가 없습니다. 크롤링이 완료되지 않았습니다.")

    results = []
    for subdir in sorted(os.listdir(output_dir)):
        subpath = os.path.join(output_dir, subdir)
        if not os.path.isdir(subpath):
            continue

        meta_path = os.path.join(subpath, "metadata.json")
        if not os.path.exists(meta_path):
            continue

        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)

        # OCR을 돌렸으면 crawl의 context.md + OCR 텍스트가 합쳐진 product.md가
        # ocr_dir 쪽에 있다. 있으면 그걸 우선 보여주고, 없으면 crawl 단계의
        # context.md(DOM/표만 있음)로 대체한다.
        markdown = ""
        product_md_path = os.path.join(ocr_dir, subdir, "product.md") if ocr_dir else None
        if product_md_path and os.path.exists(product_md_path):
            with open(product_md_path, encoding="utf-8") as f:
                markdown = f.read()
        else:
            ctx_path = os.path.join(subpath, "context.md")
            if os.path.exists(ctx_path):
                with open(ctx_path, encoding="utf-8") as f:
                    markdown = f.read()

        results.append({
            "url": meta.get("url", ""),
            "title": meta.get("title", ""),
            "status": meta.get("status", ""),
            "elapsed_seconds": meta.get("elapsed_seconds", 0),
            "markdown": markdown,
        })

    return results


@app.post("/api/extract")
async def run_extract(req: ExtractRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job을 찾을 수 없습니다.")

    output_dir = jobs[req.job_id].get("output_dir")
    ocr_dir = jobs[req.job_id].get("ocr_dir")

    if not output_dir or not os.path.isdir(output_dir):
        raise HTTPException(status_code=400, detail="크롤링 결과가 없습니다. 먼저 크롤링을 실행하세요.")

    def _run():
        # .env 파일 로드 (python-dotenv 있으면)
        try:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(_ROOT, ".env"))
        except ImportError:
            pass
        from extract.extractor import build_summary
        return build_summary(output_dir, ocr_dir=ocr_dir)

    try:
        by_domain = await asyncio.to_thread(_run)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    results = []
    for domain_records in by_domain.values():
        results.extend(domain_records)

    return {"results": results}


# 정적 파일 서빙 (반드시 마지막에 등록)
web_dir = os.path.join(_ROOT, "web")
if os.path.isdir(web_dir):
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    port = 8000
    print(f"\n  URL Bot 서버 시작")
    print(f"  접속 주소 → http://localhost:{port}\n")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
