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

function setWantedButtonsBusy(busy) {
    WANTED_ACTION_IDS.forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        el.disabled = busy;
        el.title = busy ? 'A wanted search or cleanup is already running' : '';
    });
}

let wantedActiveShown = false;

function applyWantedBusy(active) {
    setWantedButtonsBusy(!!active);
    if (active && !wantedActiveShown) {
        wantedActiveShown = true;
        beginWantedProgress('wanted-toast-run',
            active.kind === 'cleanup' ? 'Cleaning stale torrents' : 'Searching wanted albums');
    }
    if (!active) wantedActiveShown = false;
}

async function watchWantedBusy() {
    try {
        const status = await wantedApi('/api/wanted/status');
        applyWantedBusy(status.active);
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
        el.innerHTML = '<span class="wanted-toast-dot"></span><span class="wanted-toast-text"></span>';
        document.body.appendChild(el);
    }
    el.dataset.type = type || 'info';
    const text = el.querySelector('.wanted-toast-text');
    if (text) text.textContent = message;
    return el;
}

function finishWantedToast(id, message, type) {
    const state = wantedToastState[id] || { done: false };
    state.done = true;
    wantedToast(id, message, type);
    setTimeout(() => {
        const el = document.getElementById(id);
        if (el) el.remove();
        delete wantedToastState[id];
    }, type === 'error' ? 8000 : 5000);
}

async function pollWantedProgress(id, label) {
    const state = wantedToastState[id] || { done: false };
    const started = Date.now();
    while (!state.done) {
        await new Promise(resolve => setTimeout(resolve, 1500));
        if (state.done) break;
        const elapsed = Math.round((Date.now() - started) / 1000);
        let detail = 'working';
        try {
            const status = await wantedApi('/api/wanted/status');
            const active = status.active;
            if (active && active.kind === 'cleanup') {
                detail = active.phase || 'searching';
                const parts = [];
                for (const key of ['scanned', 'searched', 'imported', 'deleted']) {
                    if (active[key] !== undefined) parts.push(`${key} ${active[key]}`);
                }
                if (parts.length) detail += ' · ' + parts.join(', ');
            }
        } catch (e) {
            detail = 'status unavailable';
        }
        if (!state.done) wantedToast(id, `${label} — ${detail} (${elapsed}s)`, 'info');
        if (elapsed > 900) break;
    }
}

function beginWantedProgress(id, label) {
    wantedToastState[id] = { done: false };
    wantedToast(id, `${label} — starting…`, 'info');
    pollWantedProgress(id, label);
}

function wantedResult(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = JSON.stringify(value, null, 2);
}

function selectedValues(containerId, attribute) {
    return Array.from(document.querySelectorAll(`#${containerId} input:checked`))
        .map(input => input.dataset[attribute]);
}

function renderWantedList(items) {
    const container = document.getElementById('wantedList');
    if (!container) return;
    container.innerHTML = '';
    if (!items.length) {
        container.innerHTML = '<em>No missing albums returned by Lidarr.</em>';
        return;
    }
    items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'wanted-row';
        const check = document.createElement('input');
        check.type = 'checkbox';
        check.dataset.albumId = item.albumId || item.id || '';
        const label = document.createElement('label');
        label.textContent = item.label || `${item.albumTitle || item.title || 'Unknown album'} (${item.artistId || ''})`;
        row.appendChild(check);
        row.appendChild(label);
        container.appendChild(row);
    });
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
        label.textContent = `${item.title || 'Album ' + item.albumId} — ${item.errorMessage || 'stale'}`;
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
        applyWantedBusy(status.active);
    } catch (error) {
        showNotification(`Could not load wanted settings: ${error.message}`, 'error');
    }
}

async function saveWantedSettings() {
    const payload = {
        wanted_search_enabled: document.getElementById('wantedSearchEnabled').checked,
        stale_cleanup_enabled: document.getElementById('staleCleanupEnabled').checked,
        stale_cleanup_interval_hours: parseInt(document.getElementById('staleCleanupInterval').value, 10) || 6,
        stale_cleanup_wait_minutes: parseInt(document.getElementById('staleCleanupWait').value, 10) || 10
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

async function loadStale() {
    try {
        const data = await wantedApi('/api/stale-torrents');
        renderStaleList(data.items || []);
        wantedResult('staleResult', { count: (data.items || []).length });
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
    const toastId = 'wanted-toast-search';
    setWantedButtonsBusy(true);
    beginWantedProgress(toastId, apply ? 'Queuing searches' : 'Previewing search');
    try {
        const result = await wantedApi('/api/wanted/search', {
            method: 'POST',
            body: JSON.stringify({ mode, album_ids, apply })
        });
        wantedResult('wantedResult', result);
        const message = apply
            ? `Search queued — ${result.count} album(s), command ${result.command_id || 'n/a'}`
            : `Dry run complete — ${result.count} album(s) would be searched`;
        finishWantedToast(toastId, message, 'success');
    } catch (error) {
        const detail = error.data && error.data.active
            ? ` (${error.data.active.kind || 'run'} in progress)` : '';
        finishWantedToast(toastId, `Search failed: ${error.message}${detail}`, 'error');
    } finally {
        setWantedButtonsBusy(false);
    }
}

async function runStaleCleanup() {
    const apply = document.getElementById('staleApply').checked;
    const record_ids = selectedValues('staleList', 'recordId');
    const toastId = 'wanted-toast-cleanup';
    setWantedButtonsBusy(true);
    beginWantedProgress(toastId, apply ? 'Cleaning stale torrents' : 'Previewing cleanup');
    try {
        const result = await wantedApi('/api/stale-torrents/cleanup', {
            method: 'POST',
            body: JSON.stringify({ record_ids, apply })
        });
        wantedResult('staleResult', result);
        const counts = result.counts || {};
        const message = apply
            ? `Cleanup finished — imported ${counts.imported || 0}, deleted ${counts.deleted || 0}, kept ${counts.kept || 0}`
            : `Dry run complete — ${counts.scanned || 0} stale item(s) found`;
        finishWantedToast(toastId, message, 'success');
        if (apply) loadStale();
    } catch (error) {
        const detail = error.data && error.data.active
            ? ` (${error.data.active.kind || 'run'} in progress)` : '';
        finishWantedToast(toastId, `Cleanup failed: ${error.message}${detail}`, 'error');
    } finally {
        setWantedButtonsBusy(false);
    }
}

async function resetWantedState() {
    try {
        await wantedApi('/api/wanted/reset', { method: 'POST', body: '{}' });
        showNotification('Wanted search state reset', 'success');
    } catch (error) {
        showNotification(`Reset failed: ${error.message}`, 'error');
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
    wire('resetWantedState', resetWantedState);
    loadWantedSettings();
    setInterval(watchWantedBusy, 5000);
});
