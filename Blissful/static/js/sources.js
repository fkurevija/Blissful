/**
 * Source Management - Simplified
 * Direct list of searchable yt-dlp sources with enable/disable and reordering
 *
 * The ordered source list is a config slice; the DOM is only its projection.
 */

const SrcB = window.Blissful;

let draggedItem = null;

function sourceState() {
    const cfg = SrcB.state.get('config') || {};
    if (!Array.isArray(cfg.source_priorities)) {
        SrcB.state.patch('config', { source_priorities: [] }, { source: 'sources' });
        return [];
    }
    return cfg.source_priorities;
}

function setSourceState(list) {
    SrcB.state.patch('config', { source_priorities: list }, { source: 'sources' });
}

function sourceKey(source) {
    return String(source.name || '') + '\u0000' + String(source.search || String(source.name || '').toLowerCase());
}

// Rebuild the state slice from DOM *data attributes* after a drag or toggle.
// Names/searches are never parsed back out of <strong>/<small> textContent.
function syncSourceStateFromDom() {
    const container = document.getElementById('sourcePriorityList');
    if (!container) return;
    const byKey = Object.create(null);
    sourceState().forEach(source => { byKey[sourceKey(source)] = source; });
    const next = Array.prototype.slice.call(container.querySelectorAll('.source-priority-item'))
        .map((item, index) => {
            const name = item.dataset.sourceName || '';
            const search = item.dataset.sourceSearch || name.toLowerCase();
            const previous = byKey[sourceKey({ name: name, search: search })] || {};
            const toggle = item.querySelector('input[type="checkbox"]');
            const tier = parseInt(item.dataset.tier, 10) || previous.tier || 4;
            return {
                name: name,
                search: search,
                enabled: toggle ? toggle.checked : true,
                tier: tier,
                description: previous.description || '',
                index: index
            };
        });
    setSourceState(next);
}

// Load source priorities - shows ALL searchable sources
function loadSourcePriorities(priorities) {
    // Spotify, Discogs and AcoustID are metadata-only; hide stale saved entries.
    const visible = (priorities || []).filter(source =>
        !/spotify|discog|acoustid|chromaprint|musicbrainz|mbid/i.test(source.name || '') &&
        !/spotify|discog|acoustid|chromaprint|musicbrainz|mbid/i.test(source.search || ''))
        .map(source => ({
            name: source.name,
            search: source.search || String(source.name || '').toLowerCase(),
            enabled: source.enabled !== false,
            tier: source.tier || 4,
            description: source.description || ''
        }));
    setSourceState(visible);
    renderSourceItems(visible);
}

function renderSourceItems(items) {
    const container = document.getElementById('sourcePriorityList');
    if (!container) return;
    container.innerHTML = '';

    // If no priorities configured, show all searchable sources from API
    if (!items.length) {
        // Will be populated after API loads
        setTimeout(() => {
            populateAllSearchableSources();
            if (typeof checkYouTubeLoginStatus === 'function') checkYouTubeLoginStatus();
        }, 100);
        return;
    }

    items.forEach((source, index) => {
        container.appendChild(createSourcePriorityItem(source, index));
    });
    updatePriorityBadges();
    if (typeof checkYouTubeLoginStatus === 'function') checkYouTubeLoginStatus();
}

// Populate all searchable sources from API
async function populateAllSearchableSources() {
    try {
        const response = await fetch('/api/supported-sources?music_only=false');
        const data = await response.json();
        
        if (!data.success) {
            console.error('Failed to load sources');
            return;
        }
        
        // Filter to only searchable sources and sort by tier
        const searchableSources = data.sources
            .filter(source => source.search_supported)
            .sort((a, b) => {
                if (a.tier !== b.tier) return a.tier - b.tier;
                return a.name.localeCompare(b.name);
            });
        
        const container = document.getElementById('sourcePriorityList');
        if (!container) return;
        const defaults = searchableSources.map(source => ({
            name: source.name,
            search: source.ie_key || source.name.toLowerCase(),
            enabled: true,
            tier: source.tier,
            description: source.description
        }));
        setSourceState(defaults);
        renderSourceItems(defaults);
        if (typeof checkYouTubeLoginStatus === 'function') checkYouTubeLoginStatus();
        console.log(`✅ Loaded ${searchableSources.length} searchable sources`);
        
    } catch (error) {
        console.error('Error loading sources:', error);
        const container = document.getElementById('sourcePriorityList');
        container.innerHTML = `
            <div class="source-placeholder">
                <span>❌</span>
                <p>Error loading sources</p>
                <button class="btn btn-secondary" onclick="populateAllSearchableSources()">🔄 Retry</button>
            </div>
        `;
    }
}

// Create source priority item
function createSourcePriorityItem(source, index) {
    const div = document.createElement('div');
    div.className = 'source-priority-item';
    div.draggable = true;
    div.dataset.index = index;
    // Serialization keys live in dataset, never in rendered text.
    div.dataset.sourceName = source.name || '';
    div.dataset.sourceSearch = source.search || String(source.name || '').toLowerCase();
    div.dataset.tier = String(source.tier || 4);

    div.addEventListener('dragstart', handleDragStart);
    div.addEventListener('dragover', handleDragOver);
    div.addEventListener('drop', handleDrop);
    div.addEventListener('dragend', handleDragEnd);
    
    div.innerHTML = `
        <div class="drag-handle">⋮⋮</div>
        <div class="priority-badge">${index + 1}</div>
        <div class="source-info">
            <strong>${source.name}</strong>
            <small>${source.search || source.name.toLowerCase()}</small>
        </div>
        <div class="source-controls">
            <label class="toggle-switch">
                <input type="checkbox" ${source.enabled ? 'checked' : ''} onchange="toggleSource(${index})">
                <span class="toggle-slider"></span>
            </label>
        </div>
    `;

    if (/youtube/i.test(source.name || '') || /youtube/i.test(source.search || '')) {
        const hint = document.createElement('span');
        hint.className = 'source-hint';
        hint.textContent = '▾';
        div.querySelector('.source-controls').appendChild(hint);
        hint.addEventListener('click', () => div.classList.toggle('expanded'));
        const fields = document.createElement('div');
        fields.className = 'source-fields';
        fields.innerHTML = `
            <div class="form-group">
                <label>YouTube session (optional)</label>
                <div class="youtube-login-row">
                    <button type="button" class="btn btn-sm youtube-login-btn" onclick="startYouTubeLogin()">Login with YouTube</button>
                    <span class="youtube-login-status">Checking login status…</span>
                </div>
                <textarea class="youtube-cookies-field" rows="5" spellcheck="false"
                    placeholder="Or paste Netscape-format cookies.txt from a signed-in browser"></textarea>
                <small>Login is handled in an embedded browser when the optional youtube-login profile is enabled. Cookies are stored as a secret and never displayed back.</small>
            </div>
        `;
        div.appendChild(fields);
        div.querySelector('.source-info').addEventListener('click', () => {
            div.classList.toggle('expanded');
        });
    }
    return div;
}

// Drag and drop handlers
function handleDragStart(e) {
    draggedItem = this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', this.innerHTML);
}

function handleDragOver(e) {
    if (e.preventDefault) {
        e.preventDefault();
    }
    e.dataTransfer.dropEffect = 'move';
    
    const container = document.getElementById('sourcePriorityList');
    const afterElement = getDragAfterElement(container, e.clientY);
    
    if (afterElement == null) {
        container.appendChild(draggedItem);
    } else {
        container.insertBefore(draggedItem, afterElement);
    }
    
    return false;
}

function handleDrop(e) {
    if (e.stopPropagation) {
        e.stopPropagation();
    }
    
    updatePriorityBadges();
    return false;
}

function handleDragEnd(e) {
    this.classList.remove('dragging');
    draggedItem = null;
    updatePriorityBadges();
}

function getDragAfterElement(container, y) {
    const draggableElements = [...container.querySelectorAll('.source-priority-item:not(.dragging)')];
    
    return draggableElements.reduce((closest, child) => {
        const box = child.getBoundingClientRect();
        const offset = y - box.top - box.height / 2;
        
        if (offset < 0 && offset > closest.offset) {
            return { offset: offset, element: child };
        } else {
            return closest;
        }
    }, { offset: Number.NEGATIVE_INFINITY }).element;
}

// Update priority badges and event handlers
function updatePriorityBadges() {
    const container = document.getElementById('sourcePriorityList');
    const items = container.querySelectorAll('.source-priority-item');
    
    items.forEach((item, index) => {
        const badge = item.querySelector('.priority-badge');
        badge.textContent = index + 1;
        
        const toggle = item.querySelector('input[type="checkbox"]');
        if (toggle) {
            toggle.onchange = () => toggleSource(index);
        }
    });
    // Drag reorders physical nodes; mirror the new order into the slice.
    syncSourceStateFromDom();
}

// Toggle source enabled/disabled
function toggleSource(index) {
    console.log(`Source ${index} toggled`);
    const items = document.querySelectorAll('.source-priority-item');
    const item = items[index];
    if (item) {
        const isEnabled = item.querySelector('input[type="checkbox"]').checked;
        if (isEnabled) {
            item.style.opacity = '1';
        } else {
            item.style.opacity = '0.6';
        }
    }
    syncSourceStateFromDom();
}

// Filter sources — reads dataset keys, not rendered textContent.
function filterSources() {
    const filter = document.getElementById('sourceFilter').value.toLowerCase();
    const items = document.querySelectorAll('.source-priority-item');

    items.forEach(item => {
        const name = (item.dataset.sourceName || '').toLowerCase();
        const search = (item.dataset.sourceSearch || '').toLowerCase();

        if (name.includes(filter) || search.includes(filter)) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });
}

// Get source priorities for saving — always from state, never DOM text.
function getSourcePriorities() {
    return sourceState().map(source => ({
        name: source.name,
        search: source.search || String(source.name || '').toLowerCase(),
        enabled: !!source.enabled,
        tier: source.tier || 4
    }));
}

// Load supported sources (called from main.js)
async function loadSupportedSources() {
    // No longer needed - sources are loaded as part of priority list
    console.log('Sources loaded via populateAllSearchableSources()');
}

window.Blissful.register({
    loadSourcePriorities: loadSourcePriorities,
    populateAllSearchableSources: populateAllSearchableSources,
    createSourcePriorityItem: createSourcePriorityItem,
    toggleSource: toggleSource,
    filterSources: filterSources,
    getSourcePriorities: getSourcePriorities,
    loadSupportedSources: loadSupportedSources,
    sourceState: sourceState,
    setSourceState: setSourceState
});
