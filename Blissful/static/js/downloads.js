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
    const chip = text => {
        const span = document.createElement('span');
        span.className = 'log-chip';
        span.textContent = String(text);
        return span;
    };
    const bullet = content => {
        const row = document.createElement('div');
        row.className = 'log-bullet';
        const mark = document.createElement('span');
        mark.className = 'log-bullet-mark';
        mark.textContent = '○';
        const body = document.createElement('span');
        body.className = 'log-bullet-body';
        body.appendChild(content);
        row.appendChild(mark);
        row.appendChild(body);
        return row;
    };
    const textRow = text => {
        const span = document.createElement('span');
        span.textContent = text;
        return span;
    };
    const meta = (parts) => {
        const frag = document.createDocumentFragment();
        frag.appendChild(textRow(' ('));
        parts.forEach((part, i) => {
            if (i) frag.appendChild(textRow(' , '));
            if (typeof part === 'string') {
                frag.appendChild(chip(part));
            } else {
                frag.appendChild(textRow(part.text || ''));
            }
        });
        frag.appendChild(textRow(' )'));
        return frag;
    };
    const friendlySource = source => {
        const s = String(source || '');
        const lower = s.toLowerCase();
        let label = 'Source';
        if (lower.includes('site:music.youtube.com')) label = 'YouTube Music';
        else if (lower.startsWith('ytsearch') || lower.includes('youtube')) label = 'YouTube';
        else if (lower.startsWith('scsearch') || lower.includes('soundcloud')) label = 'SoundCloud';
        else if (lower.startsWith('bandcamp') || lower.includes('bandcamp')) label = 'Bandcamp';
        else if (lower.startsWith('dzsearch') || lower.includes('deezer')) label = 'Deezer';
        else if (lower.includes('apple')) label = 'Apple Music';
        else if (lower.includes('mixcloud')) label = 'Mixcloud';
        else if (lower.includes('archive.org')) label = 'Archive.org';
        else if (lower.includes('tidal')) label = 'Tidal';
        const query = s.replace(/^(ytsearch\d*|scsearch\d*|dzsearch\d*|bandcamp):/i, '').trim();
        return query ? label + ': ' + query : label;
    };
    const provider = source => {
        const s = String(source || '').toLowerCase();
        if (s.includes('site:music.youtube.com')) return 'YouTube Music';
        if (s.startsWith('ytsearch') || s.includes('youtube')) return 'YouTube';
        if (s.startsWith('scsearch') || s.includes('soundcloud')) return 'SoundCloud';
        if (s.startsWith('bandcamp') || s.includes('bandcamp')) return 'Bandcamp';
        if (s.startsWith('dzsearch') || s.includes('deezer')) return 'Deezer';
        if (s.includes('apple')) return 'Apple Music';
        if (s.includes('mixcloud')) return 'Mixcloud';
        if (s.includes('archive.org')) return 'Archive.org';
        if (s.includes('tidal')) return 'Tidal';
        return 'Source';
    };
    log.forEach(item => {
        const entry = document.createElement('div');
        entry.className = 'job-log-entry';
        if (typeof item !== 'object' || item === null) {
            entry.textContent = String(item);
            logPane.appendChild(entry);
            return;
        }
        const header = document.createElement('div');
        header.className = 'log-snapshot-title';
        header.appendChild(textRow('Job Snapshot '));
        header.appendChild(chip(item.ts || ''));
        entry.appendChild(header);

        // Phase / Status with parenthetical status metadata.
        const statusParts = [];
        if (item.job_status) statusParts.push('job_status=' + item.job_status);
        if (item.download_status) statusParts.push('download_status=' + item.download_status);
        if (item.download_pending !== undefined) statusParts.push('download_pending=' + item.download_pending);
        if (item.phase || statusParts.length) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Phase / Status: '));
            frag.appendChild(textRow(String(item.phase || '')));
            if (statusParts.length) frag.appendChild(meta(statusParts));
            entry.appendChild(bullet(frag));
        }
        if (item.download_artist) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Artist: '));
            frag.appendChild(textRow(String(item.download_artist)));
            entry.appendChild(bullet(frag));
        }
        if (item.album_title) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Album: '));
            frag.appendChild(textRow(String(item.album_title)));
            const albumParts = [];
            if (item.album_id !== undefined) albumParts.push('album_id=' + item.album_id);
            if (item.album_index !== undefined) {
                const total = item.total_albums !== undefined ? item.total_albums : '?';
                albumParts.push({ text: 'album_index=' + item.album_index + ' of ' + total });
            }
            if (albumParts.length) frag.appendChild(meta(albumParts));
            entry.appendChild(bullet(frag));
        }
        if (item.download_track) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Track: '));
            frag.appendChild(textRow(String(item.download_track)));
            const trackParts = [];
            if (item.current_track !== undefined) {
                const total = item.total_tracks !== undefined ? item.total_tracks : '?';
                trackParts.push({ text: 'current_track=' + item.current_track + ' of ' + total });
            }
            if (trackParts.length) frag.appendChild(meta(trackParts));
            entry.appendChild(bullet(frag));
        }
        if (item.download_source) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Current Source:'));
            frag.appendChild(document.createElement('br'));
            frag.appendChild(chip(friendlySource(item.download_source)));
            entry.appendChild(bullet(frag));
        }
        const attempts = Array.isArray(item.attempts) ? item.attempts : [];
        if (attempts.length) {
            const heading = document.createElement('div');
            heading.className = 'log-section-title';
            heading.textContent = 'Download Attempts';
            entry.appendChild(heading);
            attempts.forEach(attempt => {
                const frag = document.createDocumentFragment();
                const src = attempt.source || '';
                frag.appendChild(textRow(provider(src) + ' ('));
                frag.appendChild(chip(friendlySource(src)));
                frag.appendChild(textRow('): '));
                frag.appendChild(textRow(String(attempt.status || '')));
                frag.appendChild(textRow(' — '));
                frag.appendChild(textRow(String(attempt.reason || attempt.error || '')));
                entry.appendChild(bullet(frag));
            });
        }
        logPane.appendChild(entry);
    });
    if (!log.length) {
        logPane.textContent = '(waiting for log entries…)';
    }
    logPane.dataset.init = '1';
    // Only autoscroll when the user was already at the bottom (or on the
    // first render). If they scrolled up to read older entries, leave
    // their scroll position alone until they scroll back down.
    if (wasAtBottom) logPane.scrollTop = logPane.scrollHeight;
    // Keep the plain log text for the Copy logs button.
    detailsPlainText = log.map(item => {
        if (typeof item !== 'object' || item === null) return String(item);
        const lines = [`Job Snapshot ( ${item.ts || ''} )`];
        const status = [];
        if (item.job_status) status.push('job_status=' + item.job_status);
        if (item.download_status) status.push('download_status=' + item.download_status);
        if (item.download_pending !== undefined) status.push('download_pending=' + item.download_pending);
        lines.push(`○ Phase / Status: ${item.phase || ''}${status.length ? ' ( ' + status.join(' , ') + ' )' : ''}`);
        if (item.download_artist) lines.push(`○ Artist: ${item.download_artist}`);
        if (item.album_title) {
            let line = `○ Album: ${item.album_title}`;
            if (item.album_id !== undefined) line += ` ( album_id=${item.album_id}`;
            if (item.album_index !== undefined) line += ` , album_index=${item.album_index} of ${item.total_albums}`;
            if (item.album_id !== undefined) line += ' )';
            lines.push(line);
        }
        if (item.download_track) {
            let line = `○ Track: ${item.download_track}`;
            if (item.current_track !== undefined) line += ` ( current_track=${item.current_track} of ${item.total_tracks} )`;
            lines.push(line);
        }
        if (item.download_source) lines.push(`○ Current Source:\n    ${friendlySource(item.download_source)}`);
        const attempts = Array.isArray(item.attempts) ? item.attempts : [];
        if (attempts.length) {
            lines.push('', 'Download Attempts', '');
            attempts.forEach(a => {
                const src = a.source || '';
                const s = src.toLowerCase();
                let label = 'Source';
                if (s.includes('site:music.youtube.com')) label = 'YouTube Music';
                else if (s.startsWith('ytsearch') || s.includes('youtube')) label = 'YouTube';
                else if (s.startsWith('scsearch') || s.includes('soundcloud')) label = 'SoundCloud';
                else if (s.startsWith('bandcamp') || s.includes('bandcamp')) label = 'Bandcamp';
                lines.push(`○ ${label} ( ${friendlySource(src)} ): ${a.status || ''} — ${a.reason || a.error || ''}`);
            });
        }
        return lines.join('\n');
    }).join('\n\n');
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
            const copy = pane.querySelector('.job-details-copy');
            const markCopied = () => {
                if (copy) { copy.textContent = 'Copied'; setTimeout(() => copy.textContent = 'Copy logs', 1200); }
            };
            // navigator.clipboard needs a secure context (HTTPS/localhost);
            // Blissful is usually plain HTTP, so fall back to execCommand.
            try {
                if (navigator.clipboard && window.isSecureContext) {
                    await navigator.clipboard.writeText(detailsPlainText);
                    markCopied();
                    return;
                }
            } catch (e) {}
            const ta = document.createElement('textarea');
            ta.value = detailsPlainText;
            ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            ta.setSelectionRange(0, ta.value.length);
            try {
                if (document.execCommand('copy')) markCopied();
                else if (copy) { copy.textContent = 'Select + Ctrl+C'; setTimeout(() => copy.textContent = 'Copy logs', 1800); }
            } catch (e) {
                if (copy) { copy.textContent = 'Select + Ctrl+C'; setTimeout(() => copy.textContent = 'Copy logs', 1800); }
            }
            document.body.removeChild(ta);
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
