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
const extractBtn            = document.getElementById('extract-btn');
const extractResultSection  = document.getElementById('extract-result-section');
const extractResultContent  = document.getElementById('extract-result-content');
const closeExtractBtn       = document.getElementById('close-extract-btn');
const jobList               = document.getElementById('job-list');
const historyToggle         = document.getElementById('history-toggle');

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
      if (data.error) {
        if (data.error.includes('대기열')) {
          alert('⚠️ 현재 사용 인원이 너무 많습니다. 잠시 후 다시 시도해 주세요.');
        }
        appendLog(`[오류] ${data.error}`);
      }
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

historyToggle.addEventListener('click', () => {
  const isOpen = !jobList.hidden;
  jobList.hidden = isOpen;
  historyToggle.classList.toggle('open', !isOpen);
});

async function renderHistory() {
  try {
    const res = await fetch('/api/jobs');
    const jobs = await res.json();

    if (!jobs.length) {
      jobList.innerHTML = '<p class="empty-state">아직 작업 기록이 없습니다</p>';
      return;
    }

    jobList.innerHTML = jobs.map(j => {
      const statusLabel = { running: '진행 중', done: '완료', error: '오류' }[j.status] ?? j.status;
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

// ── Extract ──────────────────────────────────────────────────────────────────

closeExtractBtn.addEventListener('click', () => {
  extractResultSection.hidden = true;
  extractResultContent.innerHTML = '';
});

extractBtn.addEventListener('click', async () => {
  if (!currentJobId) {
    alert('먼저 크롤링을 실행하세요.');
    return;
  }

  extractBtn.disabled = true;
  extractBtn.textContent = '추출 중...';

  try {
    const res = await fetch('/api/extract', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: currentJobId }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      alert(`추출 실패: ${err.detail}`);
      return;
    }

    const { results } = await res.json();
    renderExtractResults(results);
  } catch (e) {
    alert(`오류: ${e.message}`);
  } finally {
    extractBtn.disabled = false;
    extractBtn.textContent = 'Extract 실행';
  }
});

function renderSpec(spec) {
  if (typeof spec === 'string') {
    return `<div class="spec-row">${escHtml(spec)} <span class="badge badge-dom">DOM</span></div>`;
  }
  const text = escHtml(spec.text || '');
  const src = spec.source === 'ocr' ? 'ocr' : 'dom';
  return `<div class="spec-row">${text} <span class="badge badge-${src}">${src.toUpperCase()}</span></div>`;
}

function sourceBadge(source) {
  const s = source === 'ocr' ? 'ocr' : 'dom';
  return `<span class="badge badge-${s}">${s.toUpperCase()}</span>`;
}

function renderExtractResults(results) {
  extractResultSection.hidden = false;
  const legend = `
    <div class="source-legend">
      <span class="badge badge-dom">DOM</span> HTML 구조·표에서 추출
      <span class="legend-sep">·</span>
      <span class="badge badge-ocr">OCR</span> 이미지 인식 — 오탈자 가능성 있음
    </div>`;
  extractResultContent.innerHTML = legend + results.map(r => {
    const variants = r['variants'] || [];
    const variantsHtml = variants.length
      ? `<table class="extract-table">
          <thead><tr><th>모델번호</th><th>규격</th></tr></thead>
          <tbody>
            ${variants.map(v => `
              <tr>
                <td class="model-cell">${escHtml(v.model || '—')} ${v.model && v.model_source ? sourceBadge(v.model_source) : ''}</td>
                <td>${(v['규격'] || []).map(renderSpec).join('')}</td>
              </tr>
            `).join('')}
          </tbody>
        </table>`
      : '<p class="empty-state">추출된 규격 없음</p>';

    const manufacturer = r['제조원'];
    const mfrSource = r['제조원_source'] || 'dom';

    return `
      <div class="extract-card">
        <div class="extract-product-name">${escHtml(r['상품명'] || '(상품명 없음)')}</div>
        ${manufacturer ? `<div class="extract-manufacturer">제조원: ${escHtml(manufacturer)} ${sourceBadge(mfrSource)}</div>` : ''}
        <a class="result-url-link" href="${escHtml(r['URL'])}" target="_blank" rel="noopener">${escHtml(r['URL'])}</a>
        ${variantsHtml}
      </div>
    `;
  }).join('');

  extractResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

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
  const labels = { running: '진행 중', done: '완료', error: '오류' };
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

// ── 탭 전환 ──────────────────────────────────────────────────────────────────

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.dataset.tab;
    document.getElementById('tab-crawl').hidden = tab !== 'crawl';
    document.getElementById('tab-search').hidden = tab !== 'search';
    if (tab === 'search') searchResultSection.hidden = true;
  });
});

// ── 검색 ─────────────────────────────────────────────────────────────────────

const searchInput         = document.getElementById('search-input');
const searchBtn           = document.getElementById('search-btn');
const searchResultSection = document.getElementById('search-result-section');
const searchResultTitle   = document.getElementById('search-result-title');
const searchResultContent = document.getElementById('search-result-content');

searchBtn.addEventListener('click', runSearch);
searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });

async function runSearch() {
  const q = searchInput.value.trim();
  if (!q) {
    searchResultSection.hidden = true;
    return;
  }
  searchResultSection.hidden = false;
  searchResultContent.innerHTML = '<p class="empty-state">검색 중...</p>';

  try {
    const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
    if (!res.ok) throw new Error(res.statusText);
    const items = await res.json();
    searchResultTitle.textContent = q
      ? `검색 결과 (${items.length}건)`
      : `전체 Archive (${items.length}건)`;
    renderSearchResults(items);
  } catch (e) {
    searchResultContent.innerHTML = `<p class="empty-state">오류: ${e.message}</p>`;
  }
}

function renderSearchResults(items) {
  if (!items.length) {
    searchResultContent.innerHTML = '<p class="empty-state">결과가 없습니다.</p>';
    return;
  }

  searchResultContent.innerHTML = items.map((item, idx) => {
    const name = item.product_name || item.title || item.domain || '(이름 없음)';
    const dateLabel = `${item.date} ${item.time.slice(0,2)}:${item.time.slice(2,4)}`;
    const srcTag = `<span class="job-tag">${item.source}</span>`;
    const extractTag = item.has_extract ? '<span class="job-tag" style="background:#dcfce7;color:#15803d">추출완료</span>' : '';
    const models = item.models.length ? `모델: ${item.models.slice(0,5).join(', ')}` : '';

    const imagesHtml = item.images.length
      ? item.images.slice(0, 12).map(src => `
          <div class="search-img-wrap">
            <img src="${escHtml(src)}" loading="lazy" onerror="this.style.display='none'">
            <a class="img-link" href="${escHtml(src)}" target="_blank" rel="noopener"><span>열기</span></a>
          </div>`).join('')
      : '<span class="search-no-images">저장된 이미지 없음</span>';

    const product = item.product || {};
    const variants = product.variants || [];
    const manufacturer = product['제조원'] || item.manufacturer || '';
    const mfrSource = product['제조원_source'] || 'dom';

    const extractHtml = item.has_extract ? `
      <div class="search-extract">
        ${manufacturer ? `<div class="extract-manufacturer">제조원: ${escHtml(manufacturer)} ${sourceBadge(mfrSource)}</div>` : ''}
        ${variants.length ? `
          <table class="extract-table" style="margin-top:10px">
            <thead><tr><th>모델번호</th><th>규격</th></tr></thead>
            <tbody>
              ${variants.map(v => `
                <tr>
                  <td class="model-cell">${escHtml(v.model || '—')} ${v.model && v.model_source ? sourceBadge(v.model_source) : ''}</td>
                  <td>${(v['규격'] || []).map(renderSpec).join('')}</td>
                </tr>`).join('')}
            </tbody>
          </table>` : '<p class="empty-state" style="margin-top:8px">추출된 규격 없음</p>'}
      </div>` : '';

    return `
      <div class="search-item" id="search-item-${idx}">
        <button class="search-toggle" data-idx="${idx}">
          <span class="search-name">${escHtml(name)}</span>
          <div class="search-meta">
            ${srcTag}${extractTag}
            <span class="search-date">${dateLabel}</span>
          </div>
          <span class="chevron">▾</span>
        </button>
        <div class="search-body" hidden>
          <a class="search-url" href="${escHtml(item.url)}" target="_blank" rel="noopener">${escHtml(item.url)}</a>
          ${extractHtml}
          <div style="margin-top:12px;font-size:12px;font-weight:600;color:var(--text-muted);margin-bottom:6px;">이미지</div>
          <div class="search-images">${imagesHtml}</div>
        </div>
      </div>`;
  }).join('');

  searchResultContent.querySelectorAll('.search-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = btn.closest('.search-item');
      const body = item.querySelector('.search-body');
      const isOpen = !body.hidden;
      body.hidden = isOpen;
      item.classList.toggle('open', !isOpen);
    });
  });
}

// ── 초기 로드 ─────────────────────────────────────────────────────────────────
renderHistory();
