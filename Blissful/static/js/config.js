/**
 * Configuration Management
 * Handles loading, saving, and validating configuration
 */

// Quality presets for different formats
const qualityPresets = {
    mp3: [
        { value: '128k', label: '128 kbps - Low Quality' },
        { value: '192k', label: '192 kbps - Medium Quality' },
        { value: '256k', label: '256 kbps - High Quality' },
        { value: '320k', label: '320 kbps - Maximum Quality (Recommended)' }
    ],
    opus: [
        { value: '96k', label: '96 kbps - Good Quality' },
        { value: '128k', label: '128 kbps - High Quality' },
        { value: '192k', label: '192 kbps - Very High Quality' },
        { value: '256k', label: '256 kbps - Maximum Quality (Recommended)' }
    ],
    aac: [
        { value: '128k', label: '128 kbps - Medium Quality' },
        { value: '192k', label: '192 kbps - High Quality' },
        { value: '256k', label: '256 kbps - Very High Quality' },
        { value: '320k', label: '320 kbps - Maximum Quality (Recommended)' }
    ],
    ogg: [
        { value: 'q5', label: 'Quality 5 - Good (~160 kbps)' },
        { value: 'q7', label: 'Quality 7 - High (~224 kbps)' },
        { value: 'q9', label: 'Quality 9 - Very High (~320 kbps)' },
        { value: 'q10', label: 'Quality 10 - Maximum (Recommended)' }
    ],
    flac: [
        { value: '0', label: 'Compression Level 0 - Fast' },
        { value: '5', label: 'Compression Level 5 - Balanced' },
        { value: '8', label: 'Compression Level 8 - Maximum (Recommended)' }
    ],
    wav: [
        { value: 'pcm_s16le', label: '16-bit PCM (Standard)' },
        { value: 'pcm_s24le', label: '24-bit PCM (High Resolution)' },
        { value: 'pcm_s32le', label: '32-bit PCM (Maximum)' }
    ]
};

/* ------------------------------------------------------------------ *
 * Declarative config schema — one descriptor per persisted key.
 * Load, save, masking and KEEP_EXISTING are all driven from this table,
 * so adding a setting no longer means editing mirrored DOM schemas.
 * ------------------------------------------------------------------ */
const CfgB = window.Blissful;
const CONFIG_STATE = CfgB.state;
const CONFIG_SCHED = CfgB.scheduler;

const CONFIG_FIELDS = [
    { key: 'lidarr_url', id: 'lidarrUrl', type: 'text', default: '' },
    { key: 'lidarr_api_key', id: 'lidarrApiKey', type: 'secret', default: '', trim: true,
      maskedPlaceholder: 'API Key configured (enter new key to change)',
      plainPlaceholder: 'Your Lidarr API Key' },
    { key: 'output_format', id: 'outputFormat', type: 'select', default: 'mp3' },
    { key: 'quality', id: 'quality', type: 'select', default: '320k' },
    { key: 'normalize_audio', id: 'normalizeAudio', type: 'bool', default: false },
    { key: 'mono_audio', id: 'monoAudio', type: 'bool', default: false },
    { key: 'sample_rate', id: 'sampleRate', type: 'select', default: 'original' },
    { key: 'remove_silence', id: 'removeSilence', type: 'bool', default: false },
    { key: 'loudness_normalization', id: 'loudnessNorm', type: 'bool', default: false },
    { key: 'channels', id: 'channels', type: 'select', default: 'original' },
    { key: 'auto_cleanup', id: 'autoCleanup', type: 'boolDefaultOn', default: true },
    { key: 'embed_metadata', id: 'embedMetadata', type: 'boolDefaultOn', default: true },
    { key: 'embed_thumbnail', id: 'embedThumbnail', type: 'boolDefaultOn', default: true },
    { key: 'auth_token', id: 'authToken', type: 'secret', default: '', trim: true,
      maskedPlaceholder: 'Token configured (leave blank to keep)' },
    { key: 'search_results_per_source', id: 'searchResultsPerSource', type: 'int',
      default: 3, min: 1, max: 10 },
    { key: 'youtube_cookies', selector: '.youtube-cookies-field', type: 'sharedSecret',
      default: '', maskedPlaceholder: 'Cookies configured (leave blank to keep)',
      plainPlaceholder: 'Or paste Netscape-format cookies.txt from a signed-in browser' },
    { key: 'enable_requests', id: 'enableRequests', type: 'bool', default: false },
    { key: 'auto_monitor_requests', id: 'autoMonitorRequests', type: 'bool', default: false },
    { key: 'enable_jellyfin', id: 'enableJellyfin', type: 'bool', default: false },
    { key: 'jellyfin_url', id: 'jellyfinUrl', type: 'text', default: '' },
    { key: 'jellyfin_api_key', id: 'jellyfinApiKey', type: 'text', default: '' },
    { key: 'enable_emby', id: 'enableEmby', type: 'bool', default: false },
    { key: 'emby_url', id: 'embyUrl', type: 'text', default: '' },
    { key: 'emby_api_key', id: 'embyApiKey', type: 'text', default: '' },
    { key: 'enable_plex', id: 'enablePlex', type: 'bool', default: false },
    { key: 'request_default_monitored', id: 'requestDefaultMonitored',
      type: 'boolFromSelect', default: false },
    { key: 'request_search_missing', id: 'requestSearchMissing',
      type: 'boolFromSelect', default: false }
];

const QUALITY_FIELD = CONFIG_FIELDS.find(f => f.key === 'quality');
const COOKIES_FIELD = CONFIG_FIELDS.find(f => f.type === 'sharedSecret');
const SECRET_KEYS = ['lidarr_api_key', 'spotify_client_secret', 'discogs_token',
    'acoustid_api_key', 'acoustid_user_key', 'auth_token'];

function fieldElements(desc) {
    if (desc.selector) return Array.prototype.slice.call(document.querySelectorAll(desc.selector));
    const el = document.getElementById(desc.id);
    return el ? [el] : [];
}

/** Project one config value into its DOM element(s). */
function loadField(desc, config, savedFlags) {
    const elements = fieldElements(desc);
    if (!elements.length) return;
    const value = config[desc.key];

    if (desc.type === 'secret' || desc.type === 'sharedSecret') {
        const masked = value === '***MASKED***';
        savedFlags[desc.key] = masked;
        elements.forEach(el => {
            el.value = masked ? '' : (value || '');
            el.dataset.hasSavedKey = masked ? 'true' : 'false';
            if (masked) {
                if (desc.maskedPlaceholder) el.placeholder = desc.maskedPlaceholder;
            } else if (desc.plainPlaceholder) {
                el.placeholder = desc.plainPlaceholder;
            }
        });
        return;
    }

    elements.forEach(el => {
        switch (desc.type) {
            case 'bool': el.checked = !!value; break;
            case 'boolDefaultOn': el.checked = value !== false; break;
            case 'boolFromSelect': el.value = value ? 'true' : 'false'; break;
            case 'int':
                el.value = (value === undefined || value === null)
                    ? String(desc.default) : String(value);
                break;
            default:
                el.value = (value === undefined || value === null)
                    ? (desc.default || '') : String(value);
        }
    });
}

/** Read one descriptor back; masks become ***KEEP_EXISTING*** on save. */
function readField(desc, savedFlags) {
    const el = fieldElements(desc)[0];
    if (!el) return desc.default;
    let value;
    switch (desc.type) {
        case 'secret':
        case 'sharedSecret':
            value = String(el.value || '').trim();
            if (!value && savedFlags[desc.key]) return '***KEEP_EXISTING***';
            return value;
        case 'bool':
        case 'boolDefaultOn':
            return !!el.checked;
        case 'boolFromSelect':
            return el.value === 'true';
        case 'int': {
            const parsed = parseInt(el.value, 10);
            const base = isNaN(parsed) ? desc.default : parsed;
            return Math.min(desc.max, Math.max(desc.min, base));
        }
        case 'text':
            return desc.trim ? String(el.value).trim() : String(el.value);
        default:
            return el.value;
    }
}

/** Keep the config slice current as the user edits descriptor fields. */
function wireConfigField(desc) {
    fieldElements(desc).forEach(el => {
        if (el.dataset.configBound === 'true') return;
        el.dataset.configBound = 'true';
        const event = (el.tagName === 'SELECT' || el.type === 'checkbox') ? 'change' : 'input';
        el.addEventListener(event, () => {
            const flags = (CONFIG_STATE.get('config') || {}).__savedFlags || {};
            const patch = {};
            patch[desc.key] = readField(desc, flags);
            CONFIG_STATE.patch('config', patch, { source: 'dom', field: desc.key });
        });
    });
}

// Update quality presets based on format
function updateQualityPresets() {
    const format = document.getElementById('outputFormat').value;
    const qualitySelect = document.getElementById('quality');
    const qualityHelp = document.getElementById('qualityHelp');
    const currentValue = qualitySelect.value;
    
    qualitySelect.innerHTML = '';
    
    const presets = qualityPresets[format] || qualityPresets.mp3;
    presets.forEach(preset => {
        const option = document.createElement('option');
        option.value = preset.value;
        option.textContent = preset.label;
        qualitySelect.appendChild(option);
    });
    
    // Try to maintain selection if possible
    if (currentValue && Array.from(qualitySelect.options).some(opt => opt.value === currentValue)) {
        qualitySelect.value = currentValue;
    } else {
        // Select the recommended (last) option
        qualitySelect.selectedIndex = qualitySelect.options.length - 1;
    }
    
    // Update help text
    if (format === 'flac' || format === 'wav') {
        qualityHelp.textContent = 'Lossless format - no quality loss';
    } else {
        qualityHelp.textContent = 'Higher quality = larger file size';
    }
}

// Load configuration — descriptors project API values into the DOM and store
// them as the single config slice. Complex widgets project from that slice.
async function loadConfiguration() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();

        const savedFlags = {};
        CONFIG_FIELDS.forEach(desc => {
            if (desc.key === 'quality') return;  // applied after presets are built
            loadField(desc, config, savedFlags);
        });
        updateQualityPresets();
        loadField(QUALITY_FIELD, config, savedFlags);
        CONFIG_FIELDS.forEach(wireConfigField);

        // Historical projection with no persisted key: keep it out of the
        // save payload so the server contract does not change.
        const plexUrl = document.getElementById('plexUrl');
        if (plexUrl) plexUrl.value = config.plex_url || '';

        CONFIG_STATE.set('config', Object.assign({}, config, { __savedFlags: savedFlags }),
            { source: 'api' });

        // Metadata providers + path mappings are projected from the config
        // snapshot; their drag/toggle state is written back by their modules.
        loadMetadataProviders(config);
        const pathMappings = config.lidarr_path_mapping || {};
        Object.entries(pathMappings).forEach(([microPath, lidarrPath]) => {
            addPathMapping(lidarrPath, microPath);
        });

        // Source priorities now come from state (see sources.js). This also
        // creates the YouTube cookie field, so (re)apply its descriptor now.
        loadSourcePriorities(config.source_priorities || []);
        loadField(COOKIES_FIELD, config, savedFlags);
        wireConfigField(COOKIES_FIELD);

        const youtubeCookieFields = Array.prototype.slice.call(
            document.querySelectorAll('.youtube-cookies-field'));
        if (youtubeCookieFields.length) {
            youtubeCookieFields.forEach(field => {
                if (field.dataset.cookieSync === 'true') return;
                field.dataset.cookieSync = 'true';
                field.addEventListener('input', () => {
                    youtubeCookieFields.forEach(other => {
                        if (other !== field) other.value = field.value;
                    });
                });
            });
            checkYouTubeLoginStatus();
            setTimeout(checkYouTubeLoginStatus, 300);
        }
    } catch (error) {
        console.error('Error loading configuration:', error);
        showNotification('Error loading configuration', 'error');
    }
}

// Save configuration — serialized from the config slice through descriptors.
async function saveConfiguration() {
    try {
        showNotification('Saving configuration...', 'info');

        const apiKeyField = document.getElementById('lidarrApiKey');
        const apiKeyValue = String(apiKeyField.value || '').trim();

        // Descriptor bindings keep the slice current as users edit; refresh
        // once more here so a save always serializes the same source of truth.
        const current = CONFIG_STATE.get('config') || {};
        const savedFlags = Object.assign({}, current.__savedFlags || {});
        const patch = {};
        CONFIG_FIELDS.forEach(desc => { patch[desc.key] = readField(desc, savedFlags); });
        CONFIG_STATE.patch('config', patch, { source: 'dom' });

        const cfg = CONFIG_STATE.get('config');
        const config = {};
        CONFIG_FIELDS.forEach(desc => {
            if (desc.type !== 'sharedSecret') config[desc.key] = cfg[desc.key];
        });
        Object.assign(config, getMetadataProviderState());
        config.lidarr_path_mapping = getPathMappings();
        config.source_priorities = getSourcePriorities();   // state, not DOM text
        config.youtube_cookies = cfg[COOKIES_FIELD.key];

        const loggable = Object.assign({}, config);
        for (const key of SECRET_KEYS) {
            if (loggable[key] && loggable[key] !== '***KEEP_EXISTING***') {
                loggable[key] = '***';
            }
        }
        console.log('Saving configuration:', loggable);

        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data = await response.json();

        if (data.success) {
            showNotification('✅ Configuration saved successfully!', 'success');

            // If we saved a new API key, update the marker and clear the field.
            if (apiKeyValue) {
                savedFlags.lidarr_api_key = true;
                CONFIG_STATE.patch('config', { __savedFlags: savedFlags },
                    { source: 'save' });
                apiKeyField.dataset.hasSavedKey = 'true';
                apiKeyField.placeholder = 'API Key configured (enter new key to change)';
                apiKeyField.value = '';
            }
        } else {
            showNotification('❌ Error: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        console.error('Error saving configuration:', error);
        showNotification('❌ Failed to save: ' + error.message, 'error');
    }
}

// Test Lidarr connection
async function testLidarrConnection() {
    const urlField = document.getElementById('lidarrUrl');
    const apiKeyField = document.getElementById('lidarrApiKey');
    const resultDiv = document.getElementById('connectionResult');
    
    let url = urlField.value.trim();
    let apiKey = apiKeyField.value.trim();
    
    // The server resolves the saved key from its own config; never fetch it.
    if (!apiKey && apiKeyField.dataset.hasSavedKey === 'true') {
        apiKey = '***KEEP_EXISTING***';
    }
    
    if (!url || !apiKey) {
        resultDiv.className = 'message error';
        resultDiv.textContent = 'Please enter both URL and API key';
        return;
    }
    
    resultDiv.className = 'message info';
    resultDiv.textContent = 'Testing connection...';
    
    try {
        const response = await fetch('/api/test-lidarr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ lidarr_url: url, lidarr_api_key: apiKey })
        });
        
        const data = await response.json();
        
        if (data.success) {
            resultDiv.className = 'message success';
            resultDiv.textContent = '✅ ' + data.message;
        } else {
            resultDiv.className = 'message error';
            resultDiv.textContent = '❌ ' + data.error;
        }
    } catch (error) {
        console.error('Error testing connection:', error);
        resultDiv.className = 'message error';
        resultDiv.textContent = '❌ Connection failed: ' + error.message;
    }
}

// Thin wrapper around the single ToastManager (no second toast implementation).
function showYouTubeToast(message, type) {
    return window.Blissful.toasts.youtube(message, type);
}

// Optional embedded YouTube login (compose --profile youtube-login).
async function checkYouTubeLoginStatus() {
    try {
        const res = await fetch('/api/youtube/login/status');
        const data = await res.json();
        document.querySelectorAll('.youtube-login-status').forEach(el => {
            if (!data.available) {
                el.textContent = 'Login browser not enabled (optional profile).';
            } else if (data.relogin_required) {
                el.textContent = 'Session expired - login again.';
            } else if (data.active) {
                el.textContent = 'Browser open - finish sign-in in the window.';
            } else if (data.has_cookies) {
                el.textContent = 'Signed in.';
            } else {
                el.textContent = 'Not signed in.';
            }
        });
    } catch (e) {
        document.querySelectorAll('.youtube-login-status').forEach(el => {
            el.textContent = 'Login status unavailable.';
        });
    }
}

async function startYouTubeLogin() {
    const res = await fetch('/api/youtube/login/start', {method: 'POST'});
    const data = await res.json();
    if (!data.success) {
        showYouTubeToast(data.error || 'Could not start YouTube login', 'error');
        return;
    }
    const modal = document.getElementById('youtubeLoginModal');
    document.getElementById('youtubeLoginFrame').src = data.novnc_url;
    modal.style.display = 'flex';
    checkYouTubeLoginStatus();
}

async function finishYouTubeLogin() {
    const res = await fetch('/api/youtube/login/finish', {method: 'POST'});
    const data = await res.json();
    if (!data.success) {
        showYouTubeToast(data.error || 'Could not save YouTube cookies', 'error');
        return;
    }
    closeYouTubeLogin();
    showYouTubeToast(`YouTube login saved (${data.cookie_count} cookies)`, 'success');
    await loadConfiguration();
}

async function closeYouTubeLogin() {
    document.getElementById('youtubeLoginModal').style.display = 'none';
    document.getElementById('youtubeLoginFrame').src = 'about:blank';
    await fetch('/api/youtube/login/cancel', {method: 'POST'});
    checkYouTubeLoginStatus();
}

// Tracked timer instead of a bare setInterval.
document.addEventListener('DOMContentLoaded', () => {
    checkYouTubeLoginStatus();
    CONFIG_SCHED.start('youtubeStatus', checkYouTubeLoginStatus, 120000);
});

// Publish the descriptor-driven config API into the Blissful namespace.
window.Blissful.register({
    updateQualityPresets: updateQualityPresets,
    loadConfiguration: loadConfiguration,
    saveConfiguration: saveConfiguration,
    testLidarrConnection: testLidarrConnection,
    showYouTubeToast: showYouTubeToast,
    checkYouTubeLoginStatus: checkYouTubeLoginStatus,
    startYouTubeLogin: startYouTubeLogin,
    finishYouTubeLogin: finishYouTubeLogin,
    closeYouTubeLogin: closeYouTubeLogin,
    CONFIG_FIELDS: CONFIG_FIELDS,
    readField: readField,
    loadField: loadField
});
