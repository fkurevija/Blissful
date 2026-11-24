// Downloads tab: job queue and history.
'use strict';

let jobsAutoRefresh = null;
let jobsSort = { key: 'updated_at', dir: 'desc' };
let currentJobs = [];

function sortJobsBy(key) {
    if (jobsSort.key === key) {
        jobsSort.dir = jobsSort.dir === 'asc' ? 'desc' : 'asc';
    } else {
        jobsSort = { key: key, dir: 'asc' };
    }
    renderJobs(currentJobs);
}

function jobSortValue(job, key) {
    if (key === 'status') return job.status || '';
    if (key === 'job') return jobLabel(job).toLowerCase();
    if (key === 'source') return job.source || '';
    if (key === 'updated') return job.updated_at || '';
    if (key === 'detail') return job.failure_reason || '';
    return '';
}

function showDownloadsTab() {
    const button = [...document.querySelectorAll('.tab-button')]
        .find(b => b.textContent.includes('Downloads'));
    if (button) openTab({ currentTarget: button }, 'downloads-tab');
}

function jobLabel(job) {
    const payload = job.payload || {};
    const artist = payload.artist || '';
    const album = payload.album || '';
    if (artist && album) return `${artist} — ${album}`;
    if (payload.mode === 'stale-cleanup') return 'Stale torrent cleanup';
    if (payload.mode === 'all' || payload.mode === 'selected') return 'Wanted search';
    return album || artist || job.dedupe_key || job.id;
}

function renderJobs(jobs) {
    const list = document.getElementById('jobsList');
    const summary = document.getElementById('jobsSummary');
    if (!list || !summary) return;
    currentJobs = jobs || [];
    const sorted = currentJobs.slice().sort((a, b) => {
        const av = String(jobSortValue(a, jobsSort.key)).toLowerCase();
        const bv = String(jobSortValue(b, jobsSort.key)).toLowerCase();
        const result = av.localeCompare(bv);
        return jobsSort.dir === 'asc' ? result : -result;
    });
    const counts = { pending: 0, running: 0, succeeded: 0, failed: 0 };
    currentJobs.forEach(job => {
        if (counts[job.status] !== undefined) counts[job.status] += 1;
    });
    summary.textContent = `Pending ${counts.pending} · Running ${counts.running} · Succeeded ${counts.succeeded} · Failed ${counts.failed}`;
    list.innerHTML = '';
    if (!currentJobs.length) {
        list.innerHTML = '<div style="padding:12px"><em>No jobs yet.</em></div>';
        return;
    }
    const table = document.createElement('table');
    table.className = 'jobs-table';
    const head = document.createElement('thead');
    const headRow = document.createElement('tr');
    const columns = [
        ['status', 'Status'], ['job', 'Job'], ['source', 'Source'],
        ['updated', 'Updated'], ['detail', 'Detail']
    ];
    columns.forEach(([key, label]) => {
        const th = document.createElement('th');
        th.dataset.sortKey = key;
        const arrow = jobsSort.key === key ? (jobsSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
        th.textContent = label + arrow;
        th.addEventListener('click', () => sortJobsBy(key));
        headRow.appendChild(th);
    });
    const actionHead = document.createElement('th');
    actionHead.textContent = 'Actions';
    headRow.appendChild(actionHead);
    head.appendChild(headRow);
    table.appendChild(head);
    const body = document.createElement('tbody');
    sorted.forEach(job => {
        const row = document.createElement('tr');
        const status = document.createElement('td');
        status.className = 'job-status';
        status.dataset.status = job.status;
        status.textContent = job.status;
        row.appendChild(status);

        const label = document.createElement('td');
        label.textContent = jobLabel(job);
        const tracks = (job.payload || {}).tracks || [];
        if (tracks.length) label.textContent += ` (${tracks.length} track${tracks.length === 1 ? '' : 's'})`;
        row.appendChild(label);

        const source = document.createElement('td');
        source.textContent = job.source || '';
        row.appendChild(source);

        const updated = document.createElement('td');
        updated.textContent = job.updated_at ? String(job.updated_at).replace('T', ' ').slice(0, 19) : '';
        row.appendChild(updated);

        const detail = document.createElement('td');
        detail.className = 'job-reason';
        const result = job.result || {};
        const failures = result.failures || [];
        const progress = job.progress || {};
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-secondary job-action job-details';
        btn.textContent = 'Details';
        btn.dataset.jobId = job.id;
        btn.addEventListener('click', () => showJobDetails(job.id));
        detail.appendChild(btn);
        row.appendChild(detail);

        const actions = document.createElement('td');
        actions.className = 'job-actions';
        if (job.status === 'failed') {
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'btn btn-secondary job-action';
            retry.textContent = 'Retry';
            retry.addEventListener('click', async () => {
                try {
                    const res = await fetch(`/api/jobs/${job.id}/retry`, { method: 'POST' });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                    loadJobs();
                } catch (error) {
                    showNotification(`Retry failed: ${error.message}`, 'error');
                }
            });
            actions.appendChild(retry);
        }
        if (job.status === 'pending' || job.status === 'running') {
            const cancel = document.createElement('button');
            cancel.type = 'button';
            cancel.className = 'btn btn-secondary job-action';
            cancel.textContent = 'Cancel';
            cancel.addEventListener('click', async () => {
                try {
                    const res = await fetch(`/api/jobs/${job.id}/cancel`, { method: 'POST' });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                    // Cancelling an in-flight job must stop the run that owns it.
                    try { fetch('/api/wanted/cancel', { method: 'POST', body: '{}' }); } catch (e) {}
                    loadJobs();
                } catch (error) {
                    showNotification(`Cancel failed: ${error.message}`, 'error');
                }
            });
            actions.appendChild(cancel);
        }
        if (job.status !== 'pending' && job.status !== 'running') {
            const del = document.createElement('button');
            del.type = 'button';
            del.className = 'btn btn-secondary job-action';
            del.textContent = 'Delete';
            del.addEventListener('click', async () => {
                try {
                    const res = await fetch(`/api/jobs/${job.id}`, { method: 'DELETE' });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                    loadJobs();
                } catch (error) {
                    showNotification(`Delete failed: ${error.message}`, 'error');
                }
            });
            actions.appendChild(del);
        }
        row.appendChild(actions);
        body.appendChild(row);
    });
    table.appendChild(body);
    list.appendChild(table);
}

let detailsPane = null;
let detailsTimer = null;
let detailsJobId = null;
let detailsPlainText = '';

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function closeJobDetails() {
    if (detailsTimer) { clearInterval(detailsTimer); detailsTimer = null; }
    detailsJobId = null;
    if (detailsPane) detailsPane.style.display = 'none';
}

function renderJobDetails(job) {
    if (!detailsPane || !job) return;
    const body = detailsPane.querySelector('.job-details-body');
    const result = job.result || {};
    const failures = result.failures || [];
    const progress = job.progress || {};
    const fields = [];
    const add = (label, value) => {
        if (value !== undefined && value !== null && value !== '') {
            fields.push({ label, text: String(value) });
        }
    };
    add('Job', jobLabel(job));
    add('Status', job.status);
    add('Source', job.source || '');
    add('Updated', job.updated_at || '');
    add('Failure reason', job.failure_reason || '');
    add('Phase', progress.phase || '');
    add('Album', progress.album_title || '');
    if (progress.processed !== undefined && progress.total) {
        add('Progress', `${progress.processed}/${progress.total}`);
    }
    if (progress.current_track && progress.total_tracks) {
        add('Track', `${progress.current_track}/${progress.total_tracks}`);
    }
    add('Lidarr', progress.command_status || '');
    if (result.successful !== undefined) add('Imported', result.successful);
    if (result.failed !== undefined) add('Failed', result.failed);
    if (result.total_tracks !== undefined) add('Total tracks', result.total_tracks);

    // Original structure: job info at the top as bold-label lines, then
    // a separate fixed-size scrollable log pane below it.
    const log = Array.isArray(job.log) ? job.log : [];

    body.innerHTML = '';
    if (!fields.length && !log.length) {
        body.innerHTML = '<em>No details recorded.</em>';
    } else {
        fields.forEach(f => {
            const line = document.createElement('div');
            line.className = 'job-detail-line';
            line.innerHTML = `<strong>${escapeHtml(f.label)}:</strong> ${escapeHtml(f.text)}`;
            body.appendChild(line);
        });
        if (result.failures && result.failures.length) {
            const head = document.createElement('div');
            head.className = 'job-detail-line job-detail-heading';
            head.textContent = `Per-track failures (${result.failures.length}):`;
            body.appendChild(head);
            result.failures.forEach(f => {
                const attempts = Array.isArray(f.attempts)
                    ? f.attempts.map(a => `${a.source || ''}: ${a.error || a.message || ''}`)
                    : [];
                const line = document.createElement('div');
                line.className = 'job-detail-line';
                line.textContent = `  - ${f.title || 'track'}: ${f.error || ''}`;
                body.appendChild(line);
                attempts.forEach(a => {
                    const al = document.createElement('div');
                    al.className = 'job-detail-line';
                    al.textContent = `      ${a}`;
                    body.appendChild(al);
                });
            });
        }
    }
    // The log lives in its own HTML pane with a fixed height; the
    // scrollbar grows as lines are appended.
    let logPane = detailsPane.querySelector('.job-details-log');
    if (!logPane) {
        logPane = document.createElement('div');
        logPane.className = 'job-details-log';
        const label = document.createElement('div');
        label.className = 'job-detail-heading';
        label.textContent = 'Live log:';
        detailsPane.insertBefore(label, detailsPane.querySelector('.job-details-footer'));
        detailsPane.insertBefore(logPane, detailsPane.querySelector('.job-details-footer'));
    }
    const wasAtBottom = !logPane.dataset.init ||
        (logPane.scrollHeight - logPane.scrollTop - logPane.clientHeight) < 24;
    logPane.innerHTML = '';
    if (log.length) {
        log.forEach(text => {
            const entry = document.createElement('div');
            entry.className = 'job-log-entry';
            entry.textContent = text;
            logPane.appendChild(entry);
        });
    } else {
        logPane.textContent = '(waiting for log entries…)';
    }
    logPane.dataset.init = '1';
    // Only autoscroll when the user was already at the bottom (or on the
    // first render). If they scrolled up to read older entries, leave
    // their scroll position alone until they scroll back down.
    if (wasAtBottom) logPane.scrollTop = logPane.scrollHeight;
    // Keep the plain log text for the Copy logs button.
    detailsPlainText = log.length ? log.join('\n') : '';
    const live = job.status === 'pending' || job.status === 'running';
    const badge = detailsPane.querySelector('.job-details-live');
    if (badge) badge.style.display = live ? 'inline' : 'none';
}
async function refreshJobDetails() {
    if (!detailsJobId) return;
    // Do not wipe a selection the user is copying from the pane.
    const sel = window.getSelection();
    if (sel && sel.toString() && detailsPane && detailsPane.contains(sel.anchorNode)) return;
    try {
        const res = await fetch('/api/jobs?limit=500');
        const data = await res.json();
        const job = (data.jobs || []).find(j => j.id === detailsJobId);
        if (job) renderJobDetails(job);
        const live = job && (job.status === 'pending' || job.status === 'running');
        if (!live && detailsTimer) { clearInterval(detailsTimer); detailsTimer = null; }
    } catch (e) {
        // best-effort live refresh
    }
}

function showJobDetails(jobId) {
    if (!detailsPane) {
        const pane = document.createElement('div');
        pane.className = 'job-details-pane';
        pane.innerHTML = `
            <div class="job-details-header">
                <h3>Job details <span class="job-details-live" style="display:none;color:#10b981;font-size:12px">● live</span></h3>
                <button type="button" class="btn btn-secondary job-details-close">Close</button>
            </div>
            <div class="job-details-body"></div>
            <div class="job-details-footer">
                <button type="button" class="btn btn-secondary job-details-copy">Copy logs</button>
            </div>
        `;
        pane.querySelector('.job-details-close').addEventListener('click', closeJobDetails);
        pane.querySelector('.job-details-copy').addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(detailsPlainText);
                const copy = pane.querySelector('.job-details-copy');
                if (copy) { copy.textContent = 'Copied'; setTimeout(() => copy.textContent = 'Copy logs', 1200); }
            } catch (e) {}
        });
        document.getElementById('jobsList').parentElement.appendChild(pane);
        detailsPane = pane;
    }
    detailsJobId = jobId;
    renderJobDetails(currentJobs.find(j => j.id === jobId) || { id: jobId, status: 'pending' });
    if (detailsTimer) clearInterval(detailsTimer);
    detailsTimer = setInterval(refreshJobDetails, 1500);
    detailsPane.style.display = 'flex';
}

async function loadJobs() {
    try {
        const res = await fetch('/api/jobs?limit=100');
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
        renderJobs(data.jobs || []);
    } catch (error) {
        const list = document.getElementById('jobsList');
        if (list) list.textContent = `Could not load jobs: ${error.message}`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const refresh = document.getElementById('refreshJobs');
    if (refresh) refresh.addEventListener('click', loadJobs);
    const toggle = document.getElementById('autoRefreshJobs');
    if (toggle) {
        toggle.checked = true;
        toggle.addEventListener('change', () => {
            if (jobsAutoRefresh) clearInterval(jobsAutoRefresh);
            jobsAutoRefresh = toggle.checked ? setInterval(loadJobs, 5000) : null;
        });
    }
    loadJobs();
    jobsAutoRefresh = setInterval(loadJobs, 5000);

    const list = document.getElementById('jobsList');
    if (list) {
        const clear = document.createElement('button');
        clear.type = 'button';
        clear.className = 'btn btn-secondary';
        clear.textContent = 'Clear finished jobs';
        clear.style.marginTop = '8px';
        clear.addEventListener('click', async () => {
            try {
                const res = await fetch('/api/jobs/clear-finished', { method: 'POST' });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                showNotification(`Cleared ${data.removed} jobs`, 'success');
                loadJobs();
            } catch (error) {
                showNotification(`Clear failed: ${error.message}`, 'error');
            }
        });
        list.parentElement.insertBefore(clear, list.nextSibling);
    }
});
