// ═══════════════════════════════════════════════════════════════════════════
// JobAgent Dashboard — Application Logic
// ═══════════════════════════════════════════════════════════════════════════

const API = window.location.origin;
let allJobs = [];
let currentPage = 1;
const rowsPerPage = 50;

// ─── Utility ─────────────────────────────────────────────────────────────

function toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.style.animation = 'toast-out 0.3s ease forwards';
        setTimeout(() => el.remove(), 300);
    }, 4000);
}

async function apiFetch(path, options = {}) {
    try {
        const res = await fetch(`${API}${path}`, {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || res.statusText);
        }
        return await res.json();
    } catch (e) {
        console.error(`[API] ${path} failed:`, e);
        throw e;
    }
}

function formatDate(isoStr) {
    if (!isoStr) return '—';
    try {
        const d = new Date(isoStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch { return isoStr.slice(0, 10); }
}

function getScoreClass(score) {
    const s = parseInt(score) || 0;
    if (s >= 8) return 'score-high';
    if (s >= 5) return 'score-mid';
    if (s >= 1) return 'score-low';
    return 'score-zero';
}

function truncate(str, len = 40) {
    if (!str) return '—';
    return str.length > len ? str.slice(0, len) + '…' : str;
}

// ─── Stats ───────────────────────────────────────────────────────────────

async function loadStats() {
    try {
        const stats = await apiFetch('/api/tracker/stats');
        document.getElementById('stat-total').textContent = stats.total ?? 0;
        document.getElementById('stat-found').textContent = stats.found ?? 0;
        document.getElementById('stat-shortlisted').textContent = stats.shortlisted ?? 0;
        document.getElementById('stat-tailored').textContent = stats.tailored ?? 0;
        document.getElementById('stat-applied').textContent = stats.applied ?? 0;
        document.getElementById('stat-rejected').textContent = stats.rejected ?? 0;
    } catch (e) {
        toast('Failed to load stats', 'error');
    }
}

// ─── Jobs Table ──────────────────────────────────────────────────────────

async function loadJobs() {
    try {
        allJobs = await apiFetch('/api/tracker/jobs');
        renderJobs();
    } catch (e) {
        toast('Failed to load jobs', 'error');
    }
}

function getFilteredJobs() {
    const statusFilter = document.getElementById('filter-status').value;
    const searchFilter = document.getElementById('filter-search').value.toLowerCase();
    const sortKey = document.getElementById('filter-sort').value;

    let filtered = allJobs;

    if (statusFilter) {
        filtered = filtered.filter(j => j.status === statusFilter);
    }

    if (searchFilter) {
        filtered = filtered.filter(j => {
            const hay = `${j.company} ${j.title} ${j.job_id} ${j.location} ${j.source}`.toLowerCase();
            return hay.includes(searchFilter);
        });
    }

    filtered.sort((a, b) => {
        if (sortKey === 'score') return (parseInt(b.score) || 0) - (parseInt(a.score) || 0);
        if (sortKey === 'company') return (a.company || '').localeCompare(b.company || '');
        if (sortKey === 'title') return (a.title || '').localeCompare(b.title || '');
        // default: last_updated descending
        return (b.last_updated || '').localeCompare(a.last_updated || '');
    });

    return filtered;
}

function renderJobs() {
    const tbody = document.getElementById('jobs-tbody');
    const jobs = getFilteredJobs();

    if (jobs.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="empty-state">No jobs found. Run Scout or adjust filters.</td></tr>';
        updatePaginationUI(0);
        return;
    }

    const totalPages = Math.ceil(jobs.length / rowsPerPage);
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const startIdx = (currentPage - 1) * rowsPerPage;
    const paginatedJobs = jobs.slice(startIdx, startIdx + rowsPerPage);

    tbody.innerHTML = paginatedJobs.map(job => {
        const score = parseInt(job.score) || 0;
        const status = job.status || 'found';

        return `
        <tr data-job-id="${job.job_id}">
            <td class="col-score">
                <span class="score-badge ${getScoreClass(score)}">${score}</span>
            </td>
            <td class="col-company">
                <span class="cell-company">${escapeHtml(job.company || '—')}</span>
            </td>
            <td class="col-title">
                <span class="cell-title">
                    ${job.apply_link
                        ? `<a href="${escapeHtml(job.apply_link)}" target="_blank" title="Open job posting">${escapeHtml(truncate(job.title, 50))}</a>`
                        : escapeHtml(truncate(job.title, 50))
                    }
                </span>
            </td>
            <td class="col-status">
                <span class="status-pill status-${status}">${status}</span>
            </td>
            <td class="col-location">
                <span class="cell-location">${escapeHtml(truncate(job.location, 25))}</span>
            </td>
            <td class="col-source">
                <span class="cell-source">${escapeHtml(job.source || '—')}</span>
            </td>
            <td class="col-date">
                <span class="cell-date">${formatDate(job.found_at)}</span>
            </td>
            <td class="col-actions">
                <button class="action-btn view-action" title="View Details" onclick="openJobDetail('${job.job_id}')">👁</button>
                ${job.apply_link ? `<button class="action-btn link-action" title="Open Link" onclick="window.open('${escapeHtml(job.apply_link)}', '_blank')">🔗</button>` : ''}
                <button class="action-btn tailor-action" title="Tailor Resume" onclick="tailorJob('${job.job_id}', this)">📄</button>
                <button class="action-btn delete-action" title="Delete Job" onclick="deleteJob('${job.job_id}', this)">🗑</button>
            </td>
        </tr>`;
    }).join('');

    updatePaginationUI(totalPages);
}

function updatePaginationUI(totalPages) {
    const prevBtn = document.getElementById('btn-prev-page');
    const nextBtn = document.getElementById('btn-next-page');
    const infoText = document.getElementById('pagination-info');

    if (!prevBtn || !nextBtn || !infoText) return;

    if (totalPages <= 0) {
        infoText.textContent = 'Page 0 of 0';
        prevBtn.disabled = true;
        nextBtn.disabled = true;
        return;
    }

    infoText.textContent = `Page ${currentPage} of ${totalPages}`;
    prevBtn.disabled = currentPage <= 1;
    nextBtn.disabled = currentPage >= totalPages;
}

function applyFiltersAndRender() {
    currentPage = 1;
    renderJobs();
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ─── Actions ─────────────────────────────────────────────────────────────

async function deleteJob(jobId, btn) {
    if (!confirm('Delete this job permanently?')) return;
    const origText = btn.textContent;
    btn.textContent = '⏳';
    btn.disabled = true;
    try {
        await apiFetch(`/api/tracker/${jobId}`, { method: 'DELETE' });
        toast('Job deleted', 'success');
        await refreshAll();
    } catch (e) {
        toast(`Delete failed: ${e.message}`, 'error');
        btn.textContent = origText;
        btn.disabled = false;
    }
}

async function tailorJob(jobId, btn) {
    const origText = btn.textContent;
    btn.textContent = '⏳';
    btn.disabled = true;
    try {
        const result = await apiFetch('/api/tailor/generate', {
            method: 'POST',
            body: JSON.stringify({ job_id: jobId }),
        });
        toast(`Resume tailored! File: ${result.filename}`, 'success');
        await refreshAll();
    } catch (e) {
        toast(`Tailoring failed: ${e.message}`, 'error');
    }
    btn.textContent = origText;
    btn.disabled = false;
}

async function openJobDetail(jobId) {
    const overlay = document.getElementById('modal-overlay');
    const body = document.getElementById('modal-body');

    body.innerHTML = '<p style="color: var(--text-muted); font-family: var(--font-mono);">Loading...</p>';
    overlay.classList.remove('hidden');

    try {
        const job = await apiFetch(`/api/scout/jobs/${jobId}`);

        const score = parseInt(job.score) || 0;
        const status = job.status || 'found';

        body.innerHTML = `
            <div class="detail-header">
                <h2>${escapeHtml(job.title || 'Unknown Title')}</h2>
                <span class="detail-company">${escapeHtml(job.company || 'Unknown')}</span>
            </div>

            <div class="detail-grid">
                <div class="detail-field">
                    <div class="detail-field-label">Score</div>
                    <div class="detail-field-value">
                        <span class="score-badge ${getScoreClass(score)}" style="width:32px;height:32px;font-size:0.8rem;">${score}</span>
                        <span style="margin-left:8px;">/10</span>
                    </div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Status</div>
                    <div class="detail-field-value">
                        <span class="status-pill status-${status}">${status}</span>
                    </div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Location</div>
                    <div class="detail-field-value">${escapeHtml(job.location || '—')}</div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Source</div>
                    <div class="detail-field-value">${escapeHtml(job.source || '—')}</div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Found At</div>
                    <div class="detail-field-value">${formatDate(job.found_at)}</div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Apply Link</div>
                    <div class="detail-field-value">
                        ${job.apply_link
                            ? `<a href="${escapeHtml(job.apply_link)}" target="_blank">Open ↗</a>`
                            : '—'
                        }
                    </div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Job ID</div>
                    <div class="detail-field-value" style="font-family:var(--font-mono);font-size:0.75rem;">${escapeHtml(job.job_id)}</div>
                </div>
                <div class="detail-field">
                    <div class="detail-field-label">Last Updated</div>
                    <div class="detail-field-value">${formatDate(job.last_updated)}</div>
                </div>
            </div>

            ${job.reason ? `
            <div class="detail-reason">
                <div class="detail-field-label">AI Reason</div>
                <div class="detail-field-value">${escapeHtml(job.reason)}</div>
            </div>
            ` : ''}

            ${job.description ? `
            <div class="detail-reason">
                <div class="detail-field-label">Job Description (excerpt)</div>
                <div class="detail-field-value" style="max-height:200px;overflow-y:auto;font-size:0.78rem;">${escapeHtml(job.description).slice(0, 2000)}</div>
            </div>
            ` : ''}

            <div class="detail-actions">
                <button class="detail-btn btn-primary" onclick="tailorJobFromModal('${job.job_id}', this)">📄 Tailor Resume</button>
                ${job.apply_link ? `<button class="detail-btn" onclick="window.open('${escapeHtml(job.apply_link)}', '_blank')">🔗 Open Posting</button>` : ''}
                <button class="detail-btn" onclick="updateJobStatus('${job.job_id}', 'shortlisted', this)">✅ Shortlist</button>
                <button class="detail-btn" onclick="updateJobStatus('${job.job_id}', 'applied', this)">🏁 Mark Applied</button>
                <button class="detail-btn btn-danger" onclick="deleteJobFromModal('${job.job_id}')">🗑 Delete</button>
            </div>
        `;
    } catch (e) {
        body.innerHTML = `<p style="color: var(--accent-red);">Failed to load details: ${escapeHtml(e.message)}</p>`;
    }
}

async function tailorJobFromModal(jobId, btn) {
    btn.textContent = '⏳ Tailoring...';
    btn.disabled = true;
    try {
        const result = await apiFetch('/api/tailor/generate', {
            method: 'POST',
            body: JSON.stringify({ job_id: jobId }),
        });
        toast(`Resume tailored! File: ${result.filename}`, 'success');
        btn.textContent = '✅ Done';
        await refreshAll();
    } catch (e) {
        toast(`Tailoring failed: ${e.message}`, 'error');
        btn.textContent = '📄 Tailor Resume';
        btn.disabled = false;
    }
}

async function deleteJobFromModal(jobId) {
    if (!confirm('Delete this job permanently?')) return;
    try {
        await apiFetch(`/api/tracker/${jobId}`, { method: 'DELETE' });
        toast('Job deleted', 'success');
        closeModal();
        await refreshAll();
    } catch (e) {
        toast(`Delete failed: ${e.message}`, 'error');
    }
}

async function updateJobStatus(jobId, newStatus, btn) {
    const orig = btn.textContent;
    btn.textContent = '⏳';
    btn.disabled = true;
    try {
        await apiFetch(`/api/tracker/${jobId}/status`, {
            method: 'PATCH',
            body: JSON.stringify({ status: newStatus }),
        });
        toast(`Status → ${newStatus}`, 'success');
        await refreshAll();
        // Re-open the detail modal with fresh data
        openJobDetail(jobId);
    } catch (e) {
        toast(`Update failed: ${e.message}`, 'error');
        btn.textContent = orig;
        btn.disabled = false;
    }
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
}

// ─── Nav Actions ─────────────────────────────────────────────────────────

async function runScout() {
    const btn = document.getElementById('btn-run-scout');
    btn.textContent = '⏳ Scouting...';
    btn.disabled = true;
    try {
        const result = await apiFetch('/api/scout/run', { method: 'POST' });
        toast(`Scout complete: ${result.new} new, ${result.duplicates} dupes`, 'success');
        // Wait a few seconds for background processing to begin
        setTimeout(() => refreshAll(), 3000);
    } catch (e) {
        toast(`Scout failed: ${e.message}`, 'error');
    }
    btn.innerHTML = '<span class="btn-icon">🔍</span> Run Scout';
    btn.disabled = false;
}

async function tailorAll() {
    const btn = document.getElementById('btn-tailor-all');
    btn.textContent = '⏳ Tailoring...';
    btn.disabled = true;
    try {
        const result = await apiFetch('/api/tailor/run_pending', { method: 'POST' });
        toast(`Tailoring ${result.count} jobs in background`, 'success');
        setTimeout(() => refreshAll(), 5000);
    } catch (e) {
        toast(`Tailor batch failed: ${e.message}`, 'error');
    }
    btn.innerHTML = '<span class="btn-icon">📄</span> Tailor All';
    btn.disabled = false;
}

// ─── Refresh ─────────────────────────────────────────────────────────────

async function refreshAll() {
    await Promise.all([loadStats(), loadJobs()]);
}

// ─── Init ────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Load data
    refreshAll();

    // Filters (reset pagination to 1)
    document.getElementById('filter-status').addEventListener('change', applyFiltersAndRender);
    document.getElementById('filter-search').addEventListener('input', applyFiltersAndRender);
    document.getElementById('filter-sort').addEventListener('change', applyFiltersAndRender);

    // Pagination Buttons
    document.getElementById('btn-prev-page')?.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            renderJobs();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });

    document.getElementById('btn-next-page')?.addEventListener('click', () => {
        const jobs = getFilteredJobs();
        const totalPages = Math.ceil(jobs.length / rowsPerPage);
        if (currentPage < totalPages) {
            currentPage++;
            renderJobs();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        }
    });

    // Stat card clicks → filter
    document.querySelectorAll('.stat-card').forEach(card => {
        card.addEventListener('click', () => {
            const status = card.dataset.status;
            const select = document.getElementById('filter-status');
            if (status === 'total') {
                select.value = '';
            } else {
                select.value = status;
            }
            applyFiltersAndRender();
        });
    });

    // Nav buttons
    document.getElementById('btn-run-scout').addEventListener('click', runScout);
    document.getElementById('btn-tailor-all').addEventListener('click', tailorAll);
    document.getElementById('btn-refresh').addEventListener('click', () => {
        toast('Refreshing...', 'info');
        refreshAll();
    });

    // Modal
    document.getElementById('modal-close').addEventListener('click', closeModal);
    document.getElementById('modal-overlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });

    // Auto-refresh every 30s
    setInterval(refreshAll, 30000);
});
