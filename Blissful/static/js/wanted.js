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

// Wanted-run status lives in the store; the toast lifecycle lives in the
// single ToastManager. There are no module-local toast flags or state maps.
const state = window.Blissful.state;
const scheduler = window.Blissful.scheduler;
const toasts = window.Blissful.toasts;

/**
 * Fetch /api/wanted/status under the scheduler's monotonic sequence guard.
 * Returns undefined when a newer poll on the same channel has started, so a
 * slow older response can never overwrite newer wantedRun/toast state.
 */
async function fetchWantedStatus(channelName) {
    channelName = channelName || 'wantedStatus';
    const token = scheduler.next(channelName);
    const status = await wantedApi('/api/wanted/status');
    if (!scheduler.isCurrent(channelName, token)) return undefined;
    return status;
}

function applyWantedBusy(status) {
    if (!status) return;
    setWantedButtonHints(status.runs);
    state.patch('wantedRun', {
        active: status.active || null,
        runs: status.runs || {},
        lastActivity: status.last_activity || null
    }, { source: 'wanted/status' });
    toasts.syncRun(status);
}

async function watchWantedBusy() {
    try {
        const status = await fetchWantedStatus('wantedStatus');
        if (status) applyWantedBusy(status);
    } catch (e) {
        // Status polling is best-effort; never break the page on a transient error.
    }
}

/**
 * Thin boundary wrappers. The DOM, lease lifecycle and auto-dismiss timers all
 * live in boot.js's ToastManager; only the public names stay here for callers.
 */
function wantedToast(id, message, type) {
    if (id === 'youtube-login-toast') {
        toasts.youtube(message, type);
        return document.getElementById(id);
    }
    let lease = toasts.currentLease();
    if (!lease && message) {
        toasts.beginRun(String(message).split(' — ')[0]);
        lease = toasts.currentLease();
    }
    toasts.updateRun(lease, message, type);
    return document.getElementById('wanted-toast-active');
}

function finishWantedToast(message, type, showLink) {
    toasts.finishRun(toasts.currentLease(), message, type, showLink);
}

/**
 * Progress poll for one run lease. Its status fetch uses its own scheduler
 * channel so the 5 s background status poll cannot invalidate its response.
 */
async function pollWantedProgress(lease) {
    if (!lease) return;
    const label = lease.label;
    const started = lease.startedAt;
    while (!lease.done && toasts.isCurrent(lease)) {
        await new Promise(resolve => scheduler.schedule('wantedProgress', resolve, 1500));
        if (lease.done || !toasts.isCurrent(lease)) break;
        const elapsed = Math.round((Date.now() - started) / 1000);
        let detail = 'working';
        try {
            const status = await fetchWantedStatus('wantedProgressStatus');
            if (!status) break;  // superseded by a newer poll on this channel
            const active = status.active;
            if (!active && lease.sawActive) {
                // The run ended (or was cancelled) outside this tab. Close the
                // sticky toast instead of polling stale progress forever.
                const last = status.last_activity || {};
                const wasCancelled = last.cancel_requested === true
                    || last.status === 'cancelled';
                toasts.finishRun(lease,
                    wasCancelled ? `${label} cancelled` : `${label} finished`,
                    wasCancelled ? 'info' : 'success', true);
                break;
            }
            if (active) lease.sawActive = true;
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
                const done = active.completed_tracks ?? active.current_track;
                if (done && active.total_tracks) {
                    parts.push(`progress ${done}/${active.total_tracks}`);
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
                const done = active.completed_tracks ?? active.current_track;
                if (done && active.total_tracks) {
                    parts.push(`progress ${done}/${active.total_tracks}`);
                }
                if (active.command_status) parts.push(`Lidarr: ${active.command_status}`);
                if (parts.length) detail += ' · ' + parts.join(', ');
            }
        } catch (e) {
            detail = 'status unavailable';
        }
        if (!lease.done) toasts.updateRun(lease, `${label} — ${detail} (${elapsed}s)`, 'info');
        if (elapsed > 900) break;
    }
    scheduler.cancelSchedule('wantedProgress');
}

function beginWantedProgress(label) {
    toasts.beginRun(label);
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
        // Own channel: the 5 s background poll must not invalidate this one.
        const status = await fetchWantedStatus('wantedSettings');
        if (!status) return;
        const settings = {
            wanted_search_enabled: !!status.wanted_search_enabled,
            stale_cleanup_enabled: !!status.stale_cleanup_enabled,
            stale_cleanup_interval_hours: status.stale_cleanup_interval_hours || 6,
            stale_cleanup_wait_minutes: status.stale_cleanup_wait_minutes || 10,
            prefer_blissful_for_stale: status.prefer_blissful_for_stale !== false,
            stale_cleanup_remove_from_client: status.stale_cleanup_remove_from_client !== false
        };
        state.patch('wantedRun', { settings: settings }, { source: 'wanted/settings' });
        // DOM is a projection of the store slice.
        document.getElementById('wantedSearchEnabled').checked = settings.wanted_search_enabled;
        document.getElementById('staleCleanupEnabled').checked = settings.stale_cleanup_enabled;
        document.getElementById('staleCleanupInterval').value = settings.stale_cleanup_interval_hours;
        document.getElementById('staleCleanupWait').value = settings.stale_cleanup_wait_minutes;
        document.getElementById('preferBlissfulForStale').checked = settings.prefer_blissful_for_stale;
        document.getElementById('removeFromClient').checked = settings.stale_cleanup_remove_from_client;
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
    state.patch('wantedRun', { settings: payload }, { source: 'dom' });
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
    // Tracked poll with a handle (stop/restart) instead of a bare setInterval.
    scheduler.start('wantedStatus', watchWantedBusy, 5000);
});

// Publish the public API into the single Blissful namespace. boot.js installs
// the thin global aliases used by legacy inline handlers.
window.Blissful.register({
    wantedApi: wantedApi,
    fetchWantedStatus: fetchWantedStatus,
    applyWantedBusy: applyWantedBusy,
    watchWantedBusy: watchWantedBusy,
    wantedToast: wantedToast,
    finishWantedToast: finishWantedToast,
    pollWantedProgress: pollWantedProgress,
    beginWantedProgress: beginWantedProgress,
    runWantedSearch: runWantedSearch,
    runStaleCleanup: runStaleCleanup,
    loadWantedSettings: loadWantedSettings,
    saveWantedSettings: saveWantedSettings,
    loadWanted: loadWanted,
    loadStale: loadStale,
    selectedValues: selectedValues
});
