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

async function retryJobTrack(jobId, title) {
    try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/retry-track`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ title })
        });
        const data = await res.json();
        if (!res.ok || !data.success) throw new Error(data.error || `HTTP ${res.status}`);
        showNotification(`Retrying ${title}`, 'success');
        await loadJobs();
    } catch (error) {
        showNotification(`Retry failed: ${error.message}`, 'error');
    }
}
window.retryJobTrack = retryJobTrack;

function renderFailedTracks(jobs) {
    const list = document.getElementById('failedTracksList');
    if (!list) return;
    list.innerHTML = '';
    const rows = [];
    (jobs || []).forEach(job => {
        if (job.status === 'succeeded') return;
        const failures = (job.result || {}).failures || [];
        failures.forEach(track => rows.push({ job, track }));
    });
    if (!rows.length) {
        list.innerHTML = '<em>No failed tracks.</em>';
        return;
    }
    rows.forEach(({ job, track }) => {
        const title = track.title || 'track';
        const row = document.createElement('div');
        row.className = 'failed-track-row';
        const info = document.createElement('div');
        info.className = 'failed-track-info';
        info.textContent = `${jobLabel(job)} — ${title}`;
        const error = document.createElement('div');
        error.className = 'failed-track-error';
        error.textContent = String(track.error || '').slice(0, 180);
        info.appendChild(error);
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm';
        button.textContent = 'Retry track';
        button.addEventListener('click', () => retryJobTrack(job.id, title));
        row.appendChild(info);
        row.appendChild(button);
        list.appendChild(row);
    });
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
    renderFailedTracks(currentJobs);
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
        ['updated', 'Updated']
    ];
    columns.forEach(([key, label]) => {
        const th = document.createElement('th');
        th.dataset.sortKey = key;
        const arrow = jobsSort.key === key ? (jobsSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
        th.textContent = label ? label + arrow : '';
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
        if (job.status === 'pending' && job.next_attempt_at) {
            const wait = Math.max(0, Math.ceil(job.next_attempt_at - Date.now() / 1000));
            status.textContent += ` · retry ${wait}s`;
        }
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

        // Fixed three-slot grid: Details | Delete | Retry/Cancel.
        // Unavailable actions are omitted, leaving an aligned blank column.
        const actions = document.createElement('td');
        actions.className = 'job-actions';
        const makeAction = (text, extraClass, handler, column) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'btn btn-secondary job-action' + (extraClass ? ' ' + extraClass : '');
            button.textContent = text;
            button.style.gridColumn = String(column);
            button.addEventListener('click', handler);
            actions.appendChild(button);
            return button;
        };

        const detailsBtn = makeAction('Details', 'job-details',
            () => showJobDetails(job.id), 1);
        detailsBtn.dataset.jobId = job.id;

        if (job.status !== 'pending' && job.status !== 'running') {
            makeAction('Delete', '', async () => {
                try {
                    const res = await fetch(`/api/jobs/${job.id}`, { method: 'DELETE' });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                    loadJobs();
                } catch (error) {
                    showNotification(`Delete failed: ${error.message}`, 'error');
                }
            }, 2);
        }

        if (job.status === 'failed' || job.status === 'cancelled') {
            makeAction('Retry', '', async () => {
                try {
                    const res = await fetch(`/api/jobs/${job.id}/retry`, { method: 'POST' });
                    const data = await res.json();
                    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
                    loadJobs();
                } catch (error) {
                    showNotification(`Retry failed: ${error.message}`, 'error');
                }
            }, 3);
        } else if (job.status === 'pending' || job.status === 'running') {
            makeAction('Cancel', '', async () => {
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
            }, 3);
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
let detailsMarkdown = '';
let detailsFilter = { text: '', failuresOnly: false };
let detailsOpenSet = new Set();  // indices of expanded Download Attempts sections

function escapeHtml(text) {
    if (text == null) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function relativeTime(iso) {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (isNaN(t)) return String(iso);
    const diff = Math.max(0, Date.now() - t);
    const s = Math.floor(diff / 1000);
    if (s < 5) return 'just now';
    if (s < 60) return s + 's ago';
    const m = Math.floor(s / 60);
    if (m < 60) return m + 'm ago';
    const h = Math.floor(m / 60);
    if (h < 24) return h + 'h ago';
    return Math.floor(h / 24) + 'd ago';
}

function durationBetween(startIso, endIso) {
    if (!startIso || !endIso) return '';
    const a = Date.parse(startIso), b = Date.parse(endIso);
    if (isNaN(a) || isNaN(b) || b < a) return '';
    const secs = Math.floor((b - a) / 1000);
    if (secs < 60) return secs + 's';
    const m = Math.floor(secs / 60);
    if (m < 60) return m + 'm ' + (secs % 60) + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
}

function copyText(text, button) {
    const mark = () => {
        if (button) {
            const original = button.dataset.originalLabel || button.textContent;
            button.dataset.originalLabel = original;
            button.textContent = 'Copied';
            setTimeout(() => { button.textContent = original; }, 1200);
        }
    };
    if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(mark).catch(() => fallbackCopy(text, mark, button));
    } else {
        fallbackCopy(text, mark, button);
    }
}

function fallbackCopy(text, mark, button) {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0';
    document.body.appendChild(ta);
    ta.focus(); ta.select(); ta.setSelectionRange(0, ta.value.length);
    try {
        if (document.execCommand('copy')) mark();
        else if (button) {
            const original = button.dataset.originalLabel || button.textContent;
            button.dataset.originalLabel = original;
            button.textContent = 'Select + Ctrl+C';
            setTimeout(() => { button.textContent = original; }, 1800);
        }
    } catch (e) {}
    document.body.removeChild(ta);
}

function closeJobDetails() {
    if (detailsTimer) { clearInterval(detailsTimer); detailsTimer = null; }
    detailsJobId = null;
    if (detailsPane) detailsPane.style.display = 'none';
}

function providerOf(source) {
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
}

function friendlySource(source) {
    const s = String(source || '');
    const label = providerOf(s);
    const query = s.replace(/^(ytsearch\d*|scsearch\d*|dzsearch\d*|bandcamp):/i, '').trim();
    return query ? label + ': ' + query : label;
}

function statusClass(status) {
    const s = String(status || '').toLowerCase();
    if (s === 'rejected' || s === 'failed' || s === 'error') return 'log-status-bad';
    if (s === 'success' || s === 'succeeded' || s === 'downloaded') return 'log-status-good';
    return 'log-status-info';
}

function renderJobDetails(job) {
    if (!detailsPane || !job) return;
    const body = detailsPane.querySelector('.job-details-body');
    const result = job.result || {};
    const failures = Array.isArray(result.failures) ? result.failures : [];
    const progress = job.progress || {};
    const log = Array.isArray(job.log) ? job.log : [];
    const isLive = job.status === 'pending' || job.status === 'running';

    // ---- Summary bar: progress, elapsed time, attempt summary, stuck warning ----
    let summary = detailsPane.querySelector('.job-details-summary');
    if (!summary) {
        summary = document.createElement('div');
        summary.className = 'job-details-summary';
        detailsPane.insertBefore(summary, body);
    }
    summary.innerHTML = '';
    const cur = progress.completed_tracks ?? progress.current_track
        ?? result.completed_tracks ?? result.successful ?? 0;
    const tot = progress.total_tracks ?? result.total_tracks ?? 0;
    if (tot > 0) {
        const bar = document.createElement('div');
        bar.className = 'job-progress';
        const fill = document.createElement('div');
        fill.className = 'job-progress-fill';
        fill.style.width = Math.min(100, Math.round((cur / tot) * 100)) + '%';
        bar.appendChild(fill);
        summary.appendChild(bar);
        const label = document.createElement('span');
        label.className = 'job-progress-label';
        label.textContent = `${cur}/${tot} tracks`;
        summary.appendChild(label);
    }
    const elapsed = job.started_at
        ? durationBetween(job.started_at, job.finished_at || (isLive ? new Date().toISOString() : job.updated_at))
        : durationBetween(job.created_at, job.finished_at || (isLive ? new Date().toISOString() : job.updated_at));
    if (elapsed) {
        const el = document.createElement('span');
        el.className = 'job-elapsed';
        el.textContent = '⏱ ' + elapsed;
        summary.appendChild(el);
    }
    // Attempt summary derived from log entries
    const providers = new Set();
    let ok = 0, bad = 0;
    log.forEach(item => {
        if (!item || typeof item !== 'object') return;
        (item.attempts || []).forEach(a => {
            providers.add(providerOf(a.source));
            if ((a.status || '').toLowerCase() === 'success') ok++; else bad++;
        });
    });
    if (providers.size || ok || bad) {
        const s = document.createElement('span');
        s.className = 'job-attempt-summary';
        const bits = [];
        bits.push(`${providers.size} source${providers.size === 1 ? '' : 's'} tried`);
        if (ok) bits.push(`${ok} success`);
        if (bad) bits.push(`${bad} failed/rejected`);
        s.textContent = bits.join(' · ');
        summary.appendChild(s);
    }
    // Stuck warning: running with no update for ~5 minutes
    if (isLive && job.updated_at && (Date.now() - Date.parse(job.updated_at)) > 5 * 60 * 1000) {
        const warn = document.createElement('div');
        warn.className = 'job-stuck-warning';
        warn.textContent = '⚠ No progress for over 5 minutes — this job may be stuck.';
        summary.appendChild(warn);
    }

    // ---- Job info fields ----
    const fields = [];
    const add = (label, value) => {
        if (value !== undefined && value !== null && value !== '') fields.push({ label, text: String(value) });
    };
    add('Job', jobLabel(job));
    add('Status', job.status);
    if (job.parent_id) {
        add('Part of', 'Parent job ' + job.parent_id);
    } else if (job.child_count) {
        add('Includes', `${job.child_count} import job${job.child_count === 1 ? '' : 's'}`);
    }
    add('Source', job.source || '');
    add('Updated', relativeTime(job.updated_at));
    if (job.created_at) add('Created', relativeTime(job.created_at));
    if (job.finished_at) add('Duration', durationBetween(job.started_at || job.created_at, job.finished_at));
    add('Failure reason', job.failure_reason || '');
    add('Phase', progress.phase || '');
    add('Album', progress.album_title || '');
    if (progress.processed !== undefined && progress.total) add('Progress', `${progress.processed}/${progress.total}`);
    if (cur && tot) add('Track', `${cur}/${tot}`);
    add('Lidarr', progress.command_status || '');
    if (result.completed_tracks !== undefined) {
        add('Completed', `${result.completed_tracks}/${result.total_tracks ?? '?'}`);
    }
    if (result.rounds) add('Retry rounds', result.rounds);
    if (result.successful !== undefined) add('Imported', result.successful);
    if (result.failed !== undefined) add('Failed', result.failed);
    if (result.total_tracks !== undefined) add('Total tracks', result.total_tracks);

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
        if (failures.length) {
            const head = document.createElement('div');
            head.className = 'job-detail-line job-detail-heading';
            head.textContent = `Per-track failures (${failures.length}):`;
            body.appendChild(head);
            failures.forEach(f => {
                const attempts = Array.isArray(f.attempts)
                    ? f.attempts.map(a => `${a.source || ''}: ${a.error || a.message || ''}`)
                    : [];
                const line = document.createElement('div');
                line.className = 'job-detail-line';
                line.textContent = `  - ${f.title || 'track'}: ${f.error || ''}`;
                const retry = document.createElement('button');
                retry.type = 'button';
                retry.className = 'btn btn-sm';
                retry.textContent = 'Retry track';
                retry.addEventListener('click', () => retryJobTrack(job.id, f.title || 'track'));
                line.appendChild(retry);
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

    // ---- Log pane ----
    let logWrap = detailsPane.querySelector('.job-details-log-wrap');
    if (!logWrap) {
        logWrap = document.createElement('div');
        logWrap.className = 'job-details-log-wrap';
        const label = document.createElement('div');
        label.className = 'job-detail-heading';
        label.textContent = 'Live log:';
        logWrap.appendChild(label);
        const controls = document.createElement('div');
        controls.className = 'log-filter-controls';
        const text = document.createElement('input');
        text.type = 'text';
        text.placeholder = 'Filter log…';
        text.className = 'log-filter-text';
        text.addEventListener('input', () => {
            detailsFilter.text = text.value.toLowerCase();
            renderLogEntries();
        });
        const cb = document.createElement('label');
        cb.className = 'log-filter-check';
        const cbInput = document.createElement('input');
        cbInput.type = 'checkbox';
        cbInput.addEventListener('change', () => {
            detailsFilter.failuresOnly = cbInput.checked;
            renderLogEntries();
        });
        cb.appendChild(cbInput);
        cb.appendChild(document.createTextNode(' attempts/failures only'));
        controls.appendChild(text);
        controls.appendChild(cb);
        logWrap.appendChild(controls);
        const pane = document.createElement('div');
        pane.className = 'job-details-log';
        logWrap.appendChild(pane);
        detailsPane.insertBefore(logWrap, detailsPane.querySelector('.job-details-footer'));
        detailsPane._logPane = pane;
    }
    const logPane = detailsPane._logPane;
    const wasAtBottom = !logPane.dataset.init ||
        (logPane.scrollHeight - logPane.scrollTop - logPane.clientHeight) < 24;

    const textRow = text => {
        const span = document.createElement('span');
        span.textContent = text;
        return span;
    };
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
    const meta = parts => {
        const frag = document.createDocumentFragment();
        frag.appendChild(textRow(' ('));
        parts.forEach((part, i) => {
            if (i) frag.appendChild(textRow(' , '));
            frag.appendChild(typeof part === 'string' ? chip(part) : textRow(part.text || ''));
        });
        frag.appendChild(textRow(' )'));
        return frag;
    };

    function entryMatchesFilter(item) {
        if (detailsFilter.failuresOnly) {
            const hasAttempts = item && typeof item === 'object' && Array.isArray(item.attempts) && item.attempts.length;
            const isFailure = item && typeof item === 'object' &&
                /fail|reject|error/i.test(String(item.phase || '') + ' ' + String(item.failure_reason || ''));
            if (!hasAttempts && !isFailure) return false;
        }
        if (!detailsFilter.text) return true;
        return String(JSON.stringify(item)).toLowerCase().includes(detailsFilter.text);
    }

    function buildEntry(item, renderedIdx) {
        const entry = document.createElement('div');
        entry.className = 'job-log-entry';
        if (!item || typeof item !== 'object') {
            entry.textContent = String(item);
            return entry;
        }
        const header = document.createElement('div');
        header.className = 'log-snapshot-title';
        header.appendChild(textRow('Job Snapshot '));
        header.appendChild(chip(item.ts || ''));
        const copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'job-log-entry-copy';
        copyBtn.textContent = 'Copy';
        copyBtn.title = 'Copy this log entry';
        copyBtn.addEventListener('click', e => {
            e.stopPropagation();
            copyText(entry.dataset.plain || '', copyBtn);
        });
        header.appendChild(copyBtn);
        entry.appendChild(header);

        const statusParts = [];
        if (item.job_status) statusParts.push('job_status=' + item.job_status);
        if (item.download_status) statusParts.push('download_status=' + item.download_status);
        if (item.download_pending !== undefined) statusParts.push('download_pending=' + item.download_pending);
        if (item.completed !== undefined && item.total !== undefined) {
            statusParts.push(`tracks=${item.completed}/${item.total}`);
        }
        if (item.rounds !== undefined) statusParts.push('round=' + item.rounds);
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
                albumParts.push({ text: `album_index=${item.album_index} of ${total}` });
            }
            if (albumParts.length) frag.appendChild(meta(albumParts));
            entry.appendChild(bullet(frag));
        }
        if (item.download_track) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Track: '));
            frag.appendChild(textRow(String(item.download_track)));
            if (item.current_track !== undefined) {
                const total = item.total_tracks !== undefined ? item.total_tracks : '?';
                frag.appendChild(meta([{ text: `current_track=${item.current_track} of ${total}` }]));
            }
            entry.appendChild(bullet(frag));
        }
        if (item.download_source) {
            const frag = document.createDocumentFragment();
            frag.appendChild(textRow('Current Source:'));
            frag.appendChild(document.createElement('br'));
            frag.appendChild(chip(friendlySource(item.download_source)));
            entry.appendChild(bullet(frag));
        }
        const attempts = Array.isArray(item.download_attempts) ? item.download_attempts : Array.isArray(item.attempts) ? item.attempts : [];
        if (attempts.length) {
            const heading = document.createElement('div');
            heading.className = 'log-section-title';
            heading.textContent = 'Download Attempts';
            entry.appendChild(heading);
            const details = document.createElement('details');
            details.className = 'log-attempts';
            const summary = document.createElement('summary');
            summary.textContent = `${attempts.length} attempt${attempts.length === 1 ? '' : 's'} — click to expand`;
            details.appendChild(summary);
            attempts.forEach(a => {
                const frag = document.createDocumentFragment();
                frag.appendChild(textRow(providerOf(a.source) + ' ('));
                frag.appendChild(chip(friendlySource(a.source)));
                frag.appendChild(textRow('): '));
                const st = document.createElement('span');
                st.className = statusClass(a.status);
                st.textContent = String(a.status || '');
                frag.appendChild(st);
                frag.appendChild(textRow(' — '));
                frag.appendChild(textRow(String(a.reason || a.error || '')));
                details.appendChild(bullet(frag));
            });
            entry.appendChild(details);
            details.dataset.idx = renderedIdx;
            if (detailsOpenSet.has(renderedIdx)) details.open = true;
            summary.addEventListener('click', () => {
                if (details.open) detailsOpenSet.delete(renderedIdx);
                else detailsOpenSet.add(renderedIdx);
            });
        }
        entry.dataset.plain = entryPlainText(item);
        return entry;
    }

    function entryPlainText(item) {
        if (!item || typeof item !== 'object') return String(item);
        const lines = [`Job Snapshot ( ${item.ts || ''} )`];
        const status = [];
        if (item.job_status) status.push('job_status=' + item.job_status);
        if (item.download_status) status.push('download_status=' + item.download_status);
        if (item.download_pending !== undefined) status.push('download_pending=' + item.download_pending);
        if (item.completed !== undefined && item.total !== undefined) {
            status.push(`tracks=${item.completed}/${item.total}`);
        }
        if (item.rounds !== undefined) status.push('round=' + item.rounds);
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
        const attempts = Array.isArray(item.download_attempts) ? item.download_attempts : Array.isArray(item.attempts) ? item.attempts : [];
        if (attempts.length) {
            lines.push('', 'Download Attempts', '');
            attempts.forEach(a => {
                lines.push(`○ ${providerOf(a.source)} ( ${friendlySource(a.source)} ): ${a.status || ''} — ${a.reason || a.error || ''}`);
            });
        }
        return lines.join('\n');
    }

    function renderLogEntries() {
        logPane.innerHTML = '';
        let shown = 0;
        let renderedIdx = 0;
        log.forEach(item => {
            if (!entryMatchesFilter(item)) return;
            logPane.appendChild(buildEntry(item, renderedIdx));
            renderedIdx++;
            shown++;
        });
        // Re-apply persisted open/collapsed state so expanding one section
        // does not get reset when new log entries arrive on the next poll.
        detailsOpenSet.forEach(idx => {
            const el = logPane.children[idx];
            if (el && el.querySelector('.log-attempts'))
                el.querySelector('.log-attempts').open = true;
        });
        if (!shown) logPane.textContent = log.length ? '(no entries match the filter)' : '(waiting for log entries…)';
        logPane.dataset.init = '1';
        if (wasAtBottom) logPane.scrollTop = logPane.scrollHeight;
    }

    renderLogEntries();
    detailsPlainText = log.map(item => entryPlainText(item)).join('\n\n');
    detailsMarkdown = '# Job: ' + jobLabel(job) + '\n\n' +
        '- Status: ' + (job.status || '') + '\n' +
        '- Source: ' + (job.source || '') + '\n' +
        (job.failure_reason ? '- Failure: ' + job.failure_reason + '\n' : '') +
        '\n## Log\n\n```\n' + detailsPlainText + '\n```';
    const badge = detailsPane.querySelector('.job-details-live');
    if (badge) badge.style.display = isLive ? 'inline' : 'none';
}

async function refreshJobDetails() {
    if (!detailsJobId) return;
    const sel = window.getSelection();
    if (sel && sel.toString() && detailsPane && detailsPane.contains(sel.anchorNode)) return;
    try {
        const res = await fetch('/api/jobs?limit=500');
        const data = await res.json();
        const job = (data.jobs || []).find(j => j.id === detailsJobId);
        if (job) renderJobDetails(job);
        const live = job && (job.status === 'pending' || job.status === 'running');
        if (!live && detailsTimer) { clearInterval(detailsTimer); detailsTimer = null; }
    } catch (e) {}
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
            <div class="job-details-summary"></div>
            <div class="job-details-body"></div>
            <div class="job-details-footer">
                <button type="button" class="btn btn-secondary job-details-copy-md">Copy Markdown</button>
                <button type="button" class="btn btn-secondary job-details-jump">Jump to last</button>
                <button type="button" class="btn btn-secondary job-details-copy">Copy logs</button>
            </div>
        `;
        pane.querySelector('.job-details-close').addEventListener('click', closeJobDetails);
        pane.querySelector('.job-details-copy').addEventListener('click', e => copyText(detailsPlainText, e.currentTarget));
        pane.querySelector('.job-details-copy-md').addEventListener('click', e => copyText(detailsMarkdown, e.currentTarget));
        pane.querySelector('.job-details-jump').addEventListener('click', () => {
            const log = detailsPane.querySelector('.job-details-log');
            if (log) { log.scrollTop = log.scrollHeight; log.dataset.init = '1'; }
        });
        document.getElementById('jobsList').parentElement.appendChild(pane);
        detailsPane = pane;
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && detailsPane && detailsPane.style.display === 'flex') closeJobDetails();
        });
    }
    detailsJobId = jobId;
    renderJobDetails(currentJobs.find(j => j.id === jobId) || { id: jobId, status: 'pending' });
    if (detailsTimer) clearInterval(detailsTimer);
    detailsTimer = setInterval(refreshJobDetails, 1500);
    detailsPane.style.display = 'flex';
}

// Called by the progress toast's "View details" link.
async function openLatestJobDetails() {
    try {
        const res = await fetch('/api/jobs?limit=50');
        const data = await res.json();
        const jobs = (data.jobs || []).filter(j => ['search', 'cleanup'].includes(j.kind));
        if (jobs.length) showJobDetails(jobs[0].id);
        else showDownloadsTab();
    } catch (e) {
        showDownloadsTab();
    }
}
window.openLatestJobDetails = openLatestJobDetails;

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
