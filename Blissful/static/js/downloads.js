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
    actionHead.textContent = '';
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
        const progress = job.progress || {};
        const parts = [];
        if (progress.phase) parts.push(progress.phase);
        if (progress.album_title) parts.push(progress.album_title);
        if (progress.processed !== undefined && progress.total) {
            parts.push(`${progress.processed}/${progress.total}`);
        }
        if (progress.command_status) parts.push(`Lidarr: ${progress.command_status}`);
        if (job.failure_reason) parts.push(job.failure_reason);
        if (result.successful !== undefined) parts.push(`${result.successful} imported`);
        if (result.failed) parts.push(`${result.failed} failed`);
        if (result.total_tracks) parts.push(`${result.total_tracks} total`);
        if (result.command) parts.push(`command ${result.command}`);
        if (result.blissful_fallback) parts.push(`${result.blissful_fallback} Blissful fallback`);
        const failures = result.failures || [];
        if (failures.length) {
            parts.push(failures.slice(0, 3).map(f =>
                `${f.title || 'track'}: ${f.error || 'no reason'}`).join('; '));
            detail.title = failures.map(f =>
                `${f.title || 'track'}: ${f.error || 'no reason'}`).join('\n');
        }
        detail.textContent = parts.join(' · ').slice(0, 500);
        row.appendChild(detail);

        const actions = document.createElement('td');
        if (job.status === 'failed') {
            const retry = document.createElement('button');
            retry.type = 'button';
            retry.className = 'btn btn-secondary';
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
        row.appendChild(actions);
        body.appendChild(row);
    });
    table.appendChild(body);
    list.appendChild(table);
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
});
