/**
 * Nova OS Helpers
 * File uploads, command input, Files app rendering, and Settings telemetry.
 */

// Speech-to-Text: Hands-free "Say task, then say OK to run" flow
const CONFIRM_PHRASES = [
    'ok', 'okay', 'okk', 'okey',
    'ok do it', 'okay do it', 'ok execute it', 'ok please',
    'yes ok', 'yes okay',
    'ओके', 'ठीक है', 'ओके कर दो', 'ठीक है कर दो', 'ok kar do'
];
window.CONFIRM_PHRASES = CONFIRM_PHRASES;

function normaliseVoiceText(text) {
    if (!text) return '';
    return text
        .toLowerCase()
        .replace(/[.,!?;:]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}
window.normaliseVoiceText = normaliseVoiceText;

function buildConfirmationRegex(phrases) {
    const sorted = [...phrases].sort((a, b) => b.length - a.length);
    const escaped = sorted.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    return new RegExp(`(?:^|\\s)(${escaped.join('|')})$`, 'i');
}
window.buildConfirmationRegex = buildConfirmationRegex;

const CONFIRM_REGEX = buildConfirmationRegex(CONFIRM_PHRASES);

function parseVoiceTurn(rawTurn) {
    const clean = normaliseVoiceText(rawTurn);
    if (!clean) return { type: 'empty', task: '', confirm: '' };

    const match = clean.match(CONFIRM_REGEX);
    if (!match) {
        return { type: 'C', task: clean, confirm: '' };
    }

    const confirmPhrase = match[1];
    const taskPart = clean.slice(0, match.index).trim();

    if (!taskPart) {
        return { type: 'A', task: '', confirm: confirmPhrase };
    } else {
        return { type: 'B', task: taskPart, confirm: confirmPhrase };
    }
}
window.parseVoiceTurn = parseVoiceTurn;

// Global File and Extension Normalization Layer for Speech Commands
const CORE_FILE_EXTENSIONS_JS = new Set([
    "jpg", "jpeg", "png", "gif", "webp", "svg", "bmp", "ico", "tif", "tiff", "heic",
    "pdf", "txt", "doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx", "rtf", "md",
    "json", "xml", "sql", "yml", "yaml", "toml", "ini", "conf", "log",
    "zip", "rar", "7z", "tar", "gz",
    "mp3", "wav", "ogg", "m4a", "flac", "aac",
    "mp4", "avi", "mkv", "mov", "webm", "m4v", "3gp",
    "exe", "apk", "bat", "sh",
    "py", "java", "js", "ts", "html", "css", "cpp", "c", "h"
]);

const NON_STEM_WORDS_JS = new Set([
    "to", "into", "as", "from", "of", "in", "on", "at", "by", "for", "with",
    "about", "between", "through", "over", "under", "above", "below", "and",
    "or", "but", "nor", "yet", "so", "than", "then", "after", "before", "while",
    "the", "a", "an", "this", "that", "these", "those",
    "my", "your", "his", "her", "its", "our", "their", "me", "you", "him", "us", "them",
    "is", "am", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    "open", "close", "show", "view", "display", "preview", "launch", "start", "exit", "quit",
    "delete", "remove", "erase", "trash", "convert", "change", "turn", "transform", "make",
    "switch", "compress", "shrink", "optimize", "reduce", "extract", "merge", "combine",
    "split", "resize", "watermark", "add", "set", "get", "put", "run", "stop", "send",
    "upload", "download", "copy", "move", "rename", "save", "load", "find", "search",
    "please", "nova", "hey", "hi", "hello", "thanks", "thank", "now", "again", "also",
    "just", "only", "very", "too", "well", "okay", "ok", "right"
]);

function normalizeSpokenFileCommand(text) {
    if (!text) return '';
    let s = text.trim();

    // Protect URLs, emails, decimals
    const placeholders = {};
    let phIdx = 0;
    const makePh = (val) => {
        const token = `__PH_${phIdx++}__`;
        placeholders[token] = val;
        return token;
    };

    s = s.replace(/https?:\/\/[^\s]+/g, makePh);
    s = s.replace(/\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b/g, makePh);
    s = s.replace(/\b\d+\.\d+\b/g, makePh);

    // Spelled out extension letters
    const spelledOut = [
        [/\b[jJ]\s+[pP]\s+[eE]\s+[gG]\b/g, 'jpeg'],
        [/\b[dD]\s+[oO]\s+[cC]\s+[xX]\b/g, 'docx'],
        [/\b[xX]\s+[lL]\s+[sS]\s+[xX]\b/g, 'xlsx'],
        [/\b[wW]\s+[eE]\s+[bB]\s+[pP]\b/g, 'webp'],
        [/\b[hH]\s+[tT]\s+[mM]\s+[lL]\b/g, 'html'],
        [/\b[jJ]\s+[sS]\s+[oO]\s+[nN]\b/g, 'json'],
        [/\b[jJ]\s+[pP]\s+[gG]\b/g, 'jpg'],
        [/\b[pP]\s+[nN]\s+[gG]\b/g, 'png'],
        [/\b[pP]\s+[dD]\s+[fF]\b/g, 'pdf'],
        [/\b[tT]\s+[xX]\s+[tT]\b/g, 'txt'],
        [/\b[cC]\s+[sS]\s+[vV]\b/g, 'csv'],
        [/\b[mM]\s+[pP]\s*4\b/g, 'mp4'],
        [/\b[mM]\s+[pP]\s*3\b/g, 'mp3'],
        [/\b[wW]\s+[aA]\s+[vV]\b/g, 'wav'],
        [/\b[pP]\s+[yY]\b/g, 'py'],
        [/\b[jJ]\s+[sS]\b/g, 'js'],
        [/\b[tT]\s+[sS]\b/g, 'ts'],
        [/\b[mM]\s+[dD]\b/g, 'md'],
        [/\b[cC]\s+[sS]\s+[sS]\b/g, 'css']
    ];
    for (const [re, repl] of spelledOut) {
        s = s.replace(re, repl);
    }

    // Spoken separator words: dot, point, period
    s = s.replace(/(?<=[a-zA-Z0-9_\-])\s*(?:dot|point|period)\s*(?=[a-zA-Z0-9_\-])/gi, '.');
    s = s.replace(/\s+(?:dot|point|period)\s+([a-zA-Z0-9]+)/gi, '.$1');
    s = s.replace(/\s+(?:dot|point|period)\b/gi, '.');
    s = s.replace(/\s*\.\s*/g, '.');

    // Reconstruct missing dot: <stem> <ext>
    const tokens = s.split(' ');
    const reconstructed = [];
    let i = 0;
    while (i < tokens.length) {
        const tok = tokens[i];
        if (i + 1 < tokens.length) {
            const nextTok = tokens[i + 1];
            const nextClean = nextTok.replace(/[^\w]/g, '').toLowerCase();
            if (tok && CORE_FILE_EXTENSIONS_JS.has(nextClean)) {
                const tokClean = tok.replace(/^[^\w]+|[^\w]+$/g, '').toLowerCase();
                const isNonStem = NON_STEM_WORDS_JS.has(tokClean);
                const alreadyHasExt = tokClean.endsWith('.' + nextClean) || tok.endsWith('.');
                let singleLetterValid = true;
                if (nextClean === 'c' || nextClean === 'h') {
                    singleLetterValid = ['main', 'code', 'script', 'test', 'header', 'utils', 'file', 'app'].includes(tokClean);
                }
                if (!isNonStem && !alreadyHasExt && singleLetterValid && tokClean.length > 0) {
                    const trailingPunct = nextTok.startsWith(nextClean) ? nextTok.slice(nextClean.length) : '';
                    reconstructed.push(`${tok}.${nextClean}${trailingPunct}`);
                    i += 2;
                    continue;
                }
            }
        }
        reconstructed.push(tok);
        i++;
    }

    s = reconstructed.join(' ');
    s = s.replace(/\.{2,}/g, '.');

    // Restore placeholders
    for (const [token, original] of Object.entries(placeholders)) {
        s = s.replace(token, original);
    }

    return s.replace(/\s+/g, ' ').trim();
}
window.normalizeSpokenFileCommand = normalizeSpokenFileCommand;

// Voice conversation state
let pendingText = '';
let isExecuting = false;
let executingTimer = null;

function updateVoiceStatusUi() {
    const orb = document.getElementById('nova-orb');
    const status = document.getElementById('nova-status');
    const micBtn = document.getElementById('nova-mic-btn');
    const speech = window.SpeechService;

    if (!speech || !speech.isListening()) {
        return;
    }

    if (isExecuting) {
        if (status) status.textContent = 'EXECUTING COMMAND…';
        if (orb) {
            orb.classList.remove('listening');
            orb.classList.add('thinking');
        }
        if (micBtn) {
            micBtn.style.borderColor = 'var(--accent-blue)';
            micBtn.style.color = 'var(--accent-blue)';
        }
    } else if (pendingText) {
        if (status) status.textContent = "SAY 'OK' TO RUN";
        if (orb) {
            orb.classList.add('listening');
            orb.classList.remove('thinking');
        }
        if (micBtn) {
            micBtn.style.borderColor = 'var(--accent-green)';
            micBtn.style.color = 'var(--accent-green)';
        }
    } else {
        if (status) status.textContent = 'LISTENING…';
        if (orb) {
            orb.classList.add('listening');
            orb.classList.remove('thinking');
        }
        if (micBtn) {
            micBtn.style.borderColor = 'var(--accent-green)';
            micBtn.style.color = 'var(--accent-green)';
        }
    }
}

function executeVoiceCommand(commandText) {
    if (!commandText || !commandText.trim()) return;
    const cleanCmd = normalizeSpokenFileCommand(commandText.trim());

    // 1. Voice confirmation feedback
    if (window.BridgeClient) {
        window.BridgeClient.addHistory('system', '✓ Confirmed by voice');
    }

    // 2. Set executing guard to prevent late audio from leaking
    isExecuting = true;
    updateVoiceStatusUi();

    if (executingTimer) clearTimeout(executingTimer);
    executingTimer = setTimeout(() => {
        isExecuting = false;
        executingTimer = null;
        updateVoiceStatusUi();
    }, 10000); // 10s safety timeout to ensure UI is never stuck

    // 3. Send command over bridge
    if (window.BridgeClient) {
        window.BridgeClient.sendCommand(cleanCmd, () => {
            if (executingTimer) {
                clearTimeout(executingTimer);
                executingTimer = null;
            }
            isExecuting = false;
            updateVoiceStatusUi();
        });
    } else {
        isExecuting = false;
        updateVoiceStatusUi();
    }
}

window.toggleNovaVoiceMic = async function() {
    const speech = window.SpeechService;
    if (!speech) {
        console.error('[Nova Voice] SpeechService not found');
        return;
    }

    if (speech.isListening() || speech.state === 'requesting_mic') {
        await speech.stop();
        return;
    }

    if (speech.state === 'processing') {
        return;
    }

    // Starting new session: reset state
    pendingText = '';
    isExecuting = false;
    if (executingTimer) {
        clearTimeout(executingTimer);
        executingTimer = null;
    }

    // Lazily re-bind callbacks on each activation to safely handle window reopening
    speech.onPartial = (partial) => {
        if (isExecuting) return;
        const input = document.getElementById('nova-cli-input');
        if (input) {
            const cleanPartial = normaliseVoiceText(partial);
            const displayVal = pendingText
                ? (cleanPartial ? `${pendingText} ${cleanPartial}` : pendingText)
                : cleanPartial;
            input.value = displayVal;
        }
    };

    speech.onFinal = (rawTurn) => {
        if (isExecuting) return;

        const parsed = parseVoiceTurn(rawTurn);
        if (parsed.type === 'empty') return;

        const input = document.getElementById('nova-cli-input');

        if (parsed.type === 'A') {
            // Case A: The turn is only a confirmation word (e.g. "ok", "okay.").
            // If pendingText is non-empty, send it. If empty, ignore turn and do not append "ok".
            if (pendingText) {
                const commandToSend = pendingText;
                pendingText = '';
                if (input) input.value = '';
                executeVoiceCommand(commandToSend);
            }
        } else if (parsed.type === 'B') {
            // Case B: The turn is a task followed by a confirmation at the very end (e.g. "open the terminal okay").
            // Strip the trailing confirmation, append the rest to pendingText, then send.
            const commandToSend = pendingText ? `${pendingText} ${parsed.task}` : parsed.task;
            pendingText = '';
            if (input) input.value = '';
            executeVoiceCommand(commandToSend);
        } else if (parsed.type === 'C') {
            // Case C: Anything else. Append turn to pendingText and wait for "ok".
            pendingText = pendingText ? `${pendingText} ${parsed.task}` : parsed.task;
            if (input) input.value = pendingText;
            updateVoiceStatusUi();
        }
    };

    speech.onStateChange = (state) => {
        const orb = document.getElementById('nova-orb');
        const status = document.getElementById('nova-status');
        const micBtn = document.getElementById('nova-mic-btn');

        if (state === 'requesting_mic') {
            if (status) status.textContent = 'REQUESTING MICROPHONE…';
            if (orb) {
                orb.classList.remove('listening', 'thinking');
            }
            if (micBtn) {
                micBtn.style.borderColor = 'var(--accent-warning)';
                micBtn.style.color = 'var(--accent-warning)';
            }
        } else if (state === 'listening') {
            updateVoiceStatusUi();
        } else if (state === 'processing') {
            if (status) status.textContent = 'FINISHING TRANSCRIPT…';
            if (orb) {
                orb.classList.remove('listening');
                orb.classList.add('thinking');
            }
            if (micBtn) {
                micBtn.style.borderColor = 'var(--accent-blue)';
                micBtn.style.color = 'var(--accent-blue)';
            }
        } else if (state === 'stopped') {
            if (status) status.textContent = 'STANDBY — READY FOR COMMANDS';
            if (orb) {
                orb.classList.remove('listening', 'thinking');
            }
            if (micBtn) {
                micBtn.style.borderColor = 'var(--border-3)';
                micBtn.style.color = 'var(--text-muted)';
            }

            // If user taps the mic to stop while text is pending:
            // Fill input and leave it for manual SEND, and don't auto-send.
            const input = document.getElementById('nova-cli-input');
            if (input && pendingText) {
                input.value = pendingText;
            }
            isExecuting = false;
            if (executingTimer) {
                clearTimeout(executingTimer);
                executingTimer = null;
            }
        } else if (state === 'error') {
            if (orb) {
                orb.classList.remove('listening', 'thinking');
            }
            if (micBtn) {
                micBtn.style.borderColor = 'var(--accent-error)';
                micBtn.style.color = 'var(--accent-error)';
            }
            isExecuting = false;
            if (executingTimer) {
                clearTimeout(executingTimer);
                executingTimer = null;
            }
        }
    };

    speech.onError = (errorMessage) => {
        const status = document.getElementById('nova-status');
        if (status) {
            status.textContent = errorMessage;
        }
        if (window.BridgeClient) {
            window.BridgeClient.addHistory('system', `✕ ${errorMessage}`, true);
        }
    };

    await speech.start();
};

// Command sending from Nova Voice input field
window.sendMockCommand = function() {
    const input = document.getElementById('nova-cli-input');
    if (input && input.value.trim() !== '') {
        const cmd = input.value.trim();
        pendingText = ''; // Clear voice pending state on manual send
        if (window.BridgeClient) {
            window.BridgeClient.sendCommand(cmd);
        }
        input.value = '';
        updateVoiceStatusUi();
    }
};

// Enter key support for Nova Voice input
document.addEventListener('keydown', (e) => {
    if (e.target && e.target.id === 'nova-cli-input' && e.key === 'Enter') {
        window.sendMockCommand();
    }
});

// File upload handler for Nova Voice 📎 button
window.handleFileUpload = async function(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (window.BridgeClient) {
        window.BridgeClient.addHistory('system', `Streaming ${file.name} to Windows Bridge...`);
    }

    const formData = new FormData();
    formData.append('file', file);

    let token = window.BridgeClient?.localToken || localStorage.getItem('novaos_token') || '';
    try {
        let response = await fetch('/upload/file', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });

        if ((response.status === 401 || response.status === 403) && window.BridgeClient) {
            const status = await window.BridgeClient.fetchPairingStatus();
            token = status?.local_token || '';
            response = await fetch('/upload/file', {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                },
                body: formData
            });
        }

        if (response.ok) {
            const result = await response.json();
            if (window.BridgeClient) {
                window.BridgeClient.addHistory('system', `✓ Uploaded ${result.filename} (${formatBytes(result.size)})`);
            }
            window.loadFilesList();
        } else {
            const err = await response.json().catch(() => ({}));
            if (window.BridgeClient) {
                window.BridgeClient.addHistory('system', `✕ Upload failed: ${err.detail || response.statusText}`, true);
            }
        }
    } catch (error) {
        if (window.BridgeClient) {
            window.BridgeClient.addHistory('system', `✕ Network error during upload`, true);
        }
        console.error('Upload error:', error);
    }

    event.target.value = '';
};

// File upload handler inside the Files app
window.handleFilesAppUpload = async function(event) {
    const file = event.target.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);
    const token = window.BridgeClient?.localToken || '';

    try {
        const response = await fetch('/upload/file', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });

        if (response.ok) {
            window.loadFilesList();
        }
    } catch (e) {
        console.error(e);
    }
    event.target.value = '';
};

// Active files cache and folder tree navigation
window._cachedFiles = [];
window._currentFolder = 'mobile'; // 'mobile' | 'photos' | 'all' | 'files'

// Navigate directly into a folder in the folder tree
window.navigateToFolder = function(folder) {
    window._currentFolder = folder;
    
    // Update sidebar active states
    document.querySelectorAll('.files-nav-item').forEach(el => el.classList.remove('active'));
    if (folder === 'mobile') {
        document.getElementById('files-nav-mobile')?.classList.add('active');
    } else if (folder === 'photos') {
        document.getElementById('files-nav-photos')?.classList.add('active');
    } else if (folder === 'output') {
        document.getElementById('files-nav-output')?.classList.add('active');
    }

    window.updateBreadcrumbs();
    window.renderFilesTable();
};

window.updateBreadcrumbs = function() {
    const bcContainer = document.getElementById('files-breadcrumbs');
    if (!bcContainer) return;

    if (window._currentFolder === 'photos') {
        bcContainer.innerHTML = `
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn" onclick="window.navigateToFolder('mobile')">files</button>
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn" onclick="window.navigateToFolder('mobile')">mobile</button>
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn current" onclick="window.navigateToFolder('photos')">photos</button>
        `;
    } else if (window._currentFolder === 'output') {
        bcContainer.innerHTML = `
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn" onclick="window.navigateToFolder('mobile')">files</button>
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn current" onclick="window.navigateToFolder('output')">output</button>
        `;
    } else if (window._currentFolder === 'all') {
        bcContainer.innerHTML = `
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn" onclick="window.navigateToFolder('mobile')">files</button>
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn current" onclick="window.filterFiles('all')">all received</button>
        `;
    } else if (window._currentFolder === 'files') {
        bcContainer.innerHTML = `
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn" onclick="window.navigateToFolder('mobile')">files</button>
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn current" onclick="window.filterFiles('files')">documents</button>
        `;
    } else {
        // 'mobile'
        bcContainer.innerHTML = `
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn" onclick="window.navigateToFolder('mobile')">files</button>
            <span style="color: var(--text-muted);">/</span>
            <button class="files-breadcrumb-btn current" onclick="window.navigateToFolder('mobile')">mobile</button>
        `;
    }
};

// Load files list for Files application
window.loadFilesList = async function() {
    const container = document.getElementById('files-table-container');
    if (!container) return;

    try {
        const res = await fetch('/files');
        if (res.ok) {
            const data = await res.json();
            window._cachedFiles = data.files || [];
            window.updateFolderBadges();
            window.updateBreadcrumbs();
            window.renderFilesTable();
        } else {
            container.innerHTML = `<div style="color: var(--accent-error); text-align: center; padding: 30px;">Failed to load files (HTTP ${res.status})</div>`;
        }
    } catch (e) {
        container.innerHTML = `<div style="color: var(--accent-error); text-align: center; padding: 30px;">Error connecting to bridge files API</div>`;
    }
};

window.updateFolderBadges = function() {
    const allFiles = window._cachedFiles || [];
    const photos = allFiles.filter(f => f.type === 'photo' || f.folder === 'photos' || (f.path && f.path.includes('/photos/')));
    const outputFiles = allFiles.filter(f => f.type === 'output' || f.folder === 'output' || (f.path && f.path.includes('/output/')));
    const mobileFiles = allFiles.filter(f => f.type !== 'photo' && f.type !== 'output' && f.folder !== 'photos' && f.folder !== 'output' && !f.path.includes('/photos/') && !f.path.includes('/output/'));

    const bMobile = document.getElementById('badge-mobile-count');
    const bPhotos = document.getElementById('badge-photos-count');
    const bOutput = document.getElementById('badge-output-count');
    const bAll = document.getElementById('badge-all-count');

    if (bMobile) bMobile.textContent = mobileFiles.length + (photos.length > 0 ? 1 : 0) + (outputFiles.length > 0 ? 1 : 0);
    if (bPhotos) bPhotos.textContent = photos.length;
    if (bOutput) bOutput.textContent = outputFiles.length;
    if (bAll) bAll.textContent = allFiles.length;
};

window.filterFiles = function(category) {
    window._currentFolder = category;
    
    document.querySelectorAll('.files-nav-item').forEach(el => el.classList.remove('active'));
    if (category === 'all') {
        document.getElementById('files-nav-all')?.classList.add('active');
    } else if (category === 'files') {
        document.getElementById('files-nav-docs')?.classList.add('active');
    }

    window.updateBreadcrumbs();
    window.renderFilesTable();
};

window.renderFilesTable = function() {
    const container = document.getElementById('files-table-container');
    const countLabel = document.getElementById('files-count-label');
    if (!container) return;

    const allFiles = window._cachedFiles || [];
    const photos = allFiles.filter(f => f.type === 'photo' || f.folder === 'photos' || (f.path && f.path.includes('/photos/')));
    const outputFiles = allFiles.filter(f => f.type === 'output' || f.folder === 'output' || (f.path && f.path.includes('/output/')));
    const mobileDocs = allFiles.filter(f => f.type !== 'photo' && f.type !== 'output' && f.folder !== 'photos' && f.folder !== 'output' && !f.path.includes('/photos/') && !f.path.includes('/output/'));

    let displayRows = [];

    if (window._currentFolder === 'photos') {
        // Inside Photos subfolder
        displayRows.push({
            isFolder: true,
            name: '.. (Parent Folder: files)',
            type: 'folder-up',
            size_formatted: '--',
            modified: '--',
            onClick: "window.navigateToFolder('mobile')"
        });
        photos.forEach(p => displayRows.push({ ...p, isFolder: false }));
    } else if (window._currentFolder === 'output') {
        // Inside Output subfolder
        displayRows.push({
            isFolder: true,
            name: '.. (Parent Folder: files)',
            type: 'folder-up',
            size_formatted: '--',
            modified: '--',
            onClick: "window.navigateToFolder('mobile')"
        });
        outputFiles.forEach(o => displayRows.push({ ...o, isFolder: false }));
    } else if (window._currentFolder === 'all') {
        // Quick view: All
        allFiles.forEach(f => displayRows.push({ ...f, isFolder: false }));
    } else if (window._currentFolder === 'files') {
        // Quick view: Documents only
        mobileDocs.forEach(f => displayRows.push({ ...f, isFolder: false }));
    } else {
        // Default: 'mobile' folder
        displayRows.push({
            isFolder: true,
            name: 'photos',
            type: 'folder',
            size_formatted: `${photos.length} item${photos.length === 1 ? '' : 's'}`,
            modified: photos.length > 0 ? photos[0].modified : '--',
            onClick: "window.navigateToFolder('photos')"
        });
        displayRows.push({
            isFolder: true,
            name: 'output',
            type: 'folder',
            size_formatted: `${outputFiles.length} item${outputFiles.length === 1 ? '' : 's'}`,
            modified: outputFiles.length > 0 ? outputFiles[0].modified : '--',
            onClick: "window.navigateToFolder('output')"
        });
        mobileDocs.forEach(d => displayRows.push({ ...d, isFolder: false }));
    }

    const fileCount = displayRows.filter(r => !r.isFolder).length;
    if (countLabel) {
        countLabel.textContent = `${fileCount} file${fileCount === 1 ? '' : 's'}`;
    }

    if (displayRows.length === 0) {
        const emptySubtext = window._currentFolder === 'output'
            ? "Process files with voice commands like 'convert test.png to jpg' or 'compress image.png'."
            : "Upload files from your phone or click \"Upload File\" above.";
        container.innerHTML = `
            <div style="text-align: center; padding: 50px 20px; color: var(--text-muted);">
                <div style="font-size: 36px; margin-bottom: 12px; opacity: 0.6;">📁</div>
                <div style="font-size: 14px; font-weight: 500; color: var(--text-secondary); margin-bottom: 6px;">Folder is empty</div>
                <div style="font-size: 12px;">${emptySubtext}</div>
            </div>
        `;
        return;
    }

    let html = `
        <table class="files-table">
            <thead>
                <tr>
                    <th style="width: 44%;">Name</th>
                    <th style="width: 14%;">Type</th>
                    <th style="width: 14%;">Size</th>
                    <th style="width: 20%;">Uploaded At</th>
                    <th style="width: 8%; text-align: center;">Action</th>
                </tr>
            </thead>
            <tbody>
    `;

    displayRows.forEach((r) => {
        if (r.isFolder) {
            const folderIcon = r.type === 'folder-up' ? '↩️' : '📁';
            html += `
                <tr class="folder-row" onclick="${r.onClick}">
                    <td>
                        <div class="file-row-name" style="cursor: pointer; color: var(--accent-warning);">
                            <span>${folderIcon}</span>
                            <span style="font-weight: 600;">${escapeHtml(r.name)}</span>
                        </div>
                    </td>
                    <td><span class="badge-tag folder">Folder</span></td>
                    <td style="font-family: var(--font-mono); font-size: 12px; color: var(--text-muted);">${r.size_formatted}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${r.modified}</td>
                    <td style="text-align: center; color: var(--text-dark); font-size: 11px;">--</td>
                </tr>
            `;
        } else {
            const icon = r.type === 'photo' ? '🖼️' : (r.type === 'output' ? '📤' : '📄');
            const badgeClass = r.type === 'photo' ? 'badge-tag photo' : (r.type === 'output' ? 'badge-tag output' : 'badge-tag file');
            html += `
                <tr style="cursor: pointer;" onclick="if(event.target.tagName !== 'A' && !event.target.closest('.file-delete-btn')) window.openFilePreview('${r.path}', '${escapeHtml(r.name)}', '${r.type}')">
                    <td>
                        <div class="file-row-name">
                            <span>${icon}</span>
                            <a href="javascript:void(0)" onclick="event.stopPropagation(); window.openFilePreview('${r.path}', '${escapeHtml(r.name)}', '${r.type}')" style="color: var(--text-primary); text-decoration: underline; text-underline-offset: 3px; font-weight: 500;" title="Click to view inside Nova OS">${escapeHtml(r.name)}</a>
                        </div>
                    </td>
                    <td><span class="${badgeClass}">${r.type}</span></td>
                    <td style="font-family: var(--font-mono); font-size: 12px;">${r.size_formatted}</td>
                    <td style="font-family: var(--font-mono); font-size: 11px; color: var(--text-muted);">${r.modified}</td>
                    <td style="text-align: center;" onclick="event.stopPropagation()">
                        <button class="file-delete-btn" onclick="event.stopPropagation(); window.deleteFile('${r.path}', '${escapeHtml(r.name)}')" title="Delete ${escapeHtml(r.name)}">🗑️</button>
                    </td>
                </tr>
            `;
        }
    });

    html += `</tbody></table>`;
    container.innerHTML = html;
};

// Delete single file with confirmation and refresh
window.deleteFile = async function(filePath, fileName) {
    if (!filePath) return;
    const name = fileName || filePath.split('/').pop();
    const confirmed = window.confirm(`Are you sure you want to delete "${name}"?`);
    if (!confirmed) return;

    try {
        const res = await fetch(`/files?path=${encodeURIComponent(filePath)}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            const data = await res.json();
            if (window.BridgeClient) {
                window.BridgeClient.addHistory('system', `✓ Deleted file: ${name}`);
            }
            // Refresh file list and badge counts immediately
            await window.loadFilesList();
        } else {
            const err = await res.json().catch(() => ({ detail: 'Failed to delete' }));
            alert(`Could not delete file: ${err.detail || err.message || 'Unknown error'}`);
        }
    } catch (e) {
        alert('Network error deleting file: ' + e);
    }
};

// File Conversion Animation Controller (HTML/CSS/JS)
window._activeConversionTimer = null;
window._activeConversionPendingFile = null;

window.showConversionAnimation = function(sourceFormat, targetFormat, filename) {
    const overlay = document.getElementById('conversion-overlay');
    if (!overlay) return;

    if (window._activeConversionTimer) {
        clearTimeout(window._activeConversionTimer);
        window._activeConversionTimer = null;
    }

    const card = document.getElementById('conversion-card');
    const filenameEl = document.getElementById('conversion-filename');
    const srcPill = document.getElementById('conv-source-pill');
    const tgtPill = document.getElementById('conv-target-pill');
    const stateLabel = document.getElementById('conv-state-label');
    const statusIcon = document.getElementById('conv-status-icon');
    const canonicalSrc = document.getElementById('conv-canonical-src');
    const canonicalMid = document.getElementById('conv-canonical-mid');
    const canonicalTgt = document.getElementById('conv-canonical-tgt');
    const progressBar = document.getElementById('conv-progress-bar');
    const statusMsg = document.getElementById('conv-status-msg');
    const actionsEl = document.getElementById('conv-actions');

    const src = (sourceFormat || 'FILE').toUpperCase();
    const tgt = (targetFormat || 'FORMAT').toUpperCase();
    const fn = filename || 'file';

    window._activeConversionPendingFile = {
        sourceFormat: src,
        targetFormat: tgt,
        filename: fn,
        outputFile: null,
        outputPath: null
    };

    if (card) card.classList.remove('success', 'error');
    if (filenameEl) filenameEl.textContent = fn;
    if (srcPill) srcPill.textContent = src;
    if (tgtPill) tgtPill.textContent = tgt;
    if (canonicalSrc) canonicalSrc.textContent = src;
    if (canonicalMid) canonicalMid.textContent = 'Converting';
    if (canonicalTgt) canonicalTgt.textContent = tgt;
    if (stateLabel) stateLabel.textContent = 'Converting';
    if (statusIcon) {
        statusIcon.textContent = '🔄';
        statusIcon.className = 'converter-icon spinner';
    }
    if (progressBar) {
        progressBar.style.width = '35%';
        setTimeout(() => {
            if (progressBar && overlay.classList.contains('active') && !card?.classList.contains('success')) {
                progressBar.style.width = '70%';
            }
        }, 500);
    }
    if (statusMsg) statusMsg.textContent = `Converting ${src} → ${tgt}...`;
    if (actionsEl) actionsEl.style.display = 'none';

    overlay.classList.remove('closing');
    overlay.classList.add('active');
};

window.finishConversionAnimation = function(result) {
    const overlay = document.getElementById('conversion-overlay');
    if (!overlay || !overlay.classList.contains('active')) return;

    const card = document.getElementById('conversion-card');
    const stateLabel = document.getElementById('conv-state-label');
    const statusIcon = document.getElementById('conv-status-icon');
    const canonicalMid = document.getElementById('conv-canonical-mid');
    const progressBar = document.getElementById('conv-progress-bar');
    const statusMsg = document.getElementById('conv-status-msg');
    const actionsEl = document.getElementById('conv-actions');

    const isSuccess = result && result.status !== 'failed' && result.error == null;

    if (isSuccess) {
        if (card) {
            card.classList.remove('error');
            card.classList.add('success');
        }
        if (stateLabel) stateLabel.textContent = 'Converted!';
        if (statusIcon) {
            statusIcon.textContent = '✓';
            statusIcon.className = 'converter-icon';
        }
        if (canonicalMid) canonicalMid.textContent = 'Converted';
        if (progressBar) progressBar.style.width = '100%';

        const outName = result.output_file || (result.action && result.action.output_file) || 'converted file';
        const outPath = result.path || (result.action && result.action.path) || `/uploads/files/output/${outName}`;

        if (window._activeConversionPendingFile) {
            window._activeConversionPendingFile.outputFile = outName;
            window._activeConversionPendingFile.outputPath = outPath;
        }

        if (statusMsg) {
            statusMsg.textContent = `✓ Output ready: ${outName}`;
        }
        if (actionsEl) actionsEl.style.display = 'flex';

        // Automatically remove/finish the animation after conversion result is available
        window._activeConversionTimer = setTimeout(() => {
            window.hideConversionAnimation();
        }, 1800);
    } else {
        if (card) {
            card.classList.remove('success');
            card.classList.add('error');
        }
        if (stateLabel) stateLabel.textContent = 'Failed';
        if (statusIcon) {
            statusIcon.textContent = '✕';
            statusIcon.className = 'converter-icon';
        }
        if (canonicalMid) canonicalMid.textContent = 'Failed';
        if (statusMsg) statusMsg.textContent = result?.error || result?.message || 'Conversion failed';

        window._activeConversionTimer = setTimeout(() => {
            window.hideConversionAnimation();
        }, 2200);
    }
};

window.hideConversionAnimation = function() {
    const overlay = document.getElementById('conversion-overlay');
    if (!overlay) return;
    overlay.classList.add('closing');
    setTimeout(() => {
        overlay.classList.remove('active', 'closing');
        const card = document.getElementById('conversion-card');
        if (card) card.classList.remove('success', 'error');
    }, 400);
};

window.handleConversionPreviewClick = function() {
    if (window._activeConversionPendingFile && window._activeConversionPendingFile.outputPath) {
        const path = window._activeConversionPendingFile.outputPath;
        const name = window._activeConversionPendingFile.outputFile || path.split('/').pop();
        if (window.openFilePreview) {
            window.openFilePreview(path, name);
        }
        window.hideConversionAnimation();
    }
};

// Text Editor actions
window.editorNew = function() {
    const ta = document.getElementById('editor-textarea');
    const fn = document.getElementById('editor-filename');
    if (ta) ta.value = '';
    if (fn) fn.value = 'untitled.txt';
    const charCount = document.getElementById('editor-char-count');
    if (charCount) charCount.textContent = '0 characters | 0 words';
};

window.editorClear = function() {
    const ta = document.getElementById('editor-textarea');
    if (ta) ta.value = '';
    const charCount = document.getElementById('editor-char-count');
    if (charCount) charCount.textContent = '0 characters | 0 words';
};

window.editorSave = async function() {
    const ta = document.getElementById('editor-textarea');
    const fn = document.getElementById('editor-filename');
    if (!ta) return;

    const content = ta.value;
    const filename = (fn?.value.trim()) || 'notes.txt';
    const blob = new Blob([content], { type: 'text/plain' });
    const formData = new FormData();
    formData.append('file', blob, filename);

    const token = window.BridgeClient?.localToken || '';
    try {
        const response = await fetch('/upload/file', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });

        if (response.ok) {
            const res = await response.json();
            if (window.BridgeClient) {
                window.BridgeClient.addHistory('system', `✓ Saved editor file: ${res.filename} to uploads`);
            }
            alert(`File '${filename}' saved successfully to uploads directory!`);
            window.loadFilesList();
        } else {
            alert('Failed to save file to bridge.');
        }
    } catch (e) {
        alert('Network error saving file: ' + e);
    }
};

// Regenerate 6-digit pairing PIN
window.regeneratePin = async function() {
    try {
        const res = await fetch('/pair/regenerate', { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            if (window.BridgeClient) {
                window.BridgeClient.updatePairingUi(data.status);
            }
            window.loadSettingsStatus();
        }
    } catch (e) {
        console.error('Error regenerating PIN:', e);
    }
};

// Load status for Settings application
window.loadSettingsStatus = async function() {
    try {
        const [statusRes, diagRes] = await Promise.all([
            fetch('/api/status').catch(() => null),
            fetch('/api/network/diagnostics').catch(() => null)
        ]);

        const data = statusRes && statusRes.ok ? await statusRes.json() : null;
        const diag = diagRes && diagRes.ok ? await diagRes.json() : null;

        if (data) {
            const pinCode = document.getElementById('st-pin-code');
            const pinTimer = document.getElementById('st-pin-timer');

            if (pinCode) pinCode.textContent = data.pairing_code || '------';
            
            if (pinTimer && data.pin_expires_in !== undefined) {
                const m = Math.floor(data.pin_expires_in / 60).toString().padStart(2, '0');
                const s = (data.pin_expires_in % 60).toString().padStart(2, '0');
                pinTimer.textContent = `Expires in: ${m}:${s}`;
            }

            const attemptEl = document.getElementById('st-latest-attempt');
            if (attemptEl) {
                if (data.latest_attempt && data.latest_attempt.message) {
                    attemptEl.textContent = `Latest activity: ${data.latest_attempt.message}`;
                    attemptEl.style.color = (data.latest_attempt.result === 'success') ? 'var(--accent-green)' : '#ff6b6b';
                } else {
                    attemptEl.textContent = 'No pairing attempts recorded yet.';
                    attemptEl.style.color = 'var(--text-muted)';
                }
            }

            // Render Paired Devices (Task 4)
            const pairedList = document.getElementById('st-paired-devices-list');
            if (pairedList) {
                const devices = data.paired_devices || [];
                if (devices.length === 0) {
                    pairedList.innerHTML = `<span style="color: var(--text-muted);">No phone devices paired yet.</span>`;
                } else {
                    let html = '<div style="display: flex; flex-direction: column; gap: 8px;">';
                    devices.forEach(d => {
                        const name = escapeHtml(d.client_id || d.device_id || 'Mobile Client');
                        html += `
                            <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-radius: 6px; background: rgba(0,0,0,0.3); border: 1px solid var(--border-2);">
                                <div>
                                    <div style="font-weight: 600; color: var(--text-primary);">📱 ${name}</div>
                                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">
                                        Paired: ${escapeHtml(d.paired_at_str || 'N/A')} &bull; Last seen: ${escapeHtml(d.last_seen_str || 'N/A')}
                                    </div>
                                </div>
                                <button class="btn-widget-action" style="color: #ff6b6b; border-color: rgba(255,107,107,0.4); padding: 4px 10px; flex: 0 0 auto;" onclick="window.revokePairedDevice('${d.token_hash}')">Revoke</button>
                            </div>
                        `;
                    });
                    html += '</div>';
                    pairedList.innerHTML = html;
                }
            }
        }

        if (diag) {
            const httpPort = document.getElementById('st-http-port');
            const wsPort = document.getElementById('st-ws-port');
            const fwStatus = document.getElementById('st-fw-status');
            const fwFixBox = document.getElementById('st-fw-fix-box');
            const contactBox = document.getElementById('st-phone-contact-box');
            const lanAdapters = document.getElementById('st-lan-adapters');
            const mdnsStatus = document.getElementById('st-mdns-status');

            if (httpPort) httpPort.textContent = `${diag.http_port} (Listening)`;
            if (wsPort) wsPort.textContent = diag.ws_bound ? `${diag.ws_port} (Listening)` : `${diag.ws_port} [Fallback /ws on ${diag.http_port}]`;
            
            if (mdnsStatus) {
                mdnsStatus.textContent = diag.mdns_registered ? '_winbridge._tcp (Active)' : '_winbridge._tcp (Unregistered/Offline)';
                mdnsStatus.style.color = diag.mdns_registered ? 'var(--accent-green)' : 'var(--accent-warning)';
            }

            if (fwStatus) {
                if (diag.firewall_rules_ok) {
                    fwStatus.textContent = `PASS (${diag.firewall_info?.active_profile || 'Active'} Profile Allowed)`;
                    fwStatus.style.color = 'var(--accent-green)';
                    if (fwFixBox) fwFixBox.style.display = 'none';
                } else {
                    const missing = diag.firewall_info?.missing?.join(', ') || 'Inbound ports blocked';
                    fwStatus.textContent = `BLOCKED (${missing})`;
                    fwStatus.style.color = '#ff6b6b';
                    if (fwFixBox) {
                        fwFixBox.style.display = 'block';
                        fwFixBox.innerHTML = `⚠️ Run as Admin to fix: <code>${escapeHtml(diag.firewall_info?.fix_command || 'powershell -ExecutionPolicy Bypass -File scripts/allow_firewall.ps1')}</code>`;
                    }
                }
            }

            if (contactBox) {
                if (diag.last_phone_contact) {
                    const c = diag.last_phone_contact;
                    contactBox.innerHTML = `<strong>Last phone contact:</strong> ${escapeHtml(c.ip)} ${escapeHtml(c.method)} ${escapeHtml(c.path)} ${c.status} (${c.seconds_ago}s ago)`;
                    contactBox.style.background = 'rgba(90, 247, 142, 0.12)';
                    contactBox.style.border = '1px solid rgba(90, 247, 142, 0.35)';
                    contactBox.style.color = 'var(--accent-green)';
                } else {
                    contactBox.textContent = 'No phone has reached this PC yet. Check Wi-Fi, firewall and router isolation';
                    contactBox.style.background = 'rgba(255, 179, 71, 0.12)';
                    contactBox.style.border = '1px solid rgba(255, 179, 71, 0.35)';
                    contactBox.style.color = 'var(--accent-warning)';
                }
            }

            if (lanAdapters && diag.lan_ips) {
                let html = '';
                diag.lan_ips.forEach(a => {
                    const rec = a.recommended ? ' <span style="color: var(--accent-green); font-size: 10px; font-weight: 600;">[RECOMMENDED FOR PHONE]</span>' : (a.is_virtual ? ' <span style="color: var(--text-muted); font-size: 10px;">[Virtual Adapter]</span>' : '');
                    html += `
                        <div style="padding: 4px 8px; border-radius: 4px; background: rgba(0,0,0,0.2); border: 1px solid var(--border-1);">
                            <strong>${escapeHtml(a.ip)}</strong> &mdash; ${escapeHtml(a.adapter)}${rec}
                        </div>
                    `;
                });
                lanAdapters.innerHTML = html;
            }
        }
    } catch (e) {
        console.warn('Error loading settings status:', e);
    }
};

window.revokePairedDevice = async function(tokenHash) {
    if (!confirm('Revoke access for this phone? It will need to be re-paired with a PIN.')) {
        return;
    }
    try {
        const res = await fetch('/pair/revoke', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token_hash: tokenHash })
        });
        if (res.ok) {
            window.loadSettingsStatus();
        } else {
            alert('Failed to revoke session.');
        }
    } catch (e) {
        alert('Network error revoking session: ' + e);
    }
};

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
