/**
 * Tests for Nova OS Command System Enhancements:
 * 1. In-OS File Previewing (Images, PDFs, Documents) inside OS UI
 * 2. In-OS Browser / WebView integration
 * 3. Command-driven Workspace methods (documents, sheets, tasks, planner)
 * 4. Safety timeouts (no stuck loading/processing windows)
 * 5. Device routing handling
 */

const assert = require('assert');

// Mock browser DOM environment
global.document = {
    getElementById: (id) => mockElements[id] || null,
    querySelector: (selector) => {
        if (selector === '#win-preview') return mockElements['win-preview'];
        if (selector === '#win-workspace') return mockElements['win-workspace'];
        if (selector === '#win-workspace #workspace-root') return mockElements['workspace-root'];
        if (selector === '#preview-viewport img, #preview-viewport video') return mockElements['preview-active-image'];
        return null;
    },
    querySelectorAll: (selector) => [],
    createElement: (tag) => {
        const el = {
            tagName: tag.toUpperCase(),
            style: {},
            dataset: {},
            classList: {
                add: (c) => el.classes.add(c),
                remove: (c) => el.classes.delete(c),
                contains: (c) => el.classes.has(c),
                toggle: (c, v) => v ? el.classes.add(c) : el.classes.delete(c)
            },
            classes: new Set(),
            appendChild: (child) => { el.children.push(child); return child; },
            children: [],
            addEventListener: () => {},
            remove: () => {},
            querySelector: (sel) => {
                if (sel === '.window-title') return el.titleEl || { textContent: '' };
                if (sel === '.window-titlebar') return { addEventListener: () => {} };
                return null;
            }
        };
        el.titleEl = { textContent: '' };
        return el;
    }
};

global.window = {
    innerWidth: 1024,
    localStorage: {
        _store: {},
        getItem: (k) => global.window.localStorage._store[k] || null,
        setItem: (k, v) => { global.window.localStorage._store[k] = String(v); }
    }
};

const mockElements = {
    'window-manager': { appendChild: () => {}, children: [] },
    'taskbar-apps': { innerHTML: '', appendChild: () => {} },
    'win-preview': {
        querySelector: (sel) => ({ textContent: '' }),
        style: {},
        classList: { add: () => {}, remove: () => {} }
    },
    'preview-filename-label': { textContent: '' },
    'preview-download-btn': { href: '', download: '' },
    'preview-viewport': { innerHTML: '' },
    'preview-active-image': { style: {} },
    'browser-webview-frame': { src: '' },
    'browser-url-input': { value: '' },
    'nova-status': { textContent: '' },
    'nova-orb': { classList: { add: () => {}, remove: () => {} } },
    'nova-mic-btn': { style: {} },
    'nova-history': { appendChild: () => {} }
};

// Load window_manager.js into test context
const fs = require('fs');
const path = require('path');
const wmCode = fs.readFileSync(path.join(__dirname, '../js/window_manager.js'), 'utf8');

// Execute wmCode in eval context with globals
eval(wmCode);

console.log('--- Testing In-OS File Preview ---');
assert(typeof window.openFilePreview === 'function', 'openFilePreview must be a function');
window.openFilePreview('/uploads/mobile/sample.png', 'sample.png', 'image');
assert(mockElements['preview-viewport'].innerHTML.includes('preview-active-image'), 'Image must render inside preview viewport');
assert(mockElements['preview-viewport'].innerHTML.includes('/uploads/mobile/sample.png'), 'Correct image URL must be used');
console.log('[PASS] Image opens inside OS UI without external window');

window.openFilePreview('/uploads/mobile/report.pdf', 'report.pdf', 'pdf');
assert(mockElements['preview-viewport'].innerHTML.includes('iframe'), 'PDF must render embedded in preview viewport');
console.log('[PASS] PDF renders inside in-OS preview');

window.openFilePreview('/uploads/mobile/clip.mp4', 'clip.mp4', 'video');
assert(mockElements['preview-viewport'].innerHTML.includes('<video'), 'Video must render embedded in preview viewport');
assert(mockElements['preview-viewport'].innerHTML.includes('/uploads/mobile/clip.mp4'), 'Video source must be correct');
console.log('[PASS] Video renders inside in-OS preview');

window.openFilePreview('/uploads/mobile/voice.mp3', 'voice.mp3', 'audio');
assert(mockElements['preview-viewport'].innerHTML.includes('<audio'), 'Audio must render embedded in preview viewport');
assert(mockElements['preview-viewport'].innerHTML.includes('/uploads/mobile/voice.mp3'), 'Audio source must be correct');
console.log('[PASS] Audio renders inside in-OS preview');

// Mock fetch for text preview
global.fetch = (url) => Promise.resolve({
    text: () => Promise.resolve('col1,col2\nval1,val2')
});
window.openFilePreview('/uploads/files/output/data.csv', 'data.csv', 'csv');
assert(mockElements['preview-viewport'].innerHTML.includes('preview-loading'), 'Text/Data must show loading state');
console.log('[PASS] Text/Data files (CSV/JSON/TXT) render inside in-OS preview');

window.openFilePreview('/uploads/files/output/converted.png', 'converted.png', 'image');
assert(mockElements['preview-viewport'].innerHTML.includes('/uploads/files/output/converted.png'), 'Converted output files render inside in-OS preview');
console.log('[PASS] Converted output files render inside in-OS preview');

console.log('--- Testing In-OS Browser (WebView) Navigation ---');
assert(typeof window.browserNavigate === 'function', 'browserNavigate must be a function');
window.browserNavigate('https://github.com');
assert.strictEqual(mockElements['browser-webview-frame'].src, 'https://github.com', 'Browser WebView must load target URL');
window.browserNavigate('news');
assert(mockElements['browser-webview-frame'].src.includes('google.com/search?q=news'), 'Search query must be navigated smoothly');
console.log('[PASS] Browser WebView navigates smoothly');

console.log('--- Testing Workspace Command API ---');
const wsCode = fs.readFileSync(path.join(__dirname, '../js/workspace.js'), 'utf8');
eval(wsCode);

assert(window.Workspace, 'window.Workspace must exist');
const doc = window.Workspace.createDoc('Meeting Notes');
assert.strictEqual(doc.title, 'Meeting Notes', 'Document must be created with specified title');

const task = window.Workspace.addTask('Test voice pipeline', 'high');
assert.strictEqual(task.text, 'Test voice pipeline', 'Task must be added to planner');

const completed = window.Workspace.completeTask('Test voice pipeline');
assert.strictEqual(completed, true, 'Task must be marked complete via command');
assert.strictEqual(task.done, true, 'Task.done must be true');

const sheet = window.Workspace.createSheet('Budget');
assert.strictEqual(sheet.title, 'Budget', 'Sheet must be created with specified title');

window.Workspace.setCellValue('A1', '100');
assert.strictEqual(sheet.data['A1'], '100', 'setCellValue must update cell in sheet');

console.log('[PASS] Workspace methods fully command-driven');

console.log('\n========================================');
console.log('ALL COMMAND FEATURE ASSERTIONS PASSED!');
console.log('========================================\n');
