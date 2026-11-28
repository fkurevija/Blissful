// Wanted search + stale torrent cleanup controls (Blissful tab).
'use strict';

async function wantedApi(url, options = {}) {
    const response = await fetch(url, Object.assign({
        headers: { 'Content-Type': 'application/json' }
    }, options));
    let data;
    try {
        data = await response.json();
    } catch (e) {
        throw new Error(`Invalid response (HTTP ${response.status})`);
    }
    if (!response.ok) {
        const error = new Error(data.error || `HTTP ${response.status}`);
        error.data = data;
        error.status = response.status;
        throw error;
    }
    return data;
}

const WANTED_ACTION_IDS = ['searchSelected', 'searchAll', 'cleanupStale'];

function setWantedButtonHints(runs) {
    const searchBusy = !!(runs && runs.search);
    const cleanupBusy = !!(runs && runs.cleanup);
    WANTED_ACTION_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.disabled = false;
        const isCleanup = id === 'cleanupStale';
        el.title = isCleanup && cleanupBusy
            ? 'A cleanup is already running; this request will be queued'
            : !isCleanup && searchBusy
              ? 'A wanted search is already running; this request will be queued'
              : '';
    });
}

// One shared toast for every wanted run, whether started here, by the
// scheduler, or in another tab. This avoids stacked "started" toasts.
const WANTED_TOAST_ID = 'wanted-toast-active';
let wantedActiveShown = false;

function applyWantedBusy(status) {
    const active = status && status.active;
    setWantedButtonHints(status && status.runs);
    if (active && !wantedActiveShown) {
        wantedActiveShown = true;
        beginWantedProgress(active.kind === 'cleanup'
            ? 'Cleaning stale torrents' : 'Searching wanted albums');
    }
    if (!active) wantedActiveShown = false;
}

async function watchWantedBusy() {
    try {
        const status = await wantedApi('/api/wanted/status');
        applyWantedBusy(status);
    } catch (e) {
        // Status polling is best-effort; never break the page on a transient error.
    }
}

// Sticky progress toasts for long-running wanted/cleanup actions.
const wantedToastState = {};

function wantedToast(id, message, type) {
    let el = document.getElementById(id);
    if (!el) {
        el = document.createElement('div');
        el.id = id;
        el.className = 'wanted-toast';
        el.innerHTML = '<span class="wanted-toast-dot"></span><span class="wanted-toast-text"></span>' +
            '<button type="button" class="wanted-toast-cancel">Cancel</button>' +
            '<button type="button" class="wanted-toast-details" style="display:none">View details →</button>' +
            '<button type="button" class="wanted-toast-link" style="display:none">View downloads →</button>';
        const link = el.querySelector('.wanted-toast-link');
        link.addEventListener('click', () => showDownloadsTab());
        const details = el.querySelector('.wanted-toast-details');
        details.addEventListener('click', () => {
            if (typeof window.openLatestJobDetails === 'function') window.openLatestJobDetails();
            else showDownloadsTab();
        });
        const cancel = el.querySelector('.wanted-toast-cancel');
        cancel.addEventListener('click', async () => {
            try {
                const data = await wantedApi(
                    '/api/wanted/cancel', { method: 'POST', body: '{}' });
                cancel.disabled = true;
                if (data && data.cancelled === false) {
                    // No live run exists; the toast is stale, so close it.
                    finishWantedToast('No active run to cancel', 'info', true);
                    return;
                }
                const text = el.querySelector('.wanted-toast-text');
                if (text) text.textContent = 'Cancelling…';
            } catch (e) {
                cancel.disabled = true;
            }
        });
        el.tabIndex = 0;
        el.title = 'Tap to collapse or expand';
        const isMobile = () => !window.matchMedia
            || window.matchMedia('(max-width: 768px)').matches;
        const toggleCollapsed = () => {
            if (!isMobile()) return;
            el.classList.toggle('wanted-toast-collapsed');
        };
        el.addEventListener('click', event => {
            if (event.target.closest('button')) return;
            toggleCollapsed();
        });
        el.addEventListener('keydown', event => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                toggleCollapsed();
            }
        });
        if (window.matchMedia) {
            const query = window.matchMedia('(max-width: 768px)');
            const expandOnDesktop = change => {
                if (!change.matches) el.classList.remove('wanted-toast-collapsed');
            };
            if (query.addEventListener) query.addEventListener('change', expandOnDesktop);
            else if (query.addListener) query.addListener(expandOnDesktop);
        }
        document.body.appendChild(el);
    }
    el.dataset.type = type || 'info';
    const text = el.querySelector('.wanted-toast-text');
    if (text) text.textContent = message;
    return el;
}

function finishWantedToast(message, type, showLink) {
    const state = wantedToastState[WANTED_TOAST_ID] || { done: false };
    state.done = true;
    wantedActiveShown = false;
    const el = wantedToast(WANTED_TOAST_ID, message, type);
    const link = el.querySelector('.wanted-toast-link');
    if (link) link.style.display = showLink ? 'inline-block' : 'none';
    const details = el.querySelector('.wanted-toast-details');
    if (details) details.style.display = showLink ? 'inline-block' : 'none';
    const cancel = el.querySelector('.wanted-toast-cancel');
    if (cancel) cancel.style.display = 'none';
    setTimeout(() => {
        const el = document.getElementById(WANTED_TOAST_ID);
        if (el) el.remove();
        delete wantedToastState[WANTED_TOAST_ID];
    }, type === 'error' ? 8000 : 5000);
}

async function pollWantedProgress(label) {
    const state = wantedToastState[WANTED_TOAST_ID] || { done: false };
    const started = Date.now();
    let sawActive = false;
    while (!state.done) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        if (state.done) break;
        const elapsed = Math.round((Date.now() - started) / 1000);
        let detail = 'working';
        try {
            const status = await wantedApi('/api/wanted/status');
            const active = status.active;
            if (!active && sawActive) {
                // The run ended (or was cancelled) outside this tab. Close the
                // sticky toast instead of polling stale progress forever.
                state.done = true;
                const last = status.last_activity || {};
                const wasCancelled = last.cancel_requested === true
                    || last.status === 'cancelled';
                finishWantedToast(
                    wasCancelled ? `${label} cancelled` : `${label} finished`,
                    wasCancelled ? 'info' : 'success', true);
                break;
            }
            if (active) sawActive = true;
            if (active && active.kind === 'cleanup') {
                detail = active.phase || 'searching';
                const parts = [];
                if (active.artist) parts.push(active.artist);
                if (active.album_title) {
                    parts.push(`${active.album_title} (#${active.album_id || active.album})`);
                } else if (active.album) {
                    parts.push(`album #${active.album}`);
                }
                if (active.download_track) parts.push(`track: ${active.download_track}`);
                if (active.current_track && active.total_tracks) {
                    parts.push(`progress ${active.current_track}/${active.total_tracks}`);
                }
                if (active.imported !== undefined) parts.push(`imported ${active.imported}`);
                if (active.deleted !== undefined) parts.push(`deleted ${active.deleted}`);
                if (active.kept !== undefined) parts.push(`kept ${active.kept}`);
                if (parts.length) detail += ' · ' + parts.join(', ');
            } else if (active && active.kind === 'search') {
                detail = active.phase || 'searching';
                const parts = [];
                if (active.artist) parts.push(active.artist);
                if (active.album_title) {
                    parts.push(`${active.album_title} (#${active.album_id || active.album})`);
                } else if (active.album) {
                    parts.push(`album #${active.album}`);
                }
                if (active.current_track && active.total_tracks) {
                    parts.push(`track ${active.current_track}/${active.total_tracks}`);
                }
                if (active.command_status) parts.push(`Lidarr: ${active.command_status}`);
                if (parts.length) detail += ' · ' + parts.join(', ');
            }
        } catch (e) {
            detail = 'status unavailable';
        }
        if (!state.done) wantedToast(WANTED_TOAST_ID, `${label} — ${detail} (${elapsed}s)`, 'info');
        if (elapsed > 900) break;
    }
}

function beginWantedProgress(label) {
    wantedActiveShown = true;
    const state = wantedToastState[WANTED_TOAST_ID];
    wantedToast(WANTED_TOAST_ID, `${label} — starting…`, 'info');
    if (state && !state.done) return;  // a progress poll is already running
    wantedToastState[WANTED_TOAST_ID] = { done: false };
    pollWantedProgress(label);
}

function wantedResult(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = JSON.stringify(value, null, 2);
}

function selectedValues(containerId, attribute) {
    return Array.from(document.querySelectorAll(`#${containerId} input:checked`))
        .map(input => input.dataset[attribute]);
}

let wantedSort = { key: 'releaseDate', dir: 'desc' };
let wantedItems = [];

function sortWantedBy(key) {
    if (wantedSort.key === key) {
        wantedSort.dir = wantedSort.dir === 'asc' ? 'desc' : 'asc';
    } else {
        wantedSort = { key: key, dir: 'asc' };
    }
    renderWantedList(wantedItems);
}

function renderWantedList(items) {
    const container = document.getElementById('wantedList');
    if (!container) return;
    wantedItems = items || [];
    container.innerHTML = '';
    if (!wantedItems.length) {
        container.innerHTML = '<em>No missing albums returned by Lidarr.</em>';
        return;
    }
    const sorted = wantedItems.slice().sort((a, b) => {
        const av = String(a[wantedSort.key] || '').toLowerCase();
        const bv = String(b[wantedSort.key] || '').toLowerCase();
        const result = av.localeCompare(bv);
        return wantedSort.dir === 'asc' ? result : -result;
    });

    const columns = [
        ['artist', 'Artist'],
        ['title', 'Album'],
        ['albumType', 'Type'],
        ['releaseDate', 'Released'],
        ['id', 'ID']
    ];
    const table = document.createElement('table');
    table.className = 'wanted-table';
    const thead = document.createElement('thead');
    const headRow = document.createElement('tr');
    const checkHead = document.createElement('th');
    checkHead.textContent = '';
    headRow.appendChild(checkHead);
    columns.forEach(([key, label]) => {
        const th = document.createElement('th');
        th.dataset.sortKey = key;
        const arrow = wantedSort.key === key ? (wantedSort.dir === 'asc' ? ' ▲' : ' ▼') : '';
        th.textContent = label + arrow;
        th.addEventListener('click', () => sortWantedBy(key));
        headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    sorted.forEach(item => {
        const row = document.createElement('tr');
        const checkCell = document.createElement('td');
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.dataset.albumId = item.albumId || item.id || '';
        checkCell.appendChild(check);
        row.appendChild(checkCell);

        const cells = [
            item.artist || '',
            item.title || item.label || '',
            [item.albumType, ...(item.secondaryTypes || [])].filter(Boolean).join(' · '),
            item.releaseDate ? String(item.releaseDate).slice(0, 10) : '',
            String(item.id || '')
        ];
        cells.forEach(value => {
            const td = document.createElement('td');
            td.textContent = value;
            row.appendChild(td);
        });
        tbody.appendChild(row);
    });
    table.appendChild(tbody);
    container.appendChild(table);
}

function renderStaleList(items) {
    const container = document.getElementById('staleList');
    if (!container) return;
    container.innerHTML = '';
    if (!items.length) {
        container.innerHTML = '<em>No stale torrents found.</em>';
        return;
    }
    items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'wanted-row';
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.dataset.recordId = item.id;
        const label = document.createElement('label');
        const name = [item.artist, item.title].filter(Boolean).join(' – ')
            || item.albumTitle || 'Album ' + item.albumId;
        label.textContent = `${name} — ${item.errorMessage || 'stale'}`;
        if (item.downloadTitle && item.downloadTitle !== item.title) {
            label.title = 'Torrent: ' + item.downloadTitle;
        }
        row.appendChild(check);
        row.appendChild(label);
        container.appendChild(row);
    });
}

async function loadWantedSettings() {
    try {
        const status = await wantedApi('/api/wanted/status');
        document.getElementById('wantedSearchEnabled').checked = !!status.wanted_search_enabled;
        document.getElementById('staleCleanupEnabled').checked = !!status.stale_cleanup_enabled;
        document.getElementById('staleCleanupInterval').value = status.stale_cleanup_interval_hours || 6;
        document.getElementById('staleCleanupWait').value = status.stale_cleanup_wait_minutes || 10;
        document.getElementById('preferBlissfulForStale').checked = status.prefer_blissful_for_stale !== false;
        document.getElementById('removeFromClient').checked = status.stale_cleanup_remove_from_client !== false;
        applyWantedBusy(status);
    } catch (error) {
        showNotification(`Could not load wanted settings: ${error.message}`, 'error');
    }
}

async function saveWantedSettings() {
    const payload = {
        wanted_search_enabled: document.getElementById('wantedSearchEnabled').checked,
        stale_cleanup_enabled: document.getElementById('staleCleanupEnabled').checked,
        stale_cleanup_interval_hours: parseInt(document.getElementById('staleCleanupInterval').value, 10) || 6,
        stale_cleanup_wait_minutes: parseInt(document.getElementById('staleCleanupWait').value, 10) || 10,
        prefer_blissful_for_stale: document.getElementById('preferBlissfulForStale').checked,
        stale_cleanup_remove_from_client: document.getElementById('removeFromClient').checked
    };
    try {
        await wantedApi('/api/config', { method: 'POST', body: JSON.stringify(payload) });
        showNotification('Wanted search settings saved. Restart the scheduler to pick up the interval.', 'success');
    } catch (error) {
        showNotification(`Save failed: ${error.message}`, 'error');
    }
}

async function loadWanted() {
    try {
        const data = await wantedApi('/api/wanted');
        renderWantedList(data.items || []);
        wantedResult('wantedResult', { count: (data.items || []).length });
    } catch (error) {
        showNotification(`Could not load wanted items: ${error.message}`, 'error');
    }
}

async function loadStale(preserveResult) {
    try {
        const data = await wantedApi('/api/stale-torrents');
        renderStaleList(data.items || []);
        if (!preserveResult) wantedResult('staleResult', { count: (data.items || []).length });
    } catch (error) {
        showNotification(`Could not load stale torrents: ${error.message}`, 'error');
    }
}

async function runWantedSearch(mode) {
    const apply = document.getElementById('wantedApply').checked;
    const album_ids = mode === 'selected' ? selectedValues('wantedList', 'albumId').filter(Boolean) : [];
    if (mode === 'selected' && !album_ids.length) {
        showNotification('Select at least one album first', 'warning');
        return;
    }
    beginWantedProgress(apply ? 'Queuing searches' : 'Previewing search');
    try {
        const result = await wantedApi('/api/wanted/search', {
            method: 'POST',
            body: JSON.stringify({ mode, album_ids, apply })
        });
        wantedResult('wantedResult', result);
        if (result && result.queued) {
            finishWantedToast('Queued — will start when the current run finishes', 'info', true);
            return;
        }
        const cmd = apply && result.command_status
            ? ` Lidarr: ${result.command_status}${result.command_message ? ' (' + result.command_message + ')' : ''}` : '';
        const fallback = apply && result.fallback && result.fallback.length
            ? ` · Blissful fallback: ${result.fallback.length} album(s)` : '';
        const message = apply
            ? `Search ${result.success ? 'completed' : 'finished with failures'} — ${result.count} album(s).${cmd}${fallback}`
            : `Dry run complete — ${result.count} album(s) would be searched`;
        finishWantedToast(message, 'success', apply);
    } catch (error) {
        if (error.status === 409) {
            const kind = (error.data && error.data.active && error.data.active.kind) || 'run';
            finishWantedToast(`Not started — a ${kind} is already in progress`, 'warning');
        } else {
            finishWantedToast(`Search failed: ${error.message}`, 'error');
        }
    } finally {
        watchWantedBusy();
    }
}

async function runStaleCleanup() {
    const apply = document.getElementById('staleApply').checked;
    const record_ids = selectedValues('staleList', 'recordId');
    beginWantedProgress(apply ? 'Cleaning stale torrents' : 'Previewing cleanup');
    try {
        const result = await wantedApi('/api/stale-torrents/cleanup', {
            method: 'POST',
            body: JSON.stringify({ record_ids, apply })
        });
        wantedResult('staleResult', result);
        if (result && result.queued) {
            finishWantedToast('Queued — will start when the current run finishes', 'info', true);
            return;
        }
        const counts = result.counts || {};
        const reasons = (result.skipped || []).map(s => s.reason).filter(Boolean);
        const errors = (result.errors || []).map(e => typeof e === 'string' ? e : e.reason).filter(Boolean);
        const detail = [...reasons, ...errors].slice(0, 2).join('; ').slice(0, 160);
        const message = apply
            ? `Cleanup finished — imported ${counts.imported || 0}, deleted ${counts.deleted || 0}, kept ${counts.kept || 0}, skipped ${counts.skipped || 0}${detail ? ' — ' + detail : ''}`
            : `Dry run complete — ${counts.scanned || 0} stale item(s) found, ${counts.skipped || 0} skipped${detail ? ' — ' + detail : ''}`;
        finishWantedToast(message, 'success', apply);
        if (apply) loadStale(true);
    } catch (error) {
        if (error.status === 409) {
            const kind = (error.data && error.data.active && error.data.active.kind) || 'run';
            finishWantedToast(`Not started — a ${kind} is already in progress`, 'warning');
        } else {
            finishWantedToast(`Cleanup failed: ${error.message}`, 'error');
        }
    } finally {
        watchWantedBusy();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const wire = (id, handler) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('click', handler);
    };
    wire('saveWantedSettings', saveWantedSettings);
    wire('loadWanted', loadWanted);
    wire('selectAllWanted', () => {
        document.querySelectorAll('#wantedList input[type="checkbox"]').forEach(c => { c.checked = true; });
    });
    wire('searchSelected', () => runWantedSearch('selected'));
    wire('searchAll', () => runWantedSearch('all'));
    wire('loadStale', loadStale);
    wire('selectAllStale', () => {
        document.querySelectorAll('#staleList input[type="checkbox"]').forEach(c => { c.checked = true; });
    });
    wire('cleanupStale', runStaleCleanup);
    loadWantedSettings();
    setInterval(watchWantedBusy, 5000);
});
