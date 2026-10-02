/**
 * Nova OS Bridge Client
 * Communicates with FastAPI bridge backend over authenticated WebSocket and REST.
 */
class BridgeClient {
    constructor() {
        this.socket = null;
        this.reconnectAttempts = 0;
        this.isAuthenticated = false;
        try {
            this.localToken = localStorage.getItem('novaos_token') || null;
        } catch (e) {
            this.localToken = null;
        }
        this._retryingAuth = false;
        this.activePhoneCount = 0;
        this.wsPort = 7891; // Default WS port per canonical contract
        
        // Listeners for command results (Terminal app, Voice app, etc.)
        this.commandListeners = new Set();
        this.statusListeners = new Set();
        
        this.init();
    }

    async init() {
        await this.fetchPairingStatus();
        await this.fetchDiagnostics();
        this.connect();

        // Periodic pairing status and diagnostics sync (reduced to 15s when idle; WebSocket pushes live updates)
        setInterval(async () => {
            if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
                await this.fetchPairingStatus();
            }
            if (window.WindowManager && window.WindowManager.windows && window.WindowManager.windows.has('settings')) {
                await this.fetchDiagnostics();
            }
        }, 15000);
    }

    async fetchPairingStatus(retryCount = 0, maxRetries = 10) {
        const contactText = document.getElementById('pairing-contact-text');
        const statusLabel = document.getElementById('pairing-status-label');
        try {
            const url = (typeof window.apiUrl === 'function') ? window.apiUrl('/pair/status') : '/pair/status';
            const controller = (typeof AbortController !== 'undefined') ? new AbortController() : null;
            const timeoutId = controller ? setTimeout(() => controller.abort(), 12000) : null;
            const res = await fetch(url, controller ? { signal: controller.signal } : {});
            if (timeoutId) clearTimeout(timeoutId);

            if (res.ok) {
                const data = await res.json();
                this.localToken = data.local_token;
                if (data.local_token) {
                    try {
                        localStorage.setItem('novaos_token', data.local_token);
                    } catch (e) {}
                }
                this.updatePairingUi(data);
                return data;
            } else if (res.status >= 500 && retryCount < maxRetries) {
                throw new Error(`Server returned HTTP ${res.status}`);
            }
        } catch (e) {
            console.warn(`[BridgeClient] Failed to fetch pairing status (attempt ${retryCount + 1}/${maxRetries}):`, e);
            if (retryCount < maxRetries) {
                if (contactText) contactText.textContent = 'Server waking up, please wait…';
                if (statusLabel && !this.isAuthenticated) statusLabel.textContent = 'Server waking up, please wait…';
                const delay = Math.min(2000 * Math.pow(1.3, retryCount), 10000);
                await new Promise(r => setTimeout(r, delay));
                return this.fetchPairingStatus(retryCount + 1, maxRetries);
            }
        }
        return null;
    }

    async fetchDiagnostics() {
        try {
            const url = (typeof window.apiUrl === 'function') ? window.apiUrl('/api/network/diagnostics') : '/api/network/diagnostics';
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                this.updateDiagnosticsUi(data);
                return data;
            }
        } catch (e) {
            console.warn('[BridgeClient] Failed to fetch diagnostics:', e);
        }
        return null;
    }

    updateDiagnosticsUi(data) {
        if (!data) return;
        const contactContainer = document.getElementById('pairing-contact-display');
        const contactText = document.getElementById('pairing-contact-text');
        const metaInfo = document.getElementById('pairing-meta-info');

        if (contactText && contactContainer) {
            if (data.last_phone_contact) {
                const c = data.last_phone_contact;
                contactText.textContent = `Last phone contact: ${c.ip} ${c.method} ${c.path} ${c.status} (${c.seconds_ago}s ago)`;
                contactContainer.className = 'pairing-contact-display has-contact';
            } else {
                contactText.textContent = 'No phone has reached this PC yet. Check Wi-Fi, firewall and router isolation';
                contactContainer.className = 'pairing-contact-display no-contact';
            }
        }

        if (metaInfo) {
            const wsStatus = data.ws_bound ? '7891 [OK]' : '7891 [FALLBACK 7890]';
            const fwStatus = data.firewall_rules_ok ? 'FW [OK]' : 'FW [BLOCKED]';
            metaInfo.textContent = `HTTP ${data.http_port} | WS ${wsStatus} | ${fwStatus}`;
        }
    }

    updatePairingUi(data) {
        if (!data) return;
        const pinEl = document.getElementById('pairing-pin-display');
        const trayPin = document.getElementById('tray-pin-val');
        const timerEl = document.getElementById('pairing-timer-display');
        const statusLabel = document.getElementById('pairing-status-label');
        const statusDot = document.getElementById('tray-status-dot');

        if (pinEl) pinEl.textContent = data.code || '------';
        if (trayPin) trayPin.textContent = data.code || '------';

        if (timerEl && data.expires_in !== undefined) {
            const m = Math.floor(data.expires_in / 60).toString().padStart(2, '0');
            const s = (data.expires_in % 60).toString().padStart(2, '0');
            timerEl.textContent = `Expires in: ${m}:${s}`;
        }

        const phoneCount = data.paired_devices_count || 0;
        if (statusLabel && statusDot) {
            if (phoneCount > 0 || this.activePhoneCount > 0) {
                statusLabel.textContent = `Phone paired (${this.activePhoneCount} active)`;
                statusDot.className = 'status-indicator connected';
            } else {
                statusLabel.textContent = 'Waiting for phone pairing...';
                statusDot.className = 'status-indicator disconnected';
            }
        }

        const attemptEl = document.getElementById('pairing-attempt-display');
        if (attemptEl) {
            if (data.latest_attempt && data.latest_attempt.message) {
                attemptEl.textContent = data.latest_attempt.message;
                attemptEl.className = `pairing-attempt-display ${data.latest_attempt.result || ''}`;
                attemptEl.style.display = 'block';
            } else {
                attemptEl.style.display = 'none';
            }
        }
    }

    connect() {
        const wsUrl = (typeof window.wsUrl === 'function')
            ? window.wsUrl(this.reconnectAttempts)
            : `ws://${window.location.hostname || 'localhost'}:${(this.reconnectAttempts % 2 === 0) ? 7891 : (window.location.port || 7890)}/ws`;

        try {
            console.log(`[BridgeClient] Connecting to ${wsUrl}...`);
            this.socket = new WebSocket(wsUrl);

            this.socket.onopen = () => {
                console.log(`[BridgeClient] WebSocket open on ${wsUrl}`);
                this.reconnectAttempts = 0;
                this.addHistory('system', 'Connected to Windows AI Bridge.');

                // Perform authentication handshake with local session token
                if (this.localToken) {
                    this.authenticate(this.localToken);
                } else {
                    this.fetchPairingStatus().then((status) => {
                        if (status && status.local_token) {
                            this.authenticate(status.local_token);
                        }
                    });
                }
            };

            this.socket.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    this.handleMessage(message);
                } catch (err) {
                    console.error('[BridgeClient] Error parsing incoming message:', err);
                }
            };

            this.socket.onclose = () => {
                this.isAuthenticated = false;
                this.updateSysMic();
                this.scheduleReconnect();
            };

            this.socket.onerror = (error) => {
                console.warn('[BridgeClient] WebSocket Error:', error);
            };
        } catch (e) {
            this.scheduleReconnect();
        }
    }

    authenticate(token) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            const authPayload = {
                type: 'authenticate',
                token: token,
                protocol_version: '1.0'
            };
            this.socket.send(JSON.stringify(authPayload));
        }
    }

    scheduleReconnect() {
        const timeout = Math.min(1000 * Math.pow(1.5, this.reconnectAttempts), 15000);
        this.reconnectAttempts++;
        if (this.reconnectAttempts > 1) {
            const statusLabel = document.getElementById('pairing-status-label');
            if (statusLabel && !this.isAuthenticated) {
                statusLabel.textContent = 'Server waking up, please wait…';
            }
        }
        setTimeout(() => this.connect(), timeout);
    }

    handleMessage(message) {
        // 1. Auth Result
        if (message.type === 'auth_result') {
            if (message.success) {
                this.isAuthenticated = true;
                console.log(`[BridgeClient] Authenticated successfully as ${message.device_id}`);
                this.addHistory('system', '✓ Windows Bridge Authenticated (v' + (message.version || '1.0') + ')');
                this.updateSysMic();
            } else {
                this.isAuthenticated = false;
                this.addHistory('system', `✕ Auth failed: ${message.error || 'Invalid token'}`, true);
                if (!this._retryingAuth) {
                    this._retryingAuth = true;
                    setTimeout(async () => {
                        const status = await this.fetchPairingStatus();
                        if (status && status.local_token) {
                            this.authenticate(status.local_token);
                        }
                        this._retryingAuth = false;
                    }, 1500);
                }
            }
        }

        // 2. Status Updates (clients connected, telemetry)
        if (message.type === 'status_update') {
            this.activePhoneCount = message.connected_clients || 0;
            this.updateSysMic();
            this.notifyStatusListeners(message);
            
            const statusLabel = document.getElementById('pairing-status-label');
            const statusDot = document.getElementById('tray-status-dot');
            if (statusLabel && statusDot) {
                if (this.activePhoneCount > 0) {
                    statusLabel.textContent = `Phone connected (${this.activePhoneCount} active)`;
                    statusDot.className = 'status-indicator connected';
                } else {
                    statusLabel.textContent = 'Waiting for phone pairing...';
                    statusDot.className = 'status-indicator disconnected';
                }
            }
        }

        // 3. Command Result
        if (message.type === 'command_result') {
            this.notifyCommandListeners(message);

            if (message.success) {
                const isPhoneSource = message.client_device === 'phone' || message.target_device === 'phone' || message.source === 'phone';
                const msgText = message.data?.message || 'Command executed';
                const execTime = message.data?.execution_time_ms ? ` (${message.data.execution_time_ms}ms)` : '';

                if (isPhoneSource) {
                    if (window.WindowManager) {
                        window.WindowManager.openApp('nova-voice');
                        window.WindowManager.focusWindow('nova-voice');
                    }
                    const userCmd = message.data?.command || 'Voice command from phone';
                    this.addHistory('user', `📱 ${userCmd}`);
                }

                this.addHistory('system', `✓ ${msgText}${execTime}`);

                // Execute action
                const action = message.data?.action;
                if (action) {
                    if (action.action === 'file.open') {
                        if (window.openFilePreview) {
                            window.openFilePreview(action.url || action.path, action.filename, action.file_type);
                        }
                    } else if (action.action === 'media.play' || action.action === 'file.play') {
                        if (window.openFilePreview) {
                            window.openFilePreview(action.url || action.path, action.filename, action.file_type || 'audio', { forcePlay: true });
                        } else if (window.playAudioPlayback) {
                            window.playAudioPlayback();
                        }
                    } else if (action.action === 'media.pause') {
                        if (window.pauseAudioPlayback) {
                            window.pauseAudioPlayback();
                        }
                    } else if (action.action === 'media.resume') {
                        if (window.playAudioPlayback) {
                            window.playAudioPlayback();
                        }
                    } else if (action.action === 'app.open' && action.target) {
                        if (action.target === 'browser') {
                            if (window.browserNavigate && (action.url || action.query)) {
                                window.browserNavigate(action.url || action.query, action.display_url);
                            } else if (window.WindowManager) {
                                window.WindowManager.openApp('browser');
                            }
                        } else if (window.WindowManager) {
                            window.WindowManager.openApp(action.target);
                        }
                    } else if (action.action === 'app.close' && action.target) {
                        if (window.WindowManager) {
                            window.WindowManager.closeWindow(action.target);
                        }
                    } else if (action.action && action.action.startsWith('workspace.')) {
                        if (window.WindowManager) {
                            window.WindowManager.openApp('workspace');
                        }
                        if (window.Workspace) {
                            if (action.action === 'workspace.add_task') {
                                window.Workspace.switchTab('planner');
                                window.Workspace.addTask(action.text, action.priority);
                            } else if (action.action === 'workspace.complete_task') {
                                window.Workspace.switchTab('planner');
                                window.Workspace.completeTask(action.text);
                            } else if (action.action === 'workspace.delete_task') {
                                window.Workspace.switchTab('planner');
                                window.Workspace.deleteTask(action.text);
                            } else if (action.action === 'workspace.create_doc') {
                                window.Workspace.switchTab('documents');
                                window.Workspace.createDoc(action.title);
                            } else if (action.action === 'workspace.open_doc') {
                                window.Workspace.switchTab('documents');
                                window.Workspace.openDoc(action.title);
                            } else if (action.action === 'workspace.create_sheet') {
                                window.Workspace.switchTab('sheets');
                                window.Workspace.createSheet(action.title);
                            } else if (action.action === 'workspace.set_cell') {
                                window.Workspace.switchTab('sheets');
                                window.Workspace.setCellValue(action.cell, action.value);
                            } else if (action.action === 'workspace.switch_tab') {
                                window.Workspace.switchTab(action.tab);
                            }
                        }
                    } else if (action.action === 'file.processed') {
                        // Complete conversion animation in web app
                        if (window.finishConversionAnimation) {
                            window.finishConversionAnimation({
                                success: true,
                                ...action
                            });
                        }
                        // Refresh file/folder UI so the generated result immediately appears in Output
                        if (window.loadFilesList) {
                            window.loadFilesList().then(() => {
                                if (window.navigateToFolder) {
                                    window.navigateToFolder('output');
                                }
                            });
                        }
                        if (window.WindowManager && window.WindowManager.windows.has('files')) {
                            window.WindowManager.focusWindow('files');
                        }
                    } else if (action.action === 'file.deleted') {
                        if (window.loadFilesList) {
                            window.loadFilesList();
                        }
                    } else if (action.action === 'system.screenshot') {
                        this.triggerScreenshotFlash();
                    } else if (action.action && action.action.startsWith('phone.')) {
                        this.addHistory('system', `📱 [Phone] ${action.action.replace('phone.', '').toUpperCase()} executed successfully`);
                    }
                }
            } else {
                const errText = message.data?.message || message.error || 'Command failed';
                this.addHistory('system', `✕ ${errText}`, true);
                if (window.finishConversionAnimation) {
                    window.finishConversionAnimation({
                        success: false,
                        error: errText,
                        ...message.data
                    });
                }
            }
        }
    }

    triggerScreenshotFlash() {
        const flash = document.getElementById('screenshot-flash');
        if (flash) {
            flash.classList.add('active');
            setTimeout(() => {
                flash.classList.remove('active');
            }, 300);
        }
    }

    updateSysMic() {
        const micEl = document.getElementById('sys-mic');
        if (!micEl) return;
        if (this.activePhoneCount > 0) {
            micEl.textContent = `MIC ACTIVE (${this.activePhoneCount})`;
            micEl.className = 'tray-item connected';
        } else if (this.isAuthenticated) {
            micEl.textContent = 'MIC STANDBY';
            micEl.className = 'tray-item';
        } else {
            micEl.textContent = 'BRIDGE OFFLINE';
            micEl.className = 'tray-item';
        }
    }

    sendCommand(commandText, callback) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            this.addHistory('system', '✕ Cannot send: Bridge disconnected', true);
            if (callback) callback({ success: false, data: { message: 'Bridge disconnected' } });
            return;
        }

        const requestId = 'cmd-' + Date.now() + '-' + Math.random().toString(36).substr(2, 5);
        const envelope = {
            type: 'command',
            request_id: requestId,
            protocol_version: '1.0',
            timestamp: Date.now(),
            data: {
                command: commandText,
                type: 'text'
            }
        };

        this.socket.send(JSON.stringify(envelope));
        this.addHistory('user', commandText);

        // Detect conversion commands to trigger smooth conversion animation immediately
        const convMatch = (commandText || '').match(/\b(?:convert|transform|turn|change|make)\s+(.+?)\s+(?:to|into|as|a|an)\s+([a-zA-Z0-9]+)\b/i);
        if (convMatch) {
            const rawSrc = convMatch[1].trim();
            const tgt = convMatch[2].trim().toUpperCase();
            let src = 'FILE';
            if (rawSrc.includes('.')) {
                src = rawSrc.split('.').pop().trim().toUpperCase();
            } else if (rawSrc.toLowerCase().includes('dot ')) {
                src = rawSrc.toLowerCase().split('dot ').pop().trim().toUpperCase();
            }
            if (window.showConversionAnimation) {
                window.showConversionAnimation(src, tgt, rawSrc);
            }
        }

        if (callback) {
            const listener = (res) => {
                if (res.request_id === requestId) {
                    this.commandListeners.delete(listener);
                    callback(res);
                }
            };
            this.commandListeners.add(listener);
        }
    }

    onCommandResult(listener) {
        this.commandListeners.add(listener);
    }

    onStatusUpdate(listener) {
        this.statusListeners.add(listener);
    }

    notifyCommandListeners(result) {
        this.commandListeners.forEach((listener) => {
            try { listener(result); } catch (e) { console.error(e); }
        });
    }

    notifyStatusListeners(status) {
        this.statusListeners.forEach((listener) => {
            try { listener(status); } catch (e) { console.error(e); }
        });
    }

    addHistory(sender, text, isError = false) {
        const historyEl = document.getElementById('nova-history');
        if (!historyEl) return;

        const entry = document.createElement('div');
        entry.className = `history-entry ${sender}${isError ? ' error' : ''}`;
        entry.textContent = text;
        historyEl.appendChild(entry);
        historyEl.scrollTop = historyEl.scrollHeight;
    }
}

window.BridgeClient = new BridgeClient();
