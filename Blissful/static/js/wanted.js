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
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
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
    try {
        const result = await wantedApi('/api/wanted/search', {
            method: 'POST',
            body: JSON.stringify({ mode, album_ids, apply })
        });
        wantedResult('wantedResult', result);
        showNotification(apply ? 'Search command queued' : 'Dry run complete', 'success');
    } catch (error) {
        showNotification(`Search failed: ${error.message}`, 'error');
    }
}

async function runStaleCleanup() {
    const apply = document.getElementById('staleApply').checked;
    const record_ids = selectedValues('staleList', 'recordId');
    try {
        const result = await wantedApi('/api/stale-torrents/cleanup', {
            method: 'POST',
            body: JSON.stringify({ record_ids, apply })
        });
        wantedResult('staleResult', result);
        showNotification(apply ? 'Stale cleanup finished' : 'Dry run complete', 'success');
    } catch (error) {
        showNotification(`Cleanup failed: ${error.message}`, 'error');
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
});
