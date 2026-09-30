/**
 * Workspace Application for Nova OS
 * Implements Documents, Spreadsheets, Planner, and upcoming modules.
 */

(function () {
    'use strict';

    // Safe Formula Evaluator (Zero eval / new Function)
    function tokenizeFormula(str) {
        const tokens = [];
        let i = 0;
        while (i < str.length) {
            const ch = str[i];
            if (/\s/.test(ch)) {
                i++;
                continue;
            }
            if (ch === '+' || ch === '-' || ch === '*' || ch === '/' || ch === '(' || ch === ')' || ch === ',') {
                tokens.push({ type: 'OP', value: ch });
                i++;
                continue;
            }
            if (/\d/.test(ch) || (ch === '.' && /\d/.test(str[i + 1] || ''))) {
                let numStr = '';
                while (i < str.length && (/[\d.]/.test(str[i]))) {
                    numStr += str[i];
                    i++;
                }
                tokens.push({ type: 'NUMBER', value: parseFloat(numStr) });
                continue;
            }
            if (/[A-Za-z]/.test(ch)) {
                let ident = '';
                while (i < str.length && /[A-Za-z0-9]/.test(str[i])) {
                    ident += str[i];
                    i++;
                }
                ident = ident.toUpperCase();
                if (str[i] === ':') {
                    i++;
                    let rangeEnd = '';
                    while (i < str.length && /[A-Za-z0-9]/.test(str[i])) {
                        rangeEnd += str[i];
                        i++;
                    }
                    rangeEnd = rangeEnd.toUpperCase();
                    tokens.push({ type: 'RANGE', start: ident, end: rangeEnd });
                    continue;
                }
                if (['SUM', 'AVERAGE', 'AVG', 'MIN', 'MAX', 'COUNT'].includes(ident)) {
                    tokens.push({ type: 'FUNC', value: ident });
                    continue;
                }
                if (/^[A-Z]+[1-9]\d*$/.test(ident)) {
                    tokens.push({ type: 'CELL', value: ident });
                    continue;
                }
                throw new Error('Unknown identifier: ' + ident);
            }
            throw new Error('Unexpected character: ' + ch);
        }
        return tokens;
    }

    function expandRange(startRef, endRef) {
        const parse = (ref) => {
            const m = ref.match(/^([A-Z]+)([1-9]\d*)$/);
            if (!m) return null;
            let colStr = m[1];
            let row = parseInt(m[2], 10);
            let col = 0;
            for (let i = 0; i < colStr.length; i++) {
                col = col * 26 + (colStr.charCodeAt(i) - 64);
            }
            return { col: col - 1, row };
        };

        const s = parse(startRef);
        const e = parse(endRef);
        if (!s || !e) return [];

        const minCol = Math.min(s.col, e.col);
        const maxCol = Math.max(s.col, e.col);
        const minRow = Math.min(s.row, e.row);
        const maxRow = Math.max(s.row, e.row);

        const cells = [];
        for (let r = minRow; r <= maxRow; r++) {
            for (let c = minCol; c <= maxCol; c++) {
                let colName = '';
                let temp = c + 1;
                while (temp > 0) {
                    let rem = (temp - 1) % 26;
                    colName = String.fromCharCode(65 + rem) + colName;
                    temp = Math.floor((temp - 1) / 26);
                }
                cells.push(`${colName}${r}`);
            }
        }
        return cells;
    }

    class FormulaParser {
        constructor(tokens, sheetData, visited, evaluator) {
            this.tokens = tokens;
            this.pos = 0;
            this.sheetData = sheetData;
            this.visited = visited;
            this.evaluator = evaluator;
        }

        peek() {
            return this.tokens[this.pos];
        }

        consume(expectedVal) {
            const t = this.tokens[this.pos];
            if (!t) throw new Error('Unexpected end of formula');
            if (expectedVal && t.value !== expectedVal) {
                throw new Error(`Expected '${expectedVal}', got '${t.value}'`);
            }
            this.pos++;
            return t;
        }

        parse() {
            const res = this.parseExpression();
            if (this.pos < this.tokens.length) {
                throw new Error('Unexpected token: ' + this.tokens[this.pos].value);
            }
            return res;
        }

        parseExpression() {
            let left = this.parseTerm();
            while (this.peek() && (this.peek().value === '+' || this.peek().value === '-')) {
                const op = this.consume().value;
                const right = this.parseTerm();
                if (op === '+') left = left + right;
                else left = left - right;
            }
            return left;
        }

        parseTerm() {
            let left = this.parseFactor();
            while (this.peek() && (this.peek().value === '*' || this.peek().value === '/')) {
                const op = this.consume().value;
                const right = this.parseFactor();
                if (op === '/') {
                    if (right === 0) throw new Error('Division by zero');
                    left = left / right;
                } else {
                    left = left * right;
                }
            }
            return left;
        }

        parseFactor() {
            const t = this.peek();
            if (!t) throw new Error('Unexpected end of formula');

            if (t.value === '+') {
                this.consume('+');
                return this.parseFactor();
            }
            if (t.value === '-') {
                this.consume('-');
                return -this.parseFactor();
            }
            if (t.value === '(') {
                this.consume('(');
                const val = this.parseExpression();
                this.consume(')');
                return val;
            }
            if (t.type === 'NUMBER') {
                this.consume();
                return t.value;
            }
            if (t.type === 'CELL') {
                this.consume();
                const val = this.evaluator.getNumericCellValue(t.value, this.sheetData, this.visited);
                if (val === null) {
                    const raw = this.sheetData[t.value];
                    if (raw !== undefined && raw !== null && String(raw).trim() !== '') {
                        throw new Error('Non-numeric cell in arithmetic');
                    }
                    return 0;
                }
                return val;
            }
            if (t.type === 'FUNC') {
                return this.parseFunction();
            }
            throw new Error('Unexpected token: ' + JSON.stringify(t));
        }

        parseFunction() {
            const funcToken = this.consume();
            const funcName = funcToken.value;
            this.consume('(');

            const values = [];
            if (this.peek() && this.peek().value !== ')') {
                while (true) {
                    if (this.peek() && this.peek().type === 'RANGE') {
                        const rangeToken = this.consume();
                        const cellKeys = expandRange(rangeToken.start, rangeToken.end);
                        for (const k of cellKeys) {
                            const val = this.evaluator.getNumericCellValue(k, this.sheetData, this.visited);
                            if (val !== null && !isNaN(val)) {
                                values.push(val);
                            }
                        }
                    } else {
                        const exprVal = this.parseExpression();
                        if (exprVal !== null && !isNaN(exprVal)) {
                            values.push(exprVal);
                        }
                    }

                    if (this.peek() && this.peek().value === ',') {
                        this.consume(',');
                    } else {
                        break;
                    }
                }
            }
            this.consume(')');

            switch (funcName) {
                case 'SUM':
                    return values.reduce((a, b) => a + b, 0);
                case 'AVERAGE':
                case 'AVG':
                    if (values.length === 0) return 0;
                    return values.reduce((a, b) => a + b, 0) / values.length;
                case 'MIN':
                    if (values.length === 0) return 0;
                    return Math.min(...values);
                case 'MAX':
                    if (values.length === 0) return 0;
                    return Math.max(...values);
                case 'COUNT':
                    return values.length;
                default:
                    throw new Error('Unknown function: ' + funcName);
            }
        }
    }

    class WorkspaceApp {
        constructor() {
            this.storageKey = 'novaos.workspace.v1';
            this.state = {
                currentTab: 'documents',
                documents: [],
                activeDocId: null,
                sheets: [],
                activeSheetId: null,
                tasks: [],
                taskFilter: 'all'
            };
            this.rootEl = null;
            this.docAutosaveTimer = null;
            this.activeCellKey = 'A1';
            this.lastSaveOk = false;
        }

        escapeHtml(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        sanitizeHtml(html) {
            if (!html) return '';
            let clean = html.replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '');
            clean = clean.replace(/<\/?(iframe|object|embed)\b[^>]*>/gi, '');
            clean = clean.replace(/\s+on\w+\s*=\s*(?:'[^']*'|"[^"]*"|[^\s>]+)/gi, '');
            clean = clean.replace(/(href|src)\s*=\s*(?:'javascript:[^']*'|"javascript:[^"]*"|javascript:[^\s>]+)/gi, '$1="#"');
            return clean;
        }

        formatDate(dateStr) {
            if (!dateStr) return 'Just now';
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return 'Just now';
            return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        }

        formatTime(dateStr) {
            if (!dateStr) return 'Never';
            const d = new Date(dateStr);
            if (isNaN(d.getTime())) return 'Never';
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }

        getNumericCellValue(cellKey, sheetData, visited) {
            if (visited.has(cellKey)) {
                throw new Error('Circular reference at ' + cellKey);
            }
            const raw = sheetData[cellKey];
            if (raw === undefined || raw === null || String(raw).trim() === '') {
                return null;
            }
            if (typeof raw === 'string' && raw.startsWith('=')) {
                visited.add(cellKey);
                const res = this.evaluateFormula(raw, sheetData, visited);
                visited.delete(cellKey);
                if (res === '#ERR') throw new Error('Ref error');
                if (typeof res === 'number') return res;
                const n = parseFloat(res);
                if (isNaN(n)) return null;
                return n;
            }
            const n = parseFloat(raw);
            if (isNaN(n)) return null;
            return n;
        }

        evaluateFormula(formulaStr, sheetData, visited = new Set()) {
            if (!formulaStr || !formulaStr.startsWith('=')) return formulaStr;
            const clean = formulaStr.slice(1).trim();
            if (!clean) return '';
            try {
                const tokens = tokenizeFormula(clean);
                const parser = new FormulaParser(tokens, sheetData, visited, this);
                const result = parser.parse();
                if (typeof result === 'number') {
                    if (!isFinite(result) || isNaN(result)) return '#ERR';
                    return Math.round(result * 100000000) / 100000000;
                }
                return result;
            } catch (err) {
                return '#ERR';
            }
        }

        loadState() {
            try {
                const storage = typeof window !== 'undefined' && window.localStorage ? window.localStorage : (typeof localStorage !== 'undefined' ? localStorage : null);
                if (storage) {
                    const raw = storage.getItem(this.storageKey);
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (parsed && typeof parsed === 'object') {
                            this.state = Object.assign(this.state, parsed);
                            this.lastSaveOk = true;
                        }
                    }
                }
            } catch (e) {
                console.warn('Workspace: localStorage read failed, fallback to memory', e);
                this.lastSaveOk = false;
            }

            if (!Array.isArray(this.state.documents)) this.state.documents = [];
            if (!Array.isArray(this.state.sheets)) this.state.sheets = [];
            if (!Array.isArray(this.state.tasks)) this.state.tasks = [];

            if (this.state.documents.length > 0 && !this.state.activeDocId) {
                this.state.activeDocId = this.state.documents[0].id;
            }
            if (this.state.sheets.length > 0 && !this.state.activeSheetId) {
                this.state.activeSheetId = this.state.sheets[0].id;
            }
        }

        saveState() {
            try {
                const storage = typeof window !== 'undefined' && window.localStorage ? window.localStorage : (typeof localStorage !== 'undefined' ? localStorage : null);
                if (!storage) throw new Error('localStorage is not available');
                storage.setItem(this.storageKey, JSON.stringify(this.state));
                this.lastSaveOk = true;
                this.updateFooterStatus('Saved locally', true);
                return true;
            } catch (e) {
                console.warn('Workspace: localStorage write failed', e);
                this.lastSaveOk = false;
                this.updateFooterStatus('Saved in memory', false);
                return false;
            }
        }

        getActiveDoc() {
            return this.state.documents.find(d => d.id === this.state.activeDocId) || null;
        }

        getActiveSheet() {
            return this.state.sheets.find(s => s.id === this.state.activeSheetId) || null;
        }

        injectStyles() {
            if (document.getElementById('ws-styles')) return;

            const style = document.createElement('style');
            style.id = 'ws-styles';
            style.textContent = `
                /* Workspace Core Layout */
                #workspace-root {
                    height: 100%;
                    width: 100%;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    background-color: var(--bg-panel-3);
                    color: var(--text-primary);
                    font-family: var(--font-ui);
                }

                /* Text Selection Gotcha Fix */
                #workspace-root input,
                #workspace-root textarea,
                #workspace-root [contenteditable="true"],
                .ws-editor-body,
                .ws-sheet-cell,
                .ws-task-input,
                .ws-formula-input,
                .ws-doc-title-input {
                    user-select: text !important;
                    -webkit-user-select: text !important;
                }

                .ws-shell {
                    display: flex;
                    width: 100%;
                    height: 100%;
                    overflow: hidden;
                }

                /* Sidebar (260px fixed) */
                .ws-sidebar {
                    width: 260px;
                    min-width: 260px;
                    max-width: 260px;
                    height: 100%;
                    background-color: var(--bg-panel-2);
                    border-right: 1px solid var(--border-3);
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                }

                .ws-sidebar-header {
                    padding: 16px 14px;
                    border-bottom: 1px solid var(--border-2);
                    display: flex;
                    flex-direction: column;
                    gap: 6px;
                }

                .ws-brand {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    font-weight: 700;
                    font-size: 15px;
                    letter-spacing: -0.01em;
                }

                .ws-brand-badge {
                    font-size: 10px;
                    padding: 2px 6px;
                    border-radius: 4px;
                    background: rgba(90, 247, 142, 0.15);
                    color: var(--accent-green);
                    border: 1px solid rgba(90, 247, 142, 0.3);
                    font-family: var(--font-mono);
                }

                .ws-sidebar-counts {
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-muted);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .ws-sidebar-voice-section {
                    padding: 12px 14px;
                    border-bottom: 1px solid var(--border-2);
                }

                .ws-voice-orb-btn {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    width: 100%;
                    background: linear-gradient(135deg, rgba(90, 247, 142, 0.12), rgba(87, 199, 255, 0.08));
                    border: 1px solid rgba(90, 247, 142, 0.3);
                    border-radius: 10px;
                    padding: 10px 14px;
                    cursor: pointer;
                    color: var(--text-primary);
                    transition: all 0.2s ease;
                }

                .ws-voice-orb-btn:hover {
                    background: linear-gradient(135deg, rgba(90, 247, 142, 0.22), rgba(87, 199, 255, 0.15));
                    border-color: var(--accent-green);
                    transform: translateY(-1px);
                    box-shadow: 0 4px 16px rgba(90, 247, 142, 0.2);
                }

                .ws-voice-orb-core {
                    width: 28px;
                    height: 28px;
                    border-radius: 50%;
                    background: radial-gradient(circle, var(--accent-green) 0%, rgba(87, 199, 255, 0.6) 100%);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 14px;
                    box-shadow: 0 0 10px rgba(90, 247, 142, 0.5);
                }

                .ws-voice-orb-text {
                    display: flex;
                    flex-direction: column;
                    text-align: left;
                }

                .ws-voice-label {
                    font-size: 12px;
                    font-weight: 600;
                    color: var(--text-primary);
                }

                .ws-voice-sub {
                    font-size: 10px;
                    color: var(--text-muted);
                    font-family: var(--font-mono);
                }

                .ws-sidebar-menu {
                    flex: 1;
                    padding: 12px 14px;
                    overflow-y: auto;
                    display: flex;
                    flex-direction: column;
                    gap: 12px;
                }

                .ws-sidebar-section-title {
                    font-family: var(--font-mono);
                    font-size: 10px;
                    font-weight: 600;
                    color: var(--text-muted);
                    letter-spacing: 0.05em;
                }

                .ws-sidebar-info-card {
                    background: var(--bg-panel-3);
                    border: 1px solid var(--border-2);
                    border-radius: 8px;
                    padding: 12px;
                    font-size: 12px;
                    color: var(--text-secondary);
                    line-height: 1.4;
                }

                .ws-sidebar-footer {
                    padding: 12px 14px;
                    border-top: 1px solid var(--border-2);
                    background: var(--bg-panel-1);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    font-size: 11px;
                    font-family: var(--font-mono);
                }

                .ws-history-label {
                    color: var(--text-muted);
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }

                .ws-dot {
                    width: 6px;
                    height: 6px;
                    border-radius: 50%;
                    background: var(--border-4);
                }

                .ws-storage-status {
                    display: flex;
                    align-items: center;
                    gap: 5px;
                    font-size: 10px;
                }

                .ws-status-dot {
                    width: 6px;
                    height: 6px;
                    border-radius: 50%;
                }
                .ws-status-dot.success {
                    background-color: var(--accent-green);
                    box-shadow: 0 0 6px var(--accent-green);
                }
                .ws-status-dot.warning {
                    background-color: var(--accent-warning);
                    box-shadow: 0 0 6px var(--accent-warning);
                }

                /* Main Content Area */
                .ws-main {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    height: 100%;
                    overflow: hidden;
                    background-color: var(--bg-panel-3);
                }

                /* Top Tab Bar */
                .ws-topbar {
                    height: 44px;
                    min-height: 44px;
                    background-color: var(--bg-panel-2);
                    border-bottom: 1px solid var(--border-2);
                    display: flex;
                    align-items: center;
                    padding: 0 12px;
                    gap: 4px;
                    overflow-x: auto;
                }

                .ws-tabs {
                    display: flex;
                    gap: 4px;
                    align-items: center;
                }

                .ws-tab-btn {
                    background: transparent;
                    border: 1px solid transparent;
                    color: var(--text-muted);
                    font-family: var(--font-ui);
                    font-size: 12px;
                    font-weight: 500;
                    padding: 6px 12px;
                    border-radius: 6px;
                    cursor: pointer;
                    transition: all 0.15s ease;
                    white-space: nowrap;
                }

                .ws-tab-btn:hover {
                    color: var(--text-secondary);
                    background-color: rgba(255, 255, 255, 0.04);
                }

                .ws-tab-btn.active {
                    color: var(--text-primary);
                    background-color: var(--bg-panel-4);
                    border-color: var(--border-3);
                    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
                }

                .ws-content-pane {
                    flex: 1;
                    height: calc(100% - 44px);
                    overflow: hidden;
                    position: relative;
                    display: flex;
                }

                /* Common Button Styles */
                .ws-btn {
                    font-family: var(--font-ui);
                    font-size: 12px;
                    font-weight: 500;
                    padding: 6px 12px;
                    border-radius: 6px;
                    cursor: pointer;
                    border: 1px solid var(--border-3);
                    background: var(--bg-panel-4);
                    color: var(--text-primary);
                    transition: all 0.2s ease;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    outline: none;
                }

                .ws-btn:hover {
                    background: var(--bg-panel-5);
                    border-color: var(--border-4);
                }

                .ws-btn-primary {
                    background: rgba(90, 247, 142, 0.12);
                    border-color: rgba(90, 247, 142, 0.35);
                    color: var(--accent-green);
                }

                .ws-btn-primary:hover {
                    background: rgba(90, 247, 142, 0.22);
                    border-color: var(--accent-green);
                }

                .ws-btn-danger {
                    color: #ff6b6b;
                    border-color: rgba(255, 107, 107, 0.3);
                }

                .ws-btn-danger:hover {
                    background: rgba(255, 107, 107, 0.15);
                    border-color: #ff6b6b;
                }

                .ws-btn-xs {
                    padding: 3px 8px;
                    font-size: 11px;
                }

                .ws-btn-sm {
                    padding: 4px 10px;
                    font-size: 11px;
                }

                /* Empty States */
                .ws-empty-state {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    padding: 40px 20px;
                }

                .ws-empty-icon {
                    font-size: 44px;
                    margin-bottom: 12px;
                    filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.5));
                }

                .ws-empty-title {
                    font-size: 18px;
                    font-weight: 600;
                    color: var(--text-primary);
                    margin-bottom: 6px;
                }

                .ws-empty-desc {
                    font-size: 13px;
                    color: var(--text-muted);
                    max-width: 340px;
                    margin-bottom: 18px;
                    line-height: 1.5;
                }

                /* Documents Tab */
                .ws-doc-layout {
                    display: flex;
                    width: 100%;
                    height: 100%;
                    overflow: hidden;
                }

                .ws-doc-sidebar {
                    width: 220px;
                    min-width: 220px;
                    background-color: var(--bg-panel-2);
                    border-right: 1px solid var(--border-2);
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                }

                .ws-doc-sidebar-header {
                    padding: 10px 12px;
                    border-bottom: 1px solid var(--border-2);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    font-size: 11px;
                    font-weight: 600;
                    color: var(--text-muted);
                    font-family: var(--font-mono);
                }

                .ws-doc-list {
                    flex: 1;
                    overflow-y: auto;
                    padding: 6px;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                }

                .ws-doc-item {
                    padding: 8px 10px;
                    border-radius: 6px;
                    cursor: pointer;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    border: 1px solid transparent;
                    transition: all 0.15s ease;
                }

                .ws-doc-item:hover {
                    background-color: rgba(255, 255, 255, 0.04);
                    border-color: var(--border-2);
                }

                .ws-doc-item.active {
                    background-color: var(--bg-panel-4);
                    border-color: var(--border-3);
                }

                .ws-doc-item-title {
                    font-size: 12px;
                    font-weight: 500;
                    color: var(--text-primary);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    max-width: 130px;
                }

                .ws-doc-item.active .ws-doc-item-title {
                    color: var(--accent-green);
                }

                .ws-doc-item-meta {
                    font-size: 10px;
                    color: var(--text-muted);
                    font-family: var(--font-mono);
                    margin-top: 2px;
                }

                .ws-doc-actions {
                    display: flex;
                    gap: 4px;
                    opacity: 0;
                    transition: opacity 0.15s;
                }

                .ws-doc-item:hover .ws-doc-actions,
                .ws-doc-item.active .ws-doc-actions {
                    opacity: 1;
                }

                .ws-doc-action-btn {
                    background: transparent;
                    border: none;
                    color: var(--text-muted);
                    cursor: pointer;
                    padding: 2px 4px;
                    border-radius: 3px;
                    font-size: 11px;
                }

                .ws-doc-action-btn:hover {
                    color: var(--text-primary);
                    background: rgba(255, 255, 255, 0.1);
                }

                .ws-doc-editor-pane {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    height: 100%;
                    overflow: hidden;
                }

                .ws-doc-toolbar {
                    padding: 8px 16px;
                    background-color: var(--bg-panel-2);
                    border-bottom: 1px solid var(--border-2);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 12px;
                    flex-wrap: wrap;
                }

                .ws-doc-title-input {
                    background: transparent;
                    border: 1px solid transparent;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 14px;
                    font-weight: 600;
                    color: var(--text-primary);
                    font-family: var(--font-ui);
                    outline: none;
                    min-width: 180px;
                }

                .ws-doc-title-input:hover,
                .ws-doc-title-input:focus {
                    background: var(--bg-panel-4);
                    border-color: var(--border-3);
                }

                .ws-doc-fmt-group {
                    display: flex;
                    align-items: center;
                    gap: 3px;
                }

                .ws-fmt-btn {
                    padding: 5px 8px;
                    border-radius: 4px;
                    border: 1px solid var(--border-3);
                    background: var(--bg-panel-4);
                    color: var(--text-secondary);
                    cursor: pointer;
                    font-size: 12px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    min-width: 26px;
                    height: 26px;
                    outline: none;
                }

                .ws-fmt-btn:hover {
                    background: var(--bg-panel-5);
                    color: var(--text-primary);
                    border-color: var(--border-4);
                }

                .ws-toolbar-sep {
                    width: 1px;
                    height: 18px;
                    background: var(--border-3);
                    margin: 0 4px;
                }

                .ws-save-status {
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-muted);
                }

                .ws-editor-body {
                    flex: 1;
                    overflow-y: auto;
                    padding: 24px 32px;
                    outline: none;
                    font-size: 14px;
                    line-height: 1.65;
                    color: var(--text-secondary);
                    background-color: var(--bg-panel-3);
                }

                .ws-editor-body:empty:before {
                    content: attr(placeholder);
                    color: var(--text-muted);
                    pointer-events: none;
                }

                .ws-editor-body h1, .ws-editor-body h2, .ws-editor-body h3 {
                    color: var(--text-primary);
                    margin: 16px 0 8px 0;
                }
                .ws-editor-body p {
                    margin-bottom: 12px;
                }

                .ws-doc-footer {
                    height: 32px;
                    min-height: 32px;
                    background-color: var(--bg-panel-2);
                    border-top: 1px solid var(--border-2);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 0 16px;
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-muted);
                }

                .ws-doc-footer-left {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                /* Sheets Tab */
                .ws-sheet-layout {
                    width: 100%;
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                }

                .ws-sheet-toolbar {
                    padding: 8px 12px;
                    background-color: var(--bg-panel-2);
                    border-bottom: 1px solid var(--border-2);
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    flex-wrap: wrap;
                }

                .ws-sheet-select {
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    border-radius: 4px;
                    padding: 4px 8px;
                    color: var(--text-primary);
                    font-family: var(--font-ui);
                    font-size: 12px;
                    outline: none;
                }

                .ws-cell-coord {
                    width: 44px;
                    text-align: center;
                    font-family: var(--font-mono);
                    font-weight: 600;
                    font-size: 12px;
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    border-radius: 4px;
                    padding: 4px 6px;
                    color: var(--accent-green);
                }

                .ws-fx-label {
                    font-family: var(--font-mono);
                    font-style: italic;
                    font-size: 12px;
                    color: var(--text-muted);
                    font-weight: 700;
                }

                .ws-formula-input {
                    flex: 1;
                    min-width: 200px;
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    border-radius: 4px;
                    padding: 5px 10px;
                    color: var(--text-primary);
                    font-family: var(--font-mono);
                    font-size: 12px;
                    outline: none;
                }

                .ws-formula-input:focus {
                    border-color: var(--accent-blue);
                }

                .ws-grid-wrapper {
                    flex: 1;
                    overflow: auto;
                    position: relative;
                    background-color: var(--bg-panel-3);
                }

                .ws-grid-table {
                    border-collapse: collapse;
                    table-layout: fixed;
                    width: max-content;
                    min-width: 100%;
                }

                .ws-corner-header {
                    width: 44px;
                    min-width: 44px;
                    max-width: 44px;
                    height: 24px;
                    position: sticky;
                    top: 0;
                    left: 0;
                    z-index: 3;
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-muted);
                    text-align: center;
                }

                .ws-col-header {
                    width: 85px;
                    min-width: 85px;
                    height: 24px;
                    position: sticky;
                    top: 0;
                    z-index: 2;
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-secondary);
                    text-align: center;
                }

                .ws-row-header {
                    width: 44px;
                    min-width: 44px;
                    height: 24px;
                    position: sticky;
                    left: 0;
                    z-index: 2;
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-muted);
                    text-align: center;
                }

                .ws-sheet-cell {
                    width: 85px;
                    min-width: 85px;
                    height: 24px;
                    border: 1px solid var(--border-2);
                    padding: 2px 6px;
                    font-family: var(--font-mono);
                    font-size: 12px;
                    color: var(--text-primary);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    outline: none;
                    background: var(--bg-panel-3);
                }

                .ws-sheet-cell:hover {
                    background: rgba(255, 255, 255, 0.03);
                }

                .ws-sheet-cell:focus,
                .ws-sheet-cell.active-cell {
                    background: rgba(87, 199, 255, 0.12) !important;
                    border-color: var(--accent-blue) !important;
                    box-shadow: inset 0 0 0 1px var(--accent-blue);
                }

                /* Planner Tab */
                .ws-planner-layout {
                    width: 100%;
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    padding: 20px 24px;
                    overflow-y: auto;
                }

                .ws-planner-card {
                    max-width: 720px;
                    width: 100%;
                    margin: 0 auto;
                    display: flex;
                    flex-direction: column;
                    gap: 16px;
                }

                .ws-planner-input-bar {
                    display: flex;
                    gap: 10px;
                }

                .ws-task-input {
                    flex: 1;
                    background: var(--bg-panel-4);
                    border: 1px solid var(--border-3);
                    border-radius: 8px;
                    padding: 10px 14px;
                    color: var(--text-primary);
                    font-family: var(--font-ui);
                    font-size: 13px;
                    outline: none;
                }

                .ws-task-input:focus {
                    border-color: var(--accent-green);
                }

                .ws-planner-meta-bar {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 12px;
                }

                .ws-filters {
                    display: flex;
                    gap: 6px;
                }

                .ws-filter-btn {
                    padding: 5px 12px;
                    border-radius: 6px;
                    font-size: 12px;
                    font-weight: 500;
                    border: 1px solid var(--border-2);
                    background: var(--bg-panel-2);
                    color: var(--text-muted);
                    cursor: pointer;
                    transition: all 0.15s ease;
                }

                .ws-filter-btn:hover {
                    color: var(--text-secondary);
                }

                .ws-filter-btn.active {
                    background: var(--bg-panel-4);
                    border-color: var(--accent-green);
                    color: var(--accent-green);
                }

                .ws-planner-progress {
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    font-family: var(--font-mono);
                    font-size: 11px;
                    color: var(--text-muted);
                }

                .ws-progress-bar {
                    width: 120px;
                    height: 6px;
                    background: var(--bg-panel-4);
                    border-radius: 3px;
                    overflow: hidden;
                }

                .ws-progress-fill {
                    height: 100%;
                    background: var(--accent-green);
                    transition: width 0.3s ease;
                }

                .ws-task-list {
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                }

                .ws-task-item {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    padding: 12px 14px;
                    background: var(--bg-panel-2);
                    border: 1px solid var(--border-2);
                    border-radius: 8px;
                    transition: all 0.2s ease;
                }

                .ws-task-item:hover {
                    border-color: var(--border-3);
                }

                .ws-task-item.is-done {
                    opacity: 0.6;
                    background: var(--bg-panel-1);
                }

                .ws-task-checkbox {
                    width: 16px;
                    height: 16px;
                    cursor: pointer;
                    accent-color: var(--accent-green);
                }

                .ws-task-title {
                    flex: 1;
                    font-size: 13px;
                    color: var(--text-primary);
                    word-break: break-word;
                }

                .ws-task-item.is-done .ws-task-title {
                    text-decoration: line-through;
                    color: var(--text-muted);
                }

                .ws-task-date {
                    font-family: var(--font-mono);
                    font-size: 10px;
                    color: var(--text-muted);
                }

                .ws-task-delete-btn {
                    background: transparent;
                    border: none;
                    color: var(--text-muted);
                    cursor: pointer;
                    font-size: 12px;
                    padding: 2px 6px;
                    border-radius: 4px;
                    transition: all 0.15s ease;
                }

                .ws-task-delete-btn:hover {
                    color: #ff6b6b;
                    background: rgba(255, 107, 107, 0.15);
                }

                /* Coming Soon View */
                .ws-coming-soon {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    padding: 40px;
                }

                .ws-cs-icon {
                    font-size: 48px;
                    margin-bottom: 16px;
                    filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.5));
                }

                .ws-cs-title {
                    font-size: 20px;
                    font-weight: 600;
                    color: var(--text-primary);
                    margin-bottom: 8px;
                }

                .ws-cs-desc {
                    font-size: 13px;
                    color: var(--text-muted);
                    max-width: 380px;
                    margin-bottom: 20px;
                    line-height: 1.5;
                }

                .ws-cs-badge {
                    font-family: var(--font-mono);
                    font-size: 10px;
                    padding: 4px 10px;
                    border-radius: 20px;
                    background: rgba(189, 147, 249, 0.15);
                    color: var(--accent-purple);
                    border: 1px solid rgba(189, 147, 249, 0.3);
                    letter-spacing: 0.05em;
                }
            `;
            document.head.appendChild(style);
        }

        mount() {
            const root = document.querySelector('#win-workspace #workspace-root');
            if (!root) return;

            this.rootEl = root;
            this.injectStyles();
            this.loadState();
            this.renderShell();
            this.renderTabContent();
            this.updateHeaderCounts();
            this.bindEvents();
            this.updateFooterStatus(this.lastSaveOk ? 'Saved locally' : 'Saved in memory', this.lastSaveOk);
        }

        renderShell() {
            this.rootEl.innerHTML = `
                <div class="ws-shell">
                    <!-- Left Sidebar (260px) -->
                    <aside class="ws-sidebar">
                        <div class="ws-sidebar-header">
                            <div class="ws-brand">
                                <span>📦</span>
                                <span>Workspace</span>
                                <span class="ws-brand-badge">NOVA</span>
                            </div>
                            <div class="ws-sidebar-counts" id="ws-header-counts">
                                0 documents · 0 sheets · 0 tasks
                            </div>
                        </div>

                        <div class="ws-sidebar-voice-section">
                            <button class="ws-voice-orb-btn" id="ws-voice-btn" title="Open Nova Voice Agent">
                                <div class="ws-voice-orb-core">🎤</div>
                                <div class="ws-voice-orb-text">
                                    <span class="ws-voice-label">Start voice</span>
                                    <span class="ws-voice-sub">Nova Voice Agent</span>
                                </div>
                            </button>
                        </div>

                        <div class="ws-sidebar-menu">
                            <div class="ws-sidebar-section-title">ACTIVE ENVIRONMENT</div>
                            <div class="ws-sidebar-info-card">
                                <strong>Nova Workspace v1.0</strong><br>
                                Client-side persistent storage and productivity suite. All state syncs locally to this workstation.
                            </div>
                        </div>

                        <div class="ws-sidebar-footer">
                            <div class="ws-history-label">
                                <span class="ws-dot"></span> History
                            </div>
                            <div class="ws-storage-status" id="ws-storage-status">
                                <span class="ws-status-dot ${this.lastSaveOk ? 'success' : 'warning'}"></span>
                                ${this.lastSaveOk ? 'Saved locally' : 'Saved in memory'}
                            </div>
                        </div>
                    </aside>

                    <!-- Right Main Area -->
                    <main class="ws-main">
                        <header class="ws-topbar">
                            <nav class="ws-tabs" role="tablist">
                                <button class="ws-tab-btn ${this.state.currentTab === 'documents' ? 'active' : ''}" data-tab="documents">📄 Documents</button>
                                <button class="ws-tab-btn ${this.state.currentTab === 'sheets' ? 'active' : ''}" data-tab="sheets">📊 Sheets</button>
                                <button class="ws-tab-btn ${this.state.currentTab === 'planner' ? 'active' : ''}" data-tab="planner">📋 Planner</button>
                                <button class="ws-tab-btn ${this.state.currentTab === 'research' ? 'active' : ''}" data-tab="research">🔍 Research</button>
                                <button class="ws-tab-btn ${this.state.currentTab === 'canvas' ? 'active' : ''}" data-tab="canvas">🎨 Canvas</button>
                                <button class="ws-tab-btn ${this.state.currentTab === 'dashboard' ? 'active' : ''}" data-tab="dashboard">📈 Dashboard</button>
                                <button class="ws-tab-btn ${this.state.currentTab === 'settings' ? 'active' : ''}" data-tab="settings">⚙️ Settings</button>
                            </nav>
                        </header>

                        <div class="ws-content-pane" id="ws-content-pane"></div>
                    </main>
                </div>
            `;
        }

        updateHeaderCounts() {
            const countsEl = this.rootEl ? this.rootEl.querySelector('#ws-header-counts') : null;
            if (!countsEl) return;
            const docCount = (this.state.documents || []).length;
            const sheetCount = (this.state.sheets || []).length;
            const taskCount = (this.state.tasks || []).length;
            countsEl.textContent = `${docCount} documents · ${sheetCount} sheets · ${taskCount} tasks`;
        }

        updateFooterStatus(msg, isSuccess = true) {
            const footerEl = this.rootEl ? this.rootEl.querySelector('#ws-storage-status') : null;
            if (footerEl) {
                footerEl.innerHTML = `
                    <span class="ws-status-dot ${isSuccess ? 'success' : 'warning'}"></span>
                    ${this.escapeHtml(msg)}
                `;
            }
        }

        persistCurrentTabInput() {
            if (this.state.currentTab === 'documents') {
                const editor = this.rootEl.querySelector('.ws-editor-body');
                const activeDoc = this.getActiveDoc();
                if (editor && activeDoc) {
                    activeDoc.content = this.sanitizeHtml(editor.innerHTML);
                    const text = editor.innerText || editor.textContent || '';
                    activeDoc.wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
                    activeDoc.updatedAt = new Date().toISOString();
                }
            } else if (this.state.currentTab === 'sheets') {
                this.readGridFromDOM();
            }
        }

        switchTab(tabId) {
            if (this.state.currentTab === tabId) return;
            this.persistCurrentTabInput();
            this.state.currentTab = tabId;
            this.saveState();

            if (this.rootEl) {
                const tabButtons = this.rootEl.querySelectorAll('.ws-tab-btn');
                tabButtons.forEach(btn => {
                    btn.classList.toggle('active', btn.dataset.tab === tabId);
                });

                this.renderTabContent();
                this.updateHeaderCounts();
            }
        }

        renderTabContent() {
            if (!this.rootEl) return;
            const container = this.rootEl.querySelector('#ws-content-pane');
            if (!container) return;

            switch (this.state.currentTab) {
                case 'documents':
                    this.renderDocumentsTab(container);
                    break;
                case 'sheets':
                    this.renderSheetsTab(container);
                    break;
                case 'planner':
                    this.renderPlannerTab(container);
                    break;
                case 'research':
                    this.renderComingSoonTab(container, '🔍', 'Research Assistant', 'Deep document intelligence and live web synthesis engine.');
                    break;
                case 'canvas':
                    this.renderComingSoonTab(container, '🎨', 'Infinite Canvas', 'Visual whiteboard, node-based diagrams, and system architecture mapping.');
                    break;
                case 'dashboard':
                    this.renderComingSoonTab(container, '📈', 'Operations Dashboard', 'Real-time telemetry, bridge diagnostics, and activity feed.');
                    break;
                case 'settings':
                    this.renderComingSoonTab(container, '⚙️', 'Workspace Settings', 'Custom layout preferences, cloud synchronization, and backup rules.');
                    break;
                default:
                    container.innerHTML = `<div class="ws-empty-state"><div class="ws-empty-title">Unknown Module</div></div>`;
            }
        }

        /* ---------------- DOCUMENTS TAB ---------------- */

        renderDocumentsTab(container) {
            if (this.state.documents.length === 0) {
                container.innerHTML = `
                    <div class="ws-empty-state">
                        <div class="ws-empty-icon">📄</div>
                        <div class="ws-empty-title">No Documents Found</div>
                        <div class="ws-empty-desc">Create your first document to draft notes, specifications, or formatted content.</div>
                        <button class="ws-btn ws-btn-primary" id="ws-btn-create-first-doc">+ Create New Document</button>
                    </div>
                `;
                return;
            }

            const activeDoc = this.getActiveDoc() || this.state.documents[0];
            this.state.activeDocId = activeDoc.id;

            const docListHtml = this.state.documents.map(doc => `
                <div class="ws-doc-item ${doc.id === activeDoc.id ? 'active' : ''}" data-doc-id="${doc.id}">
                    <div>
                        <div class="ws-doc-item-title">${this.escapeHtml(doc.title)}</div>
                        <div class="ws-doc-item-meta">Rev ${doc.revision || 1} · ${this.formatDate(doc.updatedAt)}</div>
                    </div>
                    <div class="ws-doc-actions">
                        <button class="ws-doc-action-btn ws-doc-rename" data-doc-id="${doc.id}" title="Rename">✏️</button>
                        <button class="ws-doc-action-btn ws-doc-delete" data-doc-id="${doc.id}" title="Delete">🗑️</button>
                    </div>
                </div>
            `).join('');

            container.innerHTML = `
                <div class="ws-doc-layout">
                    <div class="ws-doc-sidebar">
                        <div class="ws-doc-sidebar-header">
                            <span>DOCUMENTS</span>
                            <button class="ws-btn ws-btn-xs" id="ws-btn-new-doc">+ New</button>
                        </div>
                        <div class="ws-doc-list" id="ws-doc-list">
                            ${docListHtml}
                        </div>
                    </div>

                    <div class="ws-doc-editor-pane">
                        <div class="ws-doc-toolbar">
                            <input type="text" class="ws-doc-title-input" id="ws-doc-title-input" value="${this.escapeHtml(activeDoc.title)}" placeholder="Untitled Document">
                            
                            <div class="ws-doc-fmt-group">
                                <button class="ws-fmt-btn" data-cmd="bold" title="Bold"><b>B</b></button>
                                <button class="ws-fmt-btn" data-cmd="italic" title="Italic"><i>I</i></button>
                                <button class="ws-fmt-btn" data-cmd="underline" title="Underline"><u>U</u></button>
                                <button class="ws-fmt-btn" data-cmd="strikeThrough" title="Strikethrough"><s>S</s></button>
                                <div class="ws-toolbar-sep"></div>
                                <button class="ws-fmt-btn" data-cmd="undo" title="Undo">↶</button>
                                <button class="ws-fmt-btn" data-cmd="redo" title="Redo">↷</button>
                            </div>

                            <div style="display: flex; align-items: center; gap: 8px;">
                                <span class="ws-save-status" id="ws-doc-status">All changes saved</span>
                                <button class="ws-btn ws-btn-primary" id="ws-btn-save-doc">💾 Save</button>
                            </div>
                        </div>

                        <div class="ws-editor-body" id="ws-editor-body" contenteditable="true" spellcheck="true" placeholder="Start typing your document or notes here...">${this.sanitizeHtml(activeDoc.content || '')}</div>

                        <div class="ws-doc-footer">
                            <div class="ws-doc-footer-left">
                                <span id="ws-doc-rev">Revision ${activeDoc.revision || 1}</span>
                                <span>·</span>
                                <span id="ws-doc-time">Last saved: ${this.formatTime(activeDoc.updatedAt)}</span>
                            </div>
                            <div>
                                <span id="ws-doc-word-count">${activeDoc.wordCount || 0} words</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        createDocument(title) {
            const count = this.state.documents.length + 1;
            const docTitle = (title || '').trim() || ('Untitled Document ' + count);
            const doc = {
                id: 'doc_' + Date.now(),
                title: docTitle,
                content: '<p>Start typing here...</p>',
                revision: 1,
                wordCount: 3,
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString()
            };
            this.state.documents.push(doc);
            this.state.activeDocId = doc.id;
            this.saveState();
            this.renderTabContent();
            this.updateHeaderCounts();
            return doc;
        }

        createDoc(title) {
            return this.createDocument(title);
        }

        openDoc(query) {
            if (!query) return null;
            const q = String(query).trim().toLowerCase();
            const doc = this.state.documents.find(d => d.id === query || (d.title && d.title.toLowerCase().includes(q)));
            if (doc) {
                this.state.activeDocId = doc.id;
                this.switchTab('documents');
                return doc;
            }
            return null;
        }

        deleteDoc(query, skipConfirm = true) {
            if (!query) return false;
            const q = String(query).trim().toLowerCase();
            const doc = this.state.documents.find(d => d.id === query || (d.title && d.title.toLowerCase().includes(q)));
            if (!doc) return false;
            if (!skipConfirm && !window.confirm(`Are you sure you want to delete "${doc.title}"?`)) return false;

            this.state.documents = this.state.documents.filter(d => d.id !== doc.id);
            if (this.state.activeDocId === doc.id) {
                this.state.activeDocId = this.state.documents.length > 0 ? this.state.documents[0].id : null;
            }
            this.saveState();
            this.renderTabContent();
            this.updateHeaderCounts();
            return true;
        }

        deleteDocument(docId) {
            const doc = this.state.documents.find(d => d.id === docId);
            if (!doc) return;
            if (!window.confirm(`Are you sure you want to delete "${doc.title}"?`)) return;

            this.state.documents = this.state.documents.filter(d => d.id !== docId);
            if (this.state.activeDocId === docId) {
                this.state.activeDocId = this.state.documents.length > 0 ? this.state.documents[0].id : null;
            }
            this.saveState();
            this.renderTabContent();
            this.updateHeaderCounts();
        }

        renameDocument(docId, newTitle) {
            const doc = this.state.documents.find(d => d.id === docId);
            if (!doc) return;
            doc.title = (newTitle || '').trim() || 'Untitled Document';
            doc.updatedAt = new Date().toISOString();
            this.saveState();
            this.renderTabContent();
        }

        saveCurrentDoc(explicit = false) {
            const activeDoc = this.getActiveDoc();
            const editor = this.rootEl.querySelector('#ws-editor-body');
            if (!activeDoc || !editor) return;

            if (explicit) {
                activeDoc.revision = (activeDoc.revision || 1) + 1;
            }
            activeDoc.content = this.sanitizeHtml(editor.innerHTML);
            const text = editor.innerText || editor.textContent || '';
            activeDoc.wordCount = text.trim() ? text.trim().split(/\s+/).length : 0;
            activeDoc.updatedAt = new Date().toISOString();

            this.saveState();

            const revEl = this.rootEl.querySelector('#ws-doc-rev');
            const timeEl = this.rootEl.querySelector('#ws-doc-time');
            const statusEl = this.rootEl.querySelector('#ws-doc-status');
            const wordEl = this.rootEl.querySelector('#ws-doc-word-count');

            if (revEl) revEl.textContent = `Revision ${activeDoc.revision || 1}`;
            if (timeEl) timeEl.textContent = `Last saved: ${this.formatTime(activeDoc.updatedAt)}`;
            if (statusEl) statusEl.textContent = explicit ? `Saved at ${this.formatTime(new Date())}` : 'Autosaved';
            if (wordEl) wordEl.textContent = `${activeDoc.wordCount} words`;

            const activeItem = this.rootEl.querySelector(`.ws-doc-item[data-doc-id="${activeDoc.id}"] .ws-doc-item-meta`);
            if (activeItem) activeItem.textContent = `Rev ${activeDoc.revision || 1} · ${this.formatDate(activeDoc.updatedAt)}`;
        }

        /* ---------------- SHEETS TAB ---------------- */

        renderSheetsTab(container) {
            if (this.state.sheets.length === 0) {
                container.innerHTML = `
                    <div class="ws-empty-state">
                        <div class="ws-empty-icon">📊</div>
                        <div class="ws-empty-title">No Spreadsheets Found</div>
                        <div class="ws-empty-desc">Create your first spreadsheet to calculate totals, run formulas, and export CSV files.</div>
                        <button class="ws-btn ws-btn-primary" id="ws-btn-create-first-sheet">+ Create New Sheet</button>
                    </div>
                `;
                return;
            }

            const activeSheet = this.getActiveSheet() || this.state.sheets[0];
            this.state.activeSheetId = activeSheet.id;
            if (!activeSheet.data) activeSheet.data = {};

            const optionsHtml = this.state.sheets.map(s => `
                <option value="${s.id}" ${s.id === activeSheet.id ? 'selected' : ''}>${this.escapeHtml(s.title)}</option>
            `).join('');

            // Build grid (26 cols A-Z x 50 rows)
            const cols = [];
            for (let i = 0; i < 26; i++) {
                cols.push(String.fromCharCode(65 + i));
            }

            let theadHtml = `<tr><th class="ws-corner-header">#</th>`;
            for (const col of cols) {
                theadHtml += `<th class="ws-col-header" data-col="${col}">${col}</th>`;
            }
            theadHtml += `</tr>`;

            let tbodyHtml = '';
            for (let r = 1; r <= 50; r++) {
                tbodyHtml += `<tr><th class="ws-row-header" data-row="${r}">${r}</th>`;
                for (const col of cols) {
                    const cellKey = `${col}${r}`;
                    const rawVal = activeSheet.data[cellKey];
                    let displayVal = '';
                    if (rawVal !== undefined && rawVal !== null && rawVal !== '') {
                        if (typeof rawVal === 'string' && rawVal.startsWith('=')) {
                            displayVal = this.evaluateFormula(rawVal, activeSheet.data);
                        } else {
                            displayVal = rawVal;
                        }
                    }
                    tbodyHtml += `<td class="ws-sheet-cell" data-cell="${cellKey}" data-col="${col}" data-row="${r}" contenteditable="true" spellcheck="false" data-raw="${rawVal !== undefined ? this.escapeHtml(rawVal) : ''}">${this.escapeHtml(displayVal)}</td>`;
                }
                tbodyHtml += `</tr>`;
            }

            container.innerHTML = `
                <div class="ws-sheet-layout">
                    <div class="ws-sheet-toolbar">
                        <select class="ws-sheet-select" id="ws-sheet-select">
                            ${optionsHtml}
                        </select>
                        <button class="ws-btn ws-btn-sm" id="ws-btn-new-sheet">+ New Sheet</button>
                        <button class="ws-btn ws-btn-sm" id="ws-btn-rename-sheet">Rename</button>
                        <button class="ws-btn ws-btn-sm ws-btn-danger" id="ws-btn-delete-sheet">Delete</button>

                        <div class="ws-toolbar-sep"></div>

                        <div class="ws-cell-coord" id="ws-cell-coord">A1</div>
                        <span class="ws-fx-label">fx</span>
                        <input type="text" class="ws-formula-input" id="ws-formula-input" placeholder="Type value or formula, e.g. =SUM(A1:A5)">

                        <div class="ws-toolbar-sep"></div>

                        <button class="ws-btn ws-btn-primary" id="ws-btn-save-sheet">💾 Save</button>
                        <button class="ws-btn" id="ws-btn-export-csv">📥 Export CSV</button>
                        <span class="ws-save-status" id="ws-sheet-status"></span>
                    </div>

                    <div class="ws-grid-wrapper" id="ws-grid-wrapper">
                        <table class="ws-grid-table" id="ws-grid-table">
                            <thead>${theadHtml}</thead>
                            <tbody>${tbodyHtml}</tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        createSheet(title) {
            const count = this.state.sheets.length + 1;
            const sheetTitle = (title || '').trim() || ('Sheet ' + count);
            const sheet = {
                id: 'sheet_' + Date.now(),
                title: sheetTitle,
                data: {},
                createdAt: new Date().toISOString(),
                updatedAt: new Date().toISOString()
            };
            this.state.sheets.push(sheet);
            this.state.activeSheetId = sheet.id;
            this.saveState();
            this.renderTabContent();
            this.updateHeaderCounts();
            return sheet;
        }

        openSheet(query) {
            if (!query) return null;
            const q = String(query).trim().toLowerCase();
            const sheet = this.state.sheets.find(s => s.id === query || (s.title && s.title.toLowerCase().includes(q)));
            if (sheet) {
                this.state.activeSheetId = sheet.id;
                this.switchTab('sheets');
                return sheet;
            }
            return null;
        }

        setCellValue(cellKey, value) {
            if (!cellKey) return;
            const sheet = this.getActiveSheet() || (this.state.sheets.length > 0 ? this.state.sheets[0] : this.createSheet());
            if (!sheet) return;
            if (!sheet.data) sheet.data = {};
            const key = String(cellKey).toUpperCase().trim();
            sheet.data[key] = String(value);
            sheet.updatedAt = new Date().toISOString();
            this.saveState();
            if (this.state.currentTab === 'sheets') {
                this.renderTabContent();
            }
        }

        deleteSheet(sheetId) {
            const sheet = this.state.sheets.find(s => s.id === sheetId);
            if (!sheet) return;
            if (!window.confirm(`Are you sure you want to delete "${sheet.title}"?`)) return;

            this.state.sheets = this.state.sheets.filter(s => s.id !== sheetId);
            if (this.state.activeSheetId === sheetId) {
                this.state.activeSheetId = this.state.sheets.length > 0 ? this.state.sheets[0].id : null;
            }
            this.saveState();
            this.renderTabContent();
            this.updateHeaderCounts();
        }

        renameSheet(sheetId, newTitle) {
            const sheet = this.state.sheets.find(s => s.id === sheetId);
            if (!sheet) return;
            sheet.title = (newTitle || '').trim() || 'Untitled Sheet';
            sheet.updatedAt = new Date().toISOString();
            this.saveState();
            this.renderTabContent();
        }

        readGridFromDOM() {
            const sheet = this.getActiveSheet();
            if (!sheet) return;
            if (!sheet.data) sheet.data = {};

            const cells = this.rootEl.querySelectorAll('.ws-sheet-cell');
            cells.forEach(cell => {
                const key = cell.dataset.cell;
                const raw = cell.dataset.raw !== undefined && cell.dataset.raw !== '' ? cell.dataset.raw : cell.textContent.trim();
                if (raw) {
                    sheet.data[key] = raw;
                } else {
                    delete sheet.data[key];
                }
            });
            sheet.updatedAt = new Date().toISOString();
        }

        saveCurrentSheet() {
            this.readGridFromDOM();
            this.saveState();
            const status = this.rootEl.querySelector('#ws-sheet-status');
            if (status) {
                status.textContent = 'Grid saved!';
                setTimeout(() => {
                    if (status) status.textContent = '';
                }, 2500);
            }
        }

        recalculateFormulas() {
            const sheet = this.getActiveSheet();
            if (!sheet) return;

            const cells = this.rootEl.querySelectorAll('.ws-sheet-cell');
            cells.forEach(cell => {
                const key = cell.dataset.cell;
                const raw = sheet.data[key];
                if (raw !== undefined && raw !== null && raw !== '') {
                    if (typeof raw === 'string' && raw.startsWith('=')) {
                        cell.textContent = this.evaluateFormula(raw, sheet.data);
                    } else {
                        cell.textContent = raw;
                    }
                } else {
                    cell.textContent = '';
                }
            });
        }

        exportCsv() {
            this.readGridFromDOM();
            const sheet = this.getActiveSheet();
            if (!sheet) return;

            let maxRow = 1;
            let maxCol = 1;
            for (const key of Object.keys(sheet.data || {})) {
                const m = key.match(/^([A-Z]+)([1-9]\d*)$/);
                if (m) {
                    let col = 0;
                    for (let i = 0; i < m[1].length; i++) {
                        col = col * 26 + (m[1].charCodeAt(i) - 64);
                    }
                    const row = parseInt(m[2], 10);
                    if (row > maxRow) maxRow = Math.min(row, 50);
                    if (col > maxCol) maxCol = Math.min(col, 26);
                }
            }

            const rows = [];
            for (let r = 1; r <= maxRow; r++) {
                const rowCells = [];
                for (let c = 1; c <= maxCol; c++) {
                    let colName = '';
                    let temp = c;
                    while (temp > 0) {
                        let rem = (temp - 1) % 26;
                        colName = String.fromCharCode(65 + rem) + colName;
                        temp = Math.floor((temp - 1) / 26);
                    }
                    const key = `${colName}${r}`;
                    const rawVal = sheet.data[key] || '';
                    let displayVal = rawVal;
                    if (typeof rawVal === 'string' && rawVal.startsWith('=')) {
                        displayVal = this.evaluateFormula(rawVal, sheet.data);
                    }
                    let str = String(displayVal);
                    if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
                        str = `"${str.replace(/"/g, '""')}"`;
                    }
                    rowCells.push(str);
                }
                rows.push(rowCells.join(','));
            }

            const csvContent = rows.join('\r\n');
            const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${sheet.title || 'sheet'}.csv`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        }

        /* ---------------- PLANNER TAB ---------------- */

        renderPlannerTab(container) {
            container.innerHTML = `
                <div class="ws-planner-layout">
                    <div class="ws-planner-card">
                        <div class="ws-planner-input-bar">
                            <input type="text" id="ws-planner-input" class="ws-task-input" placeholder="What needs to be done? Press Enter to add...">
                            <button class="ws-btn ws-btn-primary" id="ws-btn-add-task">+ Add Task</button>
                        </div>

                        <div class="ws-planner-meta-bar">
                            <div class="ws-filters" id="ws-planner-filters">
                                <button class="ws-filter-btn ${this.state.taskFilter === 'all' ? 'active' : ''}" data-filter="all">All</button>
                                <button class="ws-filter-btn ${this.state.taskFilter === 'active' ? 'active' : ''}" data-filter="active">Active</button>
                                <button class="ws-filter-btn ${this.state.taskFilter === 'done' ? 'active' : ''}" data-filter="done">Done</button>
                            </div>

                            <div class="ws-planner-progress" id="ws-planner-progress">
                                <!-- progress line -->
                            </div>
                        </div>

                        <div class="ws-task-list" id="ws-task-list">
                            <!-- task items -->
                        </div>
                    </div>
                </div>
            `;

            this.renderPlannerList();
        }

        renderPlannerList() {
            if (!this.rootEl) return;
            const listEl = this.rootEl.querySelector('#ws-task-list');
            const progressEl = this.rootEl.querySelector('#ws-planner-progress');
            if (!listEl || !progressEl) return;

            const tasks = this.state.tasks || [];
            const filter = this.state.taskFilter || 'all';

            const filtered = tasks.filter(t => {
                if (filter === 'active') return !t.done;
                if (filter === 'done') return t.done;
                return true;
            });

            const total = tasks.length;
            const doneCount = tasks.filter(t => t.done).length;
            const pct = total === 0 ? 0 : Math.round((doneCount / total) * 100);

            progressEl.innerHTML = `
                <span>${doneCount} of ${total} done (${pct}%)</span>
                <div class="ws-progress-bar">
                    <div class="ws-progress-fill" style="width: ${pct}%;"></div>
                </div>
            `;

            if (filtered.length === 0) {
                listEl.innerHTML = `
                    <div style="padding: 24px; text-align: center; color: var(--text-muted); font-size: 13px;">
                        ${total === 0 ? 'No tasks yet. Add a task above to get started.' : 'No tasks match the active filter.'}
                    </div>
                `;
                return;
            }

            listEl.innerHTML = filtered.map(t => `
                <div class="ws-task-item ${t.done ? 'is-done' : ''}" data-task-id="${t.id}">
                    <input type="checkbox" class="ws-task-checkbox" data-task-id="${t.id}" ${t.done ? 'checked' : ''}>
                    <span class="ws-task-title">${this.escapeHtml(t.text)}</span>
                    <span class="ws-task-date">${this.formatDate(t.createdAt)}</span>
                    <button class="ws-task-delete-btn" data-task-id="${t.id}" title="Delete Task">✕</button>
                </div>
            `).join('');
        }

        addTask(text, priority = 'normal') {
            const clean = (text || '').trim();
            if (!clean) return null;

            const task = {
                id: 'task_' + Date.now(),
                text: clean,
                priority: priority,
                done: false,
                createdAt: new Date().toISOString()
            };
            this.state.tasks.push(task);
            this.saveState();
            this.renderPlannerList();
            this.updateHeaderCounts();
            return task;
        }

        toggleTask(taskId) {
            const task = this.state.tasks.find(t => t.id === taskId);
            if (!task) return;
            task.done = !task.done;
            this.saveState();
            this.renderPlannerList();
            this.updateHeaderCounts();
        }

        completeTask(query) {
            if (!query) return false;
            const q = String(query).trim().toLowerCase();
            const task = this.state.tasks.find(t => t.id === query || (t.text && t.text.toLowerCase().includes(q)));
            if (!task) return false;
            task.done = true;
            this.saveState();
            this.renderPlannerList();
            this.updateHeaderCounts();
            return true;
        }

        deleteTask(taskIdOrQuery) {
            if (!taskIdOrQuery) return false;
            const q = String(taskIdOrQuery).trim().toLowerCase();
            const initialLen = this.state.tasks.length;
            this.state.tasks = this.state.tasks.filter(t => t.id !== taskIdOrQuery && !(t.text && t.text.toLowerCase().includes(q)));
            const changed = this.state.tasks.length !== initialLen;
            if (changed) {
                this.saveState();
                this.renderPlannerList();
                this.updateHeaderCounts();
            }
            return changed;
        }

        /* ---------------- COMING SOON VIEW ---------------- */

        renderComingSoonTab(container, icon, title, desc) {
            container.innerHTML = `
                <div class="ws-coming-soon">
                    <div class="ws-cs-icon">${icon}</div>
                    <div class="ws-cs-title">${title}</div>
                    <div class="ws-cs-desc">${desc}</div>
                    <span class="ws-cs-badge">COMING SOON IN NOVA OS v1.2</span>
                </div>
            `;
        }

        /* ---------------- EVENT HANDLING (DELEGATION) ---------------- */

        bindEvents() {
            if (!this.rootEl) return;

            // Voice Orb Button
            const voiceBtn = this.rootEl.querySelector('#ws-voice-btn');
            if (voiceBtn) {
                voiceBtn.addEventListener('click', () => {
                    if (window.WindowManager && typeof window.WindowManager.openApp === 'function') {
                        window.WindowManager.openApp('nova-voice');
                    }
                });
            }

            // Tab Switching
            const topbar = this.rootEl.querySelector('.ws-topbar');
            if (topbar) {
                topbar.addEventListener('click', (e) => {
                    const btn = e.target.closest('.ws-tab-btn');
                    if (btn && btn.dataset.tab) {
                        this.switchTab(btn.dataset.tab);
                    }
                });
            }

            // Click Delegations inside Content Pane
            const contentPane = this.rootEl.querySelector('#ws-content-pane');
            if (!contentPane) return;

            contentPane.addEventListener('mousedown', (e) => {
                // Prevent contenteditable focus loss on toolbar format buttons
                const fmtBtn = e.target.closest('.ws-fmt-btn');
                if (fmtBtn) {
                    e.preventDefault();
                    const cmd = fmtBtn.dataset.cmd;
                    if (cmd) {
                        document.execCommand(cmd, false, null);
                        this.saveCurrentDoc(false);
                    }
                }
            });

            contentPane.addEventListener('click', (e) => {
                // Documents
                if (e.target.closest('#ws-btn-create-first-doc') || e.target.closest('#ws-btn-new-doc')) {
                    this.createDocument();
                    return;
                }
                const renameDocBtn = e.target.closest('.ws-doc-rename');
                if (renameDocBtn) {
                    e.stopPropagation();
                    const docId = renameDocBtn.dataset.docId;
                    const doc = this.state.documents.find(d => d.id === docId);
                    if (doc) {
                        const newTitle = window.prompt('Rename document:', doc.title);
                        if (newTitle !== null) this.renameDocument(docId, newTitle);
                    }
                    return;
                }
                const deleteDocBtn = e.target.closest('.ws-doc-delete');
                if (deleteDocBtn) {
                    e.stopPropagation();
                    this.deleteDocument(deleteDocBtn.dataset.docId);
                    return;
                }
                const docItem = e.target.closest('.ws-doc-item');
                if (docItem) {
                    const docId = docItem.dataset.docId;
                    if (docId !== this.state.activeDocId) {
                        this.persistCurrentTabInput();
                        this.state.activeDocId = docId;
                        this.renderDocumentsTab(contentPane);
                    }
                    return;
                }
                if (e.target.closest('#ws-btn-save-doc')) {
                    this.saveCurrentDoc(true);
                    return;
                }

                // Sheets
                if (e.target.closest('#ws-btn-create-first-sheet') || e.target.closest('#ws-btn-new-sheet')) {
                    this.createSheet();
                    return;
                }
                if (e.target.closest('#ws-btn-rename-sheet')) {
                    const sheet = this.getActiveSheet();
                    if (sheet) {
                        const newTitle = window.prompt('Rename sheet:', sheet.title);
                        if (newTitle !== null) this.renameSheet(sheet.id, newTitle);
                    }
                    return;
                }
                if (e.target.closest('#ws-btn-delete-sheet')) {
                    const sheet = this.getActiveSheet();
                    if (sheet) {
                        this.deleteSheet(sheet.id);
                    }
                    return;
                }
                if (e.target.closest('#ws-btn-save-sheet')) {
                    this.saveCurrentSheet();
                    return;
                }
                if (e.target.closest('#ws-btn-export-csv')) {
                    this.exportCsv();
                    return;
                }

                // Planner
                if (e.target.closest('#ws-btn-add-task')) {
                    const input = this.rootEl.querySelector('#ws-planner-input');
                    if (input) {
                        this.addTask(input.value);
                        input.value = '';
                    }
                    return;
                }
                const taskDelBtn = e.target.closest('.ws-task-delete-btn');
                if (taskDelBtn) {
                    this.deleteTask(taskDelBtn.dataset.taskId);
                    return;
                }
                const filterBtn = e.target.closest('.ws-filter-btn');
                if (filterBtn && filterBtn.dataset.filter) {
                    this.state.taskFilter = filterBtn.dataset.filter;
                    const buttons = this.rootEl.querySelectorAll('.ws-filter-btn');
                    buttons.forEach(b => b.classList.toggle('active', b.dataset.filter === this.state.taskFilter));
                    this.saveState();
                    this.renderPlannerList();
                    return;
                }
            });

            // Change Events
            contentPane.addEventListener('change', (e) => {
                if (e.target.id === 'ws-sheet-select') {
                    this.persistCurrentTabInput();
                    this.state.activeSheetId = e.target.value;
                    this.renderSheetsTab(contentPane);
                    return;
                }
                if (e.target.classList.contains('ws-task-checkbox')) {
                    this.toggleTask(e.target.dataset.taskId);
                    return;
                }
                if (e.target.id === 'ws-doc-title-input') {
                    const activeDoc = this.getActiveDoc();
                    if (activeDoc) {
                        activeDoc.title = e.target.value.trim() || 'Untitled Document';
                        activeDoc.updatedAt = new Date().toISOString();
                        this.saveState();
                        const activeItemTitle = this.rootEl.querySelector(`.ws-doc-item[data-doc-id="${activeDoc.id}"] .ws-doc-item-title`);
                        if (activeItemTitle) activeItemTitle.textContent = activeDoc.title;
                    }
                    return;
                }
            });

            // Input / Keystroke Events
            contentPane.addEventListener('input', (e) => {
                // Document Typing
                if (e.target.id === 'ws-editor-body') {
                    const text = e.target.innerText || e.target.textContent || '';
                    const words = text.trim() ? text.trim().split(/\s+/).length : 0;
                    const wordEl = this.rootEl.querySelector('#ws-doc-word-count');
                    if (wordEl) wordEl.textContent = `${words} words`;

                    const statusEl = this.rootEl.querySelector('#ws-doc-status');
                    if (statusEl) statusEl.textContent = 'Unsaved changes...';

                    clearTimeout(this.docAutosaveTimer);
                    this.docAutosaveTimer = setTimeout(() => {
                        this.saveCurrentDoc(false);
                    }, 800);
                    return;
                }

                // Sheet Cell Typing
                if (e.target.classList.contains('ws-sheet-cell')) {
                    const cellKey = e.target.dataset.cell;
                    const rawVal = e.target.textContent;
                    e.target.dataset.raw = rawVal;
                    const formulaInput = this.rootEl.querySelector('#ws-formula-input');
                    if (formulaInput) formulaInput.value = rawVal;
                    return;
                }

                // Sheet Formula Bar Typing
                if (e.target.id === 'ws-formula-input') {
                    const activeCell = this.rootEl.querySelector(`.ws-sheet-cell[data-cell="${this.activeCellKey}"]`);
                    if (activeCell) {
                        activeCell.dataset.raw = e.target.value;
                        activeCell.textContent = e.target.value;
                    }
                    return;
                }
            });

            // Keydown (e.g. Enter on inputs)
            contentPane.addEventListener('keydown', (e) => {
                if (e.target.id === 'ws-planner-input' && e.key === 'Enter') {
                    e.preventDefault();
                    this.addTask(e.target.value);
                    e.target.value = '';
                    return;
                }
                if (e.target.id === 'ws-formula-input' && e.key === 'Enter') {
                    e.preventDefault();
                    e.target.blur();
                    const activeCell = this.rootEl.querySelector(`.ws-sheet-cell[data-cell="${this.activeCellKey}"]`);
                    if (activeCell) {
                        activeCell.focus();
                    }
                    return;
                }
                if (e.target.classList.contains('ws-sheet-cell') && e.key === 'Enter') {
                    e.preventDefault();
                    e.target.blur();
                    return;
                }
            });

            // Grid Cell Focusin / Focusout
            contentPane.addEventListener('focusin', (e) => {
                if (e.target.classList.contains('ws-sheet-cell')) {
                    const cellKey = e.target.dataset.cell;
                    this.activeCellKey = cellKey;

                    const coordEl = this.rootEl.querySelector('#ws-cell-coord');
                    if (coordEl) coordEl.textContent = cellKey;

                    const sheet = this.getActiveSheet();
                    const rawVal = sheet && sheet.data && sheet.data[cellKey] !== undefined ? sheet.data[cellKey] : '';
                    e.target.dataset.raw = rawVal;
                    e.target.textContent = rawVal;

                    const formulaInput = this.rootEl.querySelector('#ws-formula-input');
                    if (formulaInput) formulaInput.value = rawVal;

                    this.rootEl.querySelectorAll('.ws-sheet-cell.active-cell').forEach(c => c.classList.remove('active-cell'));
                    e.target.classList.add('active-cell');
                }
            });

            contentPane.addEventListener('focusout', (e) => {
                if (e.target.classList.contains('ws-sheet-cell')) {
                    const cellKey = e.target.dataset.cell;
                    const sheet = this.getActiveSheet();
                    if (!sheet) return;
                    if (!sheet.data) sheet.data = {};

                    const raw = e.target.textContent.trim();
                    if (raw) {
                        sheet.data[cellKey] = raw;
                        e.target.dataset.raw = raw;
                    } else {
                        delete sheet.data[cellKey];
                        delete e.target.dataset.raw;
                    }

                    this.recalculateFormulas();
                    this.saveState();
                } else if (e.target.id === 'ws-formula-input') {
                    const sheet = this.getActiveSheet();
                    if (!sheet) return;
                    if (!sheet.data) sheet.data = {};

                    const cellKey = this.activeCellKey;
                    const raw = e.target.value.trim();
                    if (raw) {
                        sheet.data[cellKey] = raw;
                    } else {
                        delete sheet.data[cellKey];
                    }

                    this.recalculateFormulas();
                    this.saveState();
                }
            });
        }
    }

    // Expose instance on window
    window.Workspace = new WorkspaceApp();
})();
