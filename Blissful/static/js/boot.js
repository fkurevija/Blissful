/**
 * Blissful boot module — the single owner of window.Blissful.
 *
 * Loaded before every other static/js file. It provides the three cross-cutting
 * seams used by the rest of the UI:
 *   1. Blissful.state    — tiny slice store. The DOM is a projection of it.
 *   2. Blissful.scheduler — tracked timers, in-flight guards, monotonic seq ids.
 *   3. Blissful.toasts   — one ToastManager (notifications, YouTube toast,
 *                          per-run progress lease).
 *
 * Other scripts register their public functions with Blissful.register(); thin
 * global aliases for legacy inline onclick="..." handlers are installed on
 * DOMContentLoaded, after all scripts have registered.
 */
'use strict';
(function (global) {
    if (global.Blissful && global.Blissful.__booted) return;

    const Blissful = global.Blissful || (global.Blissful = {});
    Blissful.__booted = true;

    /* ---------------------------------------------------------------- *
     * 1. State store — one owner per slice, never the DOM.
     * ---------------------------------------------------------------- */
    const slices = {
        config: {},
        jobs: [],
        wantedRun: {
            active: null,
            runs: {},
            lastActivity: null,
            settings: {}
        },
        details: {
            jobId: null,
            // Map of log-entry key -> true. Kept outside the DOM so expanding a
            // Download Attempts section survives every poll.
            openKeys: Object.create(null),
            filter: { text: '', failuresOnly: false },
            plainText: '',
            markdown: '',
            selectionPaused: false
        },
        toasts: {}
    };
    const listeners = Object.create(null);

    function emit(name, meta) {
        (listeners[name] || []).forEach(fn => {
            try { fn(slices[name], meta); }
            catch (e) { console.error('[Blissful] state listener failed for ' + name, e); }
        });
    }

    const store = {
        get(name) { return slices[name]; },
        set(name, value, meta) { slices[name] = value; emit(name, meta); return value; },
        patch(name, partial, meta) {
            if (!slices[name]) slices[name] = {};
            Object.assign(slices[name], partial);
            emit(name, meta);
            return slices[name];
        },
        subscribe(name, fn) {
            (listeners[name] || (listeners[name] = [])).push(fn);
            return () => { listeners[name] = (listeners[name] || []).filter(f => f !== fn); };
        },
        has(name) { return Object.prototype.hasOwnProperty.call(slices, name); }
    };
    Blissful.state = store;

    /* ---------------------------------------------------------------- *
     * 2. Scheduler — tracked timers + in-flight guards + sequence ids.
     *
     * Every poll channel (jobs, details, wantedStatus, youtubeStatus) owns a
     * monotonically increasing seq. A response is only applied when its token
     * is still current, so an in-flight slow response can never overwrite a
     * newer one. Only one task per channel may be in flight at a time.
     * ---------------------------------------------------------------- */
    const channels = Object.create(null);

    function channel(name) {
        return channels[name] || (channels[name] = {
            name: name,
            seq: 0,
            inFlight: false,
            timer: null,
            timeout: null,
            paused: false,
            ticks: 0
        });
    }

    const scheduler = {
        channel: channel,
        next(name) { const c = channel(name); c.seq += 1; return c.seq; },
        isCurrent(name, token) { return channel(name).seq === token; },
        begin(name) {
            const c = channel(name);
            if (c.inFlight) return false;
            c.inFlight = true;
            return true;
        },
        end(name) { channel(name).inFlight = false; },
        tick(name, task) {
            const c = channel(name);
            if (c.paused || c.inFlight) return false;
            c.inFlight = true;
            c.ticks += 1;
            Promise.resolve()
                .then(() => task())
                .catch(e => console.error('[Blissful] poll "' + name + '" failed', e))
                .then(() => { c.inFlight = false; });
            return true;
        },
        start(name, task, intervalMs, opts) {
            opts = opts || {};
            this.stop(name);
            const c = channel(name);
            c.timer = global.setInterval(() => { this.tick(name, task); }, intervalMs);
            if (opts.immediate !== false) this.tick(name, task);
            return c.timer;
        },
        stop(name) {
            const c = channel(name);
            if (c.timer) { clearInterval(c.timer); c.timer = null; }
            c.paused = false;
            c.inFlight = false;
        },
        pause(name) { channel(name).paused = true; },
        resume(name) { channel(name).paused = false; },
        isPaused(name) { return channel(name).paused; },
        isRunning(name) { return !!channel(name).timer; },
        // Single tracked timeout per name; reused for toast dismissal and the
        // progress poll's 1.5 s sleep so no orphan timer survives a new run.
        schedule(name, fn, ms) {
            const c = channel(name);
            if (c.timeout) clearTimeout(c.timeout);
            c.timeout = global.setTimeout(() => { c.timeout = null; fn(); }, ms);
            return c.timeout;
        },
        cancelSchedule(name) {
            const c = channel(name);
            if (c.timeout) { clearTimeout(c.timeout); c.timeout = null; }
        },
        status() {
            const out = {};
            Object.keys(channels).forEach(k => {
                const c = channels[k];
                out[k] = { seq: c.seq, inFlight: c.inFlight, paused: c.paused, running: !!c.timer, ticks: c.ticks };
            });
            return out;
        }
    };
    Blissful.scheduler = scheduler;

    /* ---------------------------------------------------------------- *
     * 3. ToastManager — replaces the four old toast lifecycles.
     * ---------------------------------------------------------------- */
    const WANTED_TOAST_ID = 'wanted-toast-active';
    let leaseSeq = 0;

    function setVisible(el, visible) {
        if (el) el.style.display = visible ? 'inline-block' : 'none';
    }

    const toasts = {
        /** Notification strip (#notification) used across the app. */
        notify(message, type) {
            type = type || 'info';
            const el = document.getElementById('notification');
            if (!el) return;
            el.textContent = message;
            el.className = 'notification ' + type + ' show';
            scheduler.schedule('toast:notification', () => el.classList.remove('show'), 3000);
        },

        /** Small YouTube-login toast (#youtube-login-toast). */
        youtube(message, type) {
            let el = document.getElementById('youtube-login-toast');
            if (!el) {
                el = document.createElement('div');
                el.id = 'youtube-login-toast';
                el.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:10001;padding:12px 16px;border-radius:8px;color:white;box-shadow:0 4px 16px rgba(0,0,0,.3)';
                document.body.appendChild(el);
            }
            el.textContent = message;
            el.style.background = type === 'error' ? '#b91c1c' : '#047857';
            el.style.display = 'block';
            scheduler.schedule('toast:youtube', () => { el.style.display = 'none'; }, 5000);
        },

        /** The one sticky wanted-run toast. DOM markup is identical to before. */
        ensureWantedElement() {
            let el = document.getElementById(WANTED_TOAST_ID);
            if (el) return el;
            el = document.createElement('div');
            el.id = WANTED_TOAST_ID;
            el.className = 'wanted-toast';
            el.innerHTML = '<span class="wanted-toast-dot"></span><span class="wanted-toast-text"></span>' +
                '<button type="button" class="wanted-toast-cancel">Cancel</button>' +
                '<button type="button" class="wanted-toast-details" style="display:none">View details →</button>' +
                '<button type="button" class="wanted-toast-link" style="display:none">View downloads →</button>';

            const link = el.querySelector('.wanted-toast-link');
            link.addEventListener('click', () => {
                const fn = Blissful.api.showDownloadsTab;
                if (fn) fn();
            });
            const details = el.querySelector('.wanted-toast-details');
            details.addEventListener('click', () => {
                const fn = Blissful.api.openLatestJobDetails;
                if (fn) fn(); else if (Blissful.api.showDownloadsTab) Blissful.api.showDownloadsTab();
            });
            const cancel = el.querySelector('.wanted-toast-cancel');
            cancel.addEventListener('click', async () => {
                const api = Blissful.api.wantedApi;
                if (!api) return;
                try {
                    const data = await api('/api/wanted/cancel', { method: 'POST', body: '{}' });
                    cancel.disabled = true;
                    if (data && data.cancelled === false) {
                        toasts.finishRun(toasts.currentLease(), 'No active run to cancel', 'info', true);
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
            const isMobile = () => !global.matchMedia || global.matchMedia('(max-width: 768px)').matches;
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
            if (global.matchMedia) {
                const query = global.matchMedia('(max-width: 768px)');
                const expandOnDesktop = change => {
                    if (!change.matches) el.classList.remove('wanted-toast-collapsed');
                };
                if (query.addEventListener) query.addEventListener('change', expandOnDesktop);
                else if (query.addListener) query.addListener(expandOnDesktop);
            }
            document.body.appendChild(el);
            return el;
        },

        currentLease() { return store.get('toasts')[WANTED_TOAST_ID] || null; },
        isCurrent(lease) {
            return !!lease && store.get('toasts')[WANTED_TOAST_ID] === lease && !lease.done;
        },

        /** Start a new per-run lease (one lease per visible run). */
        acquireLease(label) {
            scheduler.cancelSchedule('toast:' + WANTED_TOAST_ID);
            const lease = {
                id: ++leaseSeq,
                label: label,
                startedAt: Date.now(),
                done: false,
                sawActive: false,
                busySeen: true
            };
            const all = Object.assign({}, store.get('toasts'));
            all[WANTED_TOAST_ID] = lease;
            store.set('toasts', all, { reason: 'lease:acquired' });
            this.ensureWantedElement();
            this.updateRun(lease, label + ' — starting…', 'info');
            return lease;
        },

        /** Called by beginWantedProgress(): reuse a live lease or open a new one. */
        beginRun(label) {
            const live = this.currentLease();
            if (live && !live.done) {
                this.updateRun(live, label + ' — starting…', 'info');
                return live;
            }
            const lease = this.acquireLease(label);
            const poll = Blissful.api.pollWantedProgress;
            if (poll) poll(lease);
            return lease;
        },

        updateRun(lease, text, type) {
            if (!this.isCurrent(lease)) return;
            const el = this.ensureWantedElement();
            el.dataset.type = type || 'info';
            const node = el.querySelector('.wanted-toast-text');
            if (node) node.textContent = text;
        },

        /** Finish a lease: terminal text, hide Cancel, reveal links, auto-remove. */
        finishRun(lease, message, type, showLink) {
            if (!this.isCurrent(lease)) return;
            const el = this.ensureWantedElement();
            lease.done = true;
            el.dataset.type = type || 'info';
            const node = el.querySelector('.wanted-toast-text');
            if (node) node.textContent = message;
            setVisible(el.querySelector('.wanted-toast-link'), !!showLink);
            setVisible(el.querySelector('.wanted-toast-details'), !!showLink);
            setVisible(el.querySelector('.wanted-toast-cancel'), false);
            scheduler.schedule('toast:' + WANTED_TOAST_ID, () => {
                const current = document.getElementById(WANTED_TOAST_ID);
                if (current) current.remove();
                const all = Object.assign({}, store.get('toasts'));
                if (all[WANTED_TOAST_ID] === lease) {
                    delete all[WANTED_TOAST_ID];
                    store.set('toasts', all, { reason: 'lease:expired' });
                }
            }, type === 'error' ? 8000 : 5000);
        },

        /** Per-status reconciliation: open a lease for a newly seen run. */
        syncRun(status) {
            const active = status && status.active;
            const lease = this.currentLease();
            if (active) {
                if (!lease || lease.done) {
                    const label = active.kind === 'cleanup'
                        ? 'Cleaning stale torrents' : 'Searching wanted albums';
                    const next = this.acquireLease(label);
                    const poll = Blissful.api.pollWantedProgress;
                    if (poll) poll(next);
                }
            } else if (lease) {
                // Mirror the old wantedActiveShown = false: allow a future
                // status to start a fresh lease, but let the current lease's
                // own poll finish with the correct "finished/cancelled" text.
                lease.busySeen = false;
            }
        }
    };
    Blissful.toasts = toasts;

    /* ---------------------------------------------------------------- *
     * 4. Registry + boundary aliases for legacy inline handlers.
     * ---------------------------------------------------------------- */
    const api = Object.create(null);
    Blissful.api = api;
    Blissful.register = function register(exports) {
        Object.keys(exports).forEach(name => {
            api[name] = exports[name];
            Blissful[name] = exports[name];
        });
        return Blissful;
    };

    // Only these names are exposed back to inline HTML handlers. All are thin
    // aliases of Blissful.api entries; nothing new becomes a module global.
    const ALIASES = [
        'openTab', 'toggleSection', 'checkHealth',
        'showNotification', 'showYouTubeToast',
        'updateQualityPresets', 'loadConfiguration', 'saveConfiguration',
        'testLidarrConnection', 'checkYouTubeLoginStatus', 'startYouTubeLogin',
        'finishYouTubeLogin', 'closeYouTubeLogin',
        'addPathMapping', 'removePathMapping', 'getPathMappings', 'autoPopulatePathMapping',
        'loadSourcePriorities', 'populateAllSearchableSources', 'toggleSource',
        'filterSources', 'getSourcePriorities', 'loadSupportedSources',
        'wantedApi', 'applyWantedBusy', 'watchWantedBusy', 'runWantedSearch',
        'runStaleCleanup', 'beginWantedProgress', 'finishWantedToast',
        'loadWantedSettings', 'saveWantedSettings', 'loadWanted', 'loadStale',
        'showJobDetails', 'closeJobDetails', 'openLatestJobDetails',
        'loadJobs', 'renderJobs', 'sortJobsBy', 'retryJobTrack', 'showDownloadsTab',
        'initDocumentation'
        // documentationViewer is published by documentation.js as a live
        // accessor so inline handlers never see a stale instance.
    ];

    function installGlobalAliases() {
        ALIASES.forEach(name => {
            if (Object.prototype.hasOwnProperty.call(api, name)) {
                global[name] = api[name];
            }
        });
        global.Blissful = Blissful;
    }
    Blissful.installGlobalAliases = installGlobalAliases;
    document.addEventListener('DOMContentLoaded', installGlobalAliases, { once: true });
}(window));
