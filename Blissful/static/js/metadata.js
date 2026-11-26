/**
 * Metadata provider list: reorderable toggles with expandable credential fields.
 * The first enabled provider that resolves a track wins; AcoustID only verifies
 * audio after download, so its position in the list has no effect on refinement.
 */

const METADATA_PROVIDERS = [
    {
        key: 'spotify',
        name: 'Spotify',
        mode: 'Refines the search query',
        enabledKey: 'spotify_metadata_enabled',
        fields: [
            {id: 'spotifyClientId', configKey: 'spotify_client_id', label: 'Spotify Client ID',
             type: 'text', placeholder: 'From Spotify Developer Dashboard'},
            {id: 'spotifyClientSecret', configKey: 'spotify_client_secret',
             label: 'Spotify Client Secret', type: 'password', secret: true,
             placeholder: 'Leave blank to keep saved secret',
             savedPlaceholder: 'Secret configured (leave blank to keep)'}
        ]
    },
    {
        key: 'discogs',
        name: 'Discogs',
        mode: 'Refines the search query',
        enabledKey: 'discogs_metadata_enabled',
        fields: [
            {id: 'discogsToken', configKey: 'discogs_token', label: 'Discogs Personal Access Token',
             type: 'password', secret: true, placeholder: 'From Discogs Developer Settings',
             savedPlaceholder: 'Token configured (leave blank to keep)'}
        ]
    },
    {
        key: 'musicbrainz',
        name: 'MusicBrainz',
        mode: 'Refines the search query - no account needed',
        enabledKey: 'musicbrainz_metadata_enabled',
        fields: []
    },
    {
        key: 'acoustid',
        name: 'AcoustID',
        mode: 'Verifies audio after download',
        enabledKey: 'acoustid_verify_enabled',
        fields: [
            {id: 'acoustidApiKey', configKey: 'acoustid_api_key',
             label: 'AcoustID Application Key (client)', type: 'password', secret: true,
             placeholder: 'From acoustid.org/new-application',
             savedPlaceholder: 'Key configured (leave blank to keep)'},
            {id: 'acoustidUserKey', configKey: 'acoustid_user_key',
             label: 'AcoustID User Key', type: 'password', secret: true,
             placeholder: 'From acoustid.org/api-key (required from 2027)',
             savedPlaceholder: 'Key configured (leave blank to keep)'},
            {id: 'acoustidMinScore', configKey: 'acoustid_min_score',
             label: 'Minimum match score', type: 'number', min: 0, max: 1, step: 0.05,
             value: '0.75',
             hint: '0 to 1; higher is stricter. A candidate is accepted when its artist and title match at or above this score.'}
        ]
    }
];

let metadataDraggedItem = null;

function setMetadataFieldValue(field, fieldConfig, config) {
    const value = config[fieldConfig.configKey];
    if (fieldConfig.secret && value === '***MASKED***') {
        field.value = '';
        field.dataset.hasSavedKey = 'true';
        field.placeholder = fieldConfig.savedPlaceholder || 'Configured (leave blank to keep)';
    } else {
        field.value = (value === undefined || value === null)
            ? (fieldConfig.value || '') : String(value);
        field.dataset.hasSavedKey = 'false';
        field.placeholder = fieldConfig.placeholder || '';
    }
}

function createMetadataField(fieldConfig, config) {
    const group = document.createElement('div');
    group.className = 'form-group';
    const label = document.createElement('label');
    label.htmlFor = fieldConfig.id;
    label.textContent = fieldConfig.label;
    const input = document.createElement('input');
    input.type = fieldConfig.type;
    input.id = fieldConfig.id;
    if (fieldConfig.type === 'number') {
        input.min = fieldConfig.min;
        input.max = fieldConfig.max;
        input.step = fieldConfig.step;
    }
    setMetadataFieldValue(input, fieldConfig, config);
    group.appendChild(label);
    group.appendChild(input);
    if (fieldConfig.hint) {
        const hint = document.createElement('small');
        hint.textContent = fieldConfig.hint;
        group.appendChild(hint);
    }
    return group;
}

function createMetadataItem(provider, index, config) {
    const item = document.createElement('div');
    item.className = 'metadata-provider-item';
    item.dataset.provider = provider.key;
    item.draggable = true;
    item.addEventListener('dragstart', handleMetadataDragStart);
    item.addEventListener('dragover', handleMetadataDragOver);
    item.addEventListener('drop', handleMetadataDrop);
    item.addEventListener('dragend', handleMetadataDragEnd);

    const header = document.createElement('div');
    header.className = 'metadata-header';
    header.innerHTML = `
        <div class="drag-handle">⋮⋮</div>
        <div class="priority-badge">${index + 1}</div>
        <div class="metadata-info">
            <strong></strong>
            <small></small>
        </div>
        <div class="source-controls">
            <label class="toggle-switch">
                <input type="checkbox">
                <span class="toggle-slider"></span>
            </label>
            <span class="metadata-hint">▾</span>
        </div>
    `;
    header.querySelector('strong').textContent = provider.name;
    header.querySelector('small').textContent = provider.mode;
    const toggle = header.querySelector('input[type="checkbox"]');
    toggle.checked = !!config[provider.enabledKey];
    toggle.setAttribute('aria-label', 'Enable ' + provider.name);

    item.appendChild(header);

    if (provider.fields.length) {
        const fields = document.createElement('div');
        fields.className = 'metadata-fields';
        provider.fields.forEach(fieldConfig =>
            fields.appendChild(createMetadataField(fieldConfig, config)));
        item.appendChild(fields);
        header.querySelector('.metadata-info').addEventListener('click', () => {
            item.classList.toggle('expanded');
        });
        header.querySelector('.metadata-hint').addEventListener('click', () => {
            item.classList.toggle('expanded');
        });
    }
    return item;
}

function loadMetadataProviders(config) {
    const container = document.getElementById('metadataProviderList');
    if (!container) return;
    container.innerHTML = '';
    const configured = Array.isArray(config.metadata_provider_order)
        ? config.metadata_provider_order : [];
    const providers = [];
    configured.forEach(name => {
        const found = METADATA_PROVIDERS.find(p => p.key === name);
        if (found && !providers.includes(found)) providers.push(found);
    });
    METADATA_PROVIDERS.forEach(provider => {
        if (!providers.includes(provider)) providers.push(provider);
    });
    providers.forEach((provider, index) =>
        container.appendChild(createMetadataItem(provider, index, config)));
}

function handleMetadataDragStart(e) {
    metadataDraggedItem = this;
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', this.innerHTML);
}

function handleMetadataDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const container = document.getElementById('metadataProviderList');
    const after = [...container.querySelectorAll('.metadata-provider-item:not(.dragging)')]
        .reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = e.clientY - box.top - box.height / 2;
            return offset < 0 && offset > closest.offset
                ? {offset, element: child} : closest;
        }, {offset: Number.NEGATIVE_INFINITY}).element;
    if (after == null) container.appendChild(metadataDraggedItem);
    else container.insertBefore(metadataDraggedItem, after);
    return false;
}

function handleMetadataDrop(e) {
    e.stopPropagation();
    updateMetadataBadges();
    return false;
}

function handleMetadataDragEnd() {
    this.classList.remove('dragging');
    metadataDraggedItem = null;
    updateMetadataBadges();
}

function updateMetadataBadges() {
    document.querySelectorAll('#metadataProviderList .metadata-provider-item')
        .forEach((item, index) => {
            item.querySelector('.priority-badge').textContent = index + 1;
        });
}

function getMetadataProviderState() {
    const state = {metadata_provider_order: []};
    const items = document.querySelectorAll('#metadataProviderList .metadata-provider-item');
    items.forEach(item => {
        const key = item.dataset.provider;
        const provider = METADATA_PROVIDERS.find(p => p.key === key);
        if (!provider) return;
        state.metadata_provider_order.push(key);
        state[provider.enabledKey] = item.querySelector('input[type="checkbox"]').checked;
        provider.fields.forEach(fieldConfig => {
            const field = document.getElementById(fieldConfig.id);
            if (!field) return;
            let value = field.value.trim();
            if (fieldConfig.secret && !value && field.dataset.hasSavedKey === 'true') {
                value = '***KEEP_EXISTING***';
            }
            if (fieldConfig.type === 'number') {
                const parsed = parseFloat(value);
                value = isNaN(parsed) ? 0.75 : Math.min(1, Math.max(0, parsed));
            }
            state[fieldConfig.configKey] = value;
        });
    });
    return state;
}
