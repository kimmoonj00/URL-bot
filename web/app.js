// ── DOM refs ───────────────────────────────────────────────────────────────
const urlInput       = document.getElementById('url-input');
const ocrToggle      = document.getElementById('ocr-toggle');
const runBtn         = document.getElementById('run-btn');
const logSection     = document.getElementById('log-section');
const logOutput      = document.getElementById('log-output');
const logStatus      = document.getElementById('log-status');
const clearLogBtn    = document.getElementById('clear-log-btn');
const viewResultRow  = document.getElementById('view-result-row');
const viewResultBtn  = document.getElementById('view-result-btn');
const resultSection  = document.getElementById('result-section');
const resultContent  = document.getElementById('result-content');
const closeResultBtn = document.getElementById('close-result-btn');
const extractBtn     = document.getElementById('extract-btn');
const jobList        = document.getElementById('job-list');

let currentJobId = null;
let eventSource  = null;

// ── 크롤링 실행 ─────────────────────────────────────────────────────────────

runBtn.addEventListener('click', startJob);

urlInput.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') startJob();
});

async function startJob() {
  const urls = urlInput.value
    .split('\n')
    .map(u => u.trim())
    .filter(u => u.startsWith('http'));

  if (!urls.length) {
    shakeElement(urlInput);
    return;
  }

  setRunning(true);
  showLog();

  try {
    const res = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ urls, ocr: ocrToggle.checked }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      appendLog(`[오류] ${err.detail}`);
      setStatus('error');
      setRunning(false);
      return;
    }

    const { job_id } = await res.json();
    currentJobId = job_id;
    streamLogs(job_id);
    renderHistory();
  } catch (e) {
    appendLog(`[오류] 서버에 연결할 수 없습니다: ${e.message}`);
    setStatus('error');
    setRunning(false);
  }
}

// ── SSE 로그 스트리밍 ────────────────────────────────────────────────────────

function streamLogs(jobId) {
  if (eventSource) eventSource.close();

  eventSource = new EventSource(`/api/stream/${jobId}`);

  eventSource.onmessage = (e) => {
    const data = JSON.parse(e.data);

    if (data.type === 'log') {
      appendLog(data.text);
    } else if (data.type === 'done') {
      const ok = data.status === 'done';
      setStatus(ok ? 'done' : 'error');
      if (data.error) appendLog(`[오류] ${data.error}`);
      setRunning(false);
      if (ok) viewResultRow.hidden = false;
      eventSource.close();
      renderHistory();
    }
  };

  eventSource.onerror = () => {
    appendLog('[오류] 스트리밍 연결이 끊어졌습니다.');
    setStatus('error');
    setRunning(false);
    eventSource.close();
  };
}

// ── 결과 뷰어 ────────────────────────────────────────────────────────────────

viewResultBtn.addEventListener('click', () => {
  if (currentJobId) showResults(currentJobId);
});

closeResultBtn.addEventListener('click', () => {
  resultSection.hidden = true;
  resultContent.innerHTML = '';
});

async function showResults(jobId) {
  resultSection.hidden = false;
  resultContent.innerHTML = '<p class="empty-state">불러오는 중...</p>';
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const res = await fetch(`/api/jobs/${jobId}/results`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      resultContent.innerHTML = `<p class="empty-state">${err.detail}</p>`;
      return;
    }
    const items = await res.json();
    renderResults(items);
  } catch (e) {
    resultContent.innerHTML = `<p class="empty-state">오류: ${e.message}</p>`;
  }
}

function renderResults(items) {
  if (!items.length) {
    resultContent.innerHTML = '<p class="empty-state">결과가 없습니다.</p>';
    return;
  }

  resultContent.innerHTML = items.map((item, idx) => {
    const statusLabel = { captured: '완료', blocked: '차단', error: '오류' }[item.status] ?? item.status;
    const statusClass = item.status === 'captured' ? 'done' : 'error';
    const elapsed = item.elapsed_seconds ? `${item.elapsed_seconds}초` : '';
    const mdHtml = item.markdown
      ? marked.parse(item.markdown)
      : '<p class="empty-state">내용이 없습니다.</p>';

    return `
      <div class="result-item" id="result-item-${idx}">
        <button class="result-toggle" data-idx="${idx}">
          <span class="status-badge ${statusClass}">${statusLabel}</span>
          <span class="result-title">${escHtml(item.title || item.url)}</span>
          <span class="result-stats">${elapsed}</span>
          <span class="chevron">▾</span>
        </button>
        <div class="result-body" hidden>
          <a class="result-url-link" href="${escHtml(item.url)}" target="_blank" rel="noopener">${escHtml(item.url)}</a>
          <div class="md-body">${mdHtml}</div>
        </div>
      </div>
    `;
  }).join('');

  // 아코디언 토글
  resultContent.querySelectorAll('.result-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.result-item');
      const body = item.querySelector('.result-body');
      const isOpen = !body.hidden;
      body.hidden = isOpen;
      item.classList.toggle('open', !isOpen);
    });
  });

  // 첫 번째 항목 자동 펼침
  const first = resultContent.querySelector('.result-item');
  if (first) {
    first.querySelector('.result-body').hidden = false;
    first.classList.add('open');
  }
}

// ── 실행 기록 ────────────────────────────────────────────────────────────────

async function renderHistory() {
  try {
    const res = await fetch('/api/jobs');
    const jobs = await res.json();

    if (!jobs.length) {
      jobList.innerHTML = '<p class="empty-state">아직 실행 기록이 없습니다</p>';
      return;
    }

    jobList.innerHTML = jobs.map(j => {
      const statusLabel = { running: '실행 중', done: '완료', error: '오류' }[j.status] ?? j.status;
      const urlText = j.urls[0] + (j.urls.length > 1 ? ` 외 ${j.urls.length - 1}개` : '');
      const timeText = new Date(j.created_at).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      return `
        <div class="job-item">
          <span class="status-badge ${j.status}">${statusLabel}</span>
          <span class="job-urls" title="${escHtml(j.urls.join('\n'))}">${escHtml(urlText)}</span>
          <div class="job-meta">
            ${j.ocr ? '<span class="job-tag">OCR</span>' : ''}
            <span class="job-time">${timeText}</span>
            ${j.status === 'done' ? `<button class="job-result-btn" data-job="${j.id}">결과 보기</button>` : ''}
          </div>
        </div>
      `;
    }).join('');

    jobList.querySelectorAll('.job-result-btn').forEach(btn => {
      btn.addEventListener('click', () => showResults(btn.dataset.job));
    });
  } catch {
    // 조용히 무시
  }
}

// ── Extract (stub) ───────────────────────────────────────────────────────────

extractBtn.addEventListener('click', () => {
  alert('API 키 연동 후 사용 가능합니다.');
});

// ── 유틸 ─────────────────────────────────────────────────────────────────────

function showLog() {
  logSection.hidden = false;
  viewResultRow.hidden = true;
  resultSection.hidden = true;
  logOutput.textContent = '';
  setStatus('running');
}

function appendLog(text) {
  logOutput.textContent += text + '\n';
  logOutput.scrollTop = logOutput.scrollHeight;
}

function setStatus(status) {
  const labels = { running: '실행 중', done: '완료', error: '오류' };
  logStatus.className = `status-badge ${status}`;
  logStatus.textContent = labels[status] ?? status;
}

function setRunning(isRunning) {
  runBtn.disabled = isRunning;
  runBtn.textContent = isRunning ? '실행 중...' : '실행';
}

function shakeElement(el) {
  el.style.borderColor = '#dc2626';
  setTimeout(() => { el.style.borderColor = ''; }, 1500);
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

clearLogBtn.addEventListener('click', () => {
  logOutput.textContent = '';
});

// ── 초기 로드 ─────────────────────────────────────────────────────────────────
renderHistory();
