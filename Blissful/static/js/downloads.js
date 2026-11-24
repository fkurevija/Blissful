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
        const hasDetail = Boolean(
            job.failure_reason || failures.length ||
            result.successful !== undefined || result.failed ||
            result.total_tracks || progress.phase || progress.album_title
        );
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-secondary job-action job-details';
        btn.textContent = hasDetail ? 'Details' : '—';
        btn.disabled = !hasDetail;
        btn.dataset.jobId = job.id;
        btn.addEventListener('click', () => {
            if (hasDetail) showJobDetails(job);
        });
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

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showJobDetails(job) {
    if (!detailsPane) {
        const pane = document.createElement('div');
        pane.className = 'job-details-pane';
        pane.innerHTML = `
            <div class="job-details-header">
                <h3>Job details</h3>
                <button type="button" class="btn btn-secondary job-details-close">Close</button>
            </div>
            <div class="job-details-body"></div>
        `;
        pane.querySelector('.job-details-close').addEventListener('click', () => {
            pane.style.display = 'none';
        });
        document.getElementById('jobsList').parentElement.appendChild(pane);
        detailsPane = pane;
    }
    const body = detailsPane.querySelector('.job-details-body');
    const result = job.result || {};
    const failures = result.failures || [];
    const progress = job.progress || {};
    const lines = [];
    lines.push(`<strong>Job:</strong> ${escapeHtml(jobLabel(job))}`);
    lines.push(`<strong>Status:</strong> ${escapeHtml(job.status)}`);
    lines.push(`<strong>Source:</strong> ${escapeHtml(job.source || '')}`);
    lines.push(`<strong>Updated:</strong> ${escapeHtml(job.updated_at || '')}`);
    if (job.failure_reason) lines.push(`<strong>Failure reason:</strong> ${escapeHtml(job.failure_reason)}`);
    if (progress.phase) lines.push(`<strong>Phase:</strong> ${escapeHtml(progress.phase)}`);
    if (progress.album_title) lines.push(`<strong>Album:</strong> ${escapeHtml(progress.album_title)}`);
    if (progress.processed !== undefined && progress.total) {
        lines.push(`<strong>Progress:</strong> ${progress.processed}/${progress.total}`);
    }
    if (progress.command_status) lines.push(`<strong>Lidarr:</strong> ${escapeHtml(progress.command_status)}`);
    if (result.successful !== undefined) lines.push(`<strong>Imported:</strong> ${result.successful}`);
    if (result.failed !== undefined) lines.push(`<strong>Failed:</strong> ${result.failed}`);
    if (result.total_tracks !== undefined) lines.push(`<strong>Total tracks:</strong> ${result.total_tracks}`);
    if (result.command !== undefined) lines.push(`<strong>Command:</strong> ${result.command}`);
    if (result.blissful_fallback !== undefined) lines.push(`<strong>Blissful fallback:</strong> ${result.blissful_fallback}`);
    if (failures.length) {
        lines.push(`<strong>Per-track failures (${failures.length}):</strong>`);
        lines.push('<ul style="margin:6px 0 0 1.2em; padding:0">');
        failures.forEach(f => {
            const attempts = Array.isArray(f.attempts) ? f.attempts.map(a => escapeHtml(a.source + ': ' + (a.error || a.message))).join('<br>') : '';
            lines.push(`<li><strong>${escapeHtml(f.title || 'track')}</strong>: ${escapeHtml(f.error || '')}`);
            if (attempts) lines.push(`<div style="margin-top:2px; font-size:12px; color:var(--muted-foreground)">${attempts}</div>`);
            lines.push('</li>');
        });
        lines.push('</ul>');
    }
    body.innerHTML = lines.join('<br>') || '<em>No details recorded.</em>';
    detailsPane.style.display = 'block';
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
