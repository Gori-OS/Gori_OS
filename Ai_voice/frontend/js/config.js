/**
 * Nova OS — Environment & API Configuration
 * Auto-detects local vs remote (Vercel / Render) deployment.
 * Supports manual override via ?api=<url> query param or localStorage 'goori_api_base'.
 */
(function(window) {
    'use strict';

    if (typeof window === 'undefined') return;

    // 1. Check overrides: ?api=<url> or localStorage 'goori_api_base'
    let queryOverride = null;
    try {
        if (window.location && window.location.search) {
            const params = new URLSearchParams(window.location.search);
            queryOverride = params.get('api');
            if (queryOverride) {
                try {
                    localStorage.setItem('goori_api_base', queryOverride);
                } catch (e) {}
            }
        }
    } catch (e) {}

    let storageOverride = null;
    try {
        if (typeof localStorage !== 'undefined') {
            storageOverride = localStorage.getItem('goori_api_base');
        }
    } catch (e) {}

    // 2. Detect local vs cloud environment
    const hostname = (window.location && window.location.hostname) ? window.location.hostname.toLowerCase() : 'localhost';

    function checkIsLocal(host) {
        if (!host) return true;
        if (host === 'localhost' || host === '127.0.0.1' || host === '::1' || host === '[::1]' || host.endsWith('.local')) {
            return true;
        }
        // Private IPv4 ranges (RFC 1918)
        if (/^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
        if (/^192\.168\.\d{1,3}\.\d{1,3}$/.test(host)) return true;
        const match172 = host.match(/^172\.(\d{1,3})\.\d{1,3}\.\d{1,3}$/);
        if (match172) {
            const second = parseInt(match172[1], 10);
            if (second >= 16 && second <= 31) return true;
        }
        return false;
    }

    const isLocal = checkIsLocal(hostname);
    window.IS_LOCAL_ENV = isLocal;

    // Local uses relative same-origin calls (''); everywhere else points to Render
    const defaultApiBase = isLocal ? '' : 'https://gori-os.onrender.com';
    let activeApiBase = queryOverride || storageOverride || defaultApiBase;
    // Strip trailing slashes
    activeApiBase = activeApiBase ? activeApiBase.replace(/\/+$/, '') : '';

    window.API_BASE = activeApiBase;

    /**
     * Resolves an API path to the correct active backend URL.
     * Leaves external/absolute URLs untouched.
     */
    window.apiUrl = function(path) {
        if (!path) return activeApiBase || '';
        // If already an absolute http/https/blob/data/ws/wss URL, leave intact
        if (/^(https?:|wss?:|\/\/|blob:|data:)/i.test(path)) {
            return path;
        }
        const normalizedPath = path.startsWith('/') ? path : '/' + path;
        return activeApiBase ? `${activeApiBase}${normalizedPath}` : normalizedPath;
    };

    /**
     * Resolves the WebSocket URL for bridge connection.
     * Local: alternates between ws://host:7891/ws and ws://host:7890/ws.
     * Everywhere else: single wss://gori-os.onrender.com/ws URL.
     */
    window.wsUrl = function(reconnectAttempts) {
        // If explicit custom API_BASE override is set, derive WS from it
        if (queryOverride || storageOverride) {
            try {
                const parsed = new URL(activeApiBase);
                const proto = parsed.protocol === 'https:' ? 'wss:' : 'ws:';
                return `${proto}//${parsed.host}/ws`;
            } catch (e) {}
        }

        if (isLocal) {
            const host = (window.location && window.location.hostname) ? window.location.hostname : 'localhost';
            const attempts = (typeof reconnectAttempts === 'number') ? reconnectAttempts : 0;
            const targetPort = (attempts % 2 === 0) ? 7891 : (window.location.port || 7890);
            const isHttps = (window.location && window.location.protocol === 'https:');
            const proto = isHttps ? 'wss:' : 'ws:';
            return `${proto}//${host}:${targetPort}/ws`;
        }

        // Everywhere else (Vercel, Render /desktop/)
        return 'wss://gori-os.onrender.com/ws';
    };

    // Update pairing meta info UI text on DOM load
    function initMetaText() {
        const metaEl = document.getElementById('pairing-meta-info');
        if (metaEl) {
            if (isLocal) {
                metaEl.textContent = 'HTTP 7890 | WS 7891';
            } else {
                metaEl.textContent = 'Render: gori-os.onrender.com | WS: /ws';
            }
        }
    }

    if (typeof document !== 'undefined') {
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', initMetaText);
        } else {
            initMetaText();
        }
    }
})(typeof window !== 'undefined' ? window : this);
