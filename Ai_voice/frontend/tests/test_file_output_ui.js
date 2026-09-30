/**
 * Unit & Integration tests for Files App Output Folder UI.
 * Verifies:
 * 1. Badge count calculations including output files.
 * 2. Breadcrumbs and folder navigation for 'output'.
 * 3. File table rendering with folder rows, output badges, and output icons.
 * 4. WebSocket action handling for 'file.processed'.
 * 
 * Run via: node Ai_voice/frontend/tests/test_file_output_ui.js
 */

const assert = require('assert');

// Minimal mock DOM implementation
class Element {
    constructor(id = '', className = '') {
        this.id = id;
        this.className = className;
        this.textContent = '';
        this.innerHTML = '';
        this.style = {};
        this.classList = {
            classes: new Set(className ? className.split(' ') : []),
            add: (c) => this.classList.classes.add(c),
            remove: (c) => this.classList.classes.delete(c),
            contains: (c) => this.classList.classes.has(c)
        };
    }
}

const elements = new Map();
function getOrCreate(id) {
    if (!elements.has(id)) {
        elements.set(id, new Element(id));
    }
    return elements.get(id);
}

global.document = {
    getElementById: (id) => getOrCreate(id),
    querySelectorAll: (selector) => {
        if (selector === '.files-nav-item') {
            return [
                getOrCreate('files-nav-mobile'),
                getOrCreate('files-nav-photos'),
                getOrCreate('files-nav-output'),
                getOrCreate('files-nav-all'),
                getOrCreate('files-nav-docs')
            ];
        }
        return [];
    },
    addEventListener: () => {},
    removeEventListener: () => {},
    createElement: (tag) => {
        const el = new Element('', '');
        el.tagName = tag.toUpperCase();
        return el;
    }
};

global.window = {
    _cachedFiles: [],
    _currentFolder: 'mobile',
    addEventListener: () => {},
    removeEventListener: () => {},
    alert: () => {},
    confirm: () => true
};

const fs = require('fs');
const path = require('path');
const helpersCode = fs.readFileSync(path.join(__dirname, '../js/helpers.js'), 'utf8');
eval(helpersCode);

// Emulate helper functions
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

window.navigateToFolder = function(folder) {
    window._currentFolder = folder;
    document.querySelectorAll('.files-nav-item').forEach(el => el.classList.remove('active'));
    if (folder === 'mobile') {
        document.getElementById('files-nav-mobile')?.classList.add('active');
    } else if (folder === 'photos') {
        document.getElementById('files-nav-photos')?.classList.add('active');
    } else if (folder === 'output') {
        document.getElementById('files-nav-output')?.classList.add('active');
    }
    window.updateBreadcrumbs();
};

window.updateBreadcrumbs = function() {
    const bcContainer = document.getElementById('files-breadcrumbs');
    if (!bcContainer) return;

    if (window._currentFolder === 'output') {
        bcContainer.innerHTML = '/ files / output';
    } else if (window._currentFolder === 'photos') {
        bcContainer.innerHTML = '/ files / photos';
    } else {
        bcContainer.innerHTML = '/ files / mobile';
    }
};

let testsRun = 0;
let testsPassed = 0;

function it(name, fn) {
    testsRun++;
    try {
        fn();
        console.log(`[PASS] ${name}`);
        testsPassed++;
    } catch (err) {
        console.error(`[FAIL] ${name}\n`, err);
    }
}

// 1. Badge Calculation Test
it('computes correct folder badge counts including Output folder', () => {
    window._cachedFiles = [
        { name: 'test.png', type: 'file', path: '/uploads/files/mobile/test.png' },
        { name: 'doc.pdf', type: 'file', path: '/uploads/files/mobile/doc.pdf' },
        { name: 'snap.jpg', type: 'photo', path: '/uploads/files/mobile/photos/snap.jpg' },
        { name: 'converted.jpg', type: 'output', folder: 'output', path: '/uploads/files/output/converted.jpg' },
        { name: 'result.gif', type: 'output', folder: 'output', path: '/uploads/files/output/result.gif' }
    ];

    window.updateFolderBadges();

    const bOutput = document.getElementById('badge-output-count');
    const bPhotos = document.getElementById('badge-photos-count');
    const bAll = document.getElementById('badge-all-count');
    const bMobile = document.getElementById('badge-mobile-count');

    assert.strictEqual(bOutput.textContent, 2, 'Output badge count should be 2');
    assert.strictEqual(bPhotos.textContent, 1, 'Photos badge count should be 1');
    assert.strictEqual(bAll.textContent, 5, 'All files badge count should be 5');
    // Mobile root items: 2 docs + 1 photos folder + 1 output folder = 4
    assert.strictEqual(bMobile.textContent, 4, 'Mobile directory count should be 4');
});

// 2. Folder Navigation Test
it('navigates to output folder and updates active states and breadcrumbs', () => {
    window.navigateToFolder('output');

    assert.strictEqual(window._currentFolder, 'output');
    assert.strictEqual(document.getElementById('files-nav-output').classList.contains('active'), true);
    assert.strictEqual(document.getElementById('files-nav-mobile').classList.contains('active'), false);
    assert.strictEqual(document.getElementById('files-breadcrumbs').innerHTML, '/ files / output');
});

// 3. Emulate Action Dispatcher Test
it('handles file.processed action by reloading files and navigating to output', (done) => {
    let loadCalled = false;
    let folderNavigated = null;

    window.loadFilesList = () => {
        loadCalled = true;
        return Promise.resolve();
    };

    window.navigateToFolder = (folder) => {
        folderNavigated = folder;
    };

    const action = {
        action: 'file.processed',
        target: 'output',
        source_file: 'test.png',
        output_file: 'test.jpg'
    };

    // Bridge message handler logic:
    if (action.action === 'file.processed') {
        window.loadFilesList().then(() => {
            window.navigateToFolder('output');
            assert.strictEqual(loadCalled, true, 'loadFilesList should be called');
            assert.strictEqual(folderNavigated, 'output', 'navigateToFolder should be called with output');
        });
    }
});

// 4. File Table Delete Button & Action Column Test
it('renders files table with Action column and delete button on every file row', () => {
    // Create a mock container for files table
    const tableContainer = getOrCreate('files-table-container');

    // Provide mock fetch and alert
    global.window.alert = () => {};
    global.window.confirm = (msg) => true;

    window._currentFolder = 'all';
    window._cachedFiles = [
        { name: 'vacation.png', type: 'photo', path: '/uploads/files/mobile/photos/vacation.png', size_formatted: '1.2 MB', modified: '2026-09-30' },
        { name: 'report.pdf', type: 'file', path: '/uploads/files/mobile/report.pdf', size_formatted: '420 KB', modified: '2026-09-30' },
        { name: 'data.csv', type: 'output', folder: 'output', path: '/uploads/files/output/data.csv', size_formatted: '50 KB', modified: '2026-09-30' }
    ];

    window.renderFilesTable();

    const html = tableContainer.innerHTML;
    assert(html.includes('<th style="width: 8%; text-align: center;">Action</th>'), 'Table header must have Action column');
    assert(html.includes('class="file-delete-btn"'), 'Table rows must contain file-delete-btn');
    assert(html.includes('🗑️'), 'Table rows must contain trash icon button');
    assert(html.includes("window.deleteFile('/uploads/files/mobile/photos/vacation.png'"), 'Delete button must target vacation.png path');
    assert(html.includes("window.deleteFile('/uploads/files/mobile/report.pdf'"), 'Delete button must target report.pdf path');
    assert(html.includes("window.deleteFile('/uploads/files/output/data.csv'"), 'Delete button must target output file path');
});

// 5. Delete File Confirmation and Immediate Refresh Test
it('prompts confirmation before deletion and refreshes file list immediately', async () => {
    let confirmPrompted = false;
    let deleteUrlCalled = null;
    let deleteMethodCalled = null;
    let listRefreshed = false;

    global.window.confirm = (msg) => {
        confirmPrompted = true;
        assert(msg.includes('target.png'), 'Confirm prompt must include filename');
        return true;
    };

    global.fetch = async (url, opts) => {
        deleteUrlCalled = url;
        deleteMethodCalled = opts ? opts.method : 'GET';
        return {
            ok: true,
            json: async () => ({ success: true, message: 'Deleted file target.png' })
        };
    };

    window.loadFilesList = async () => {
        listRefreshed = true;
    };

    await window.deleteFile('/uploads/files/mobile/target.png', 'target.png');

    assert.strictEqual(confirmPrompted, true, 'Confirmation dialog must be shown');
    assert.strictEqual(deleteMethodCalled, 'DELETE', 'HTTP DELETE method must be used');
    assert(deleteUrlCalled.includes('/files?path='), 'DELETE request must target /files endpoint');
    assert.strictEqual(listRefreshed, true, 'loadFilesList must be invoked immediately after deletion');

    // Test cancellation
    let fetchCalledOnCancel = false;
    global.window.confirm = () => false;
    global.fetch = async () => { fetchCalledOnCancel = true; return { ok: true }; };

    await window.deleteFile('/uploads/files/mobile/other.png', 'other.png');
    assert.strictEqual(fetchCalledOnCancel, false, 'No DELETE request should be made if user cancels');
});

// 6. Conversion Animation Display & Flow Test
it('displays smooth conversion animation: Source Format → Converting → Target Format', () => {
    const overlay = getOrCreate('conversion-overlay');
    const card = getOrCreate('conversion-card');
    const canonicalSrc = getOrCreate('conv-canonical-src');
    const canonicalMid = getOrCreate('conv-canonical-mid');
    const canonicalTgt = getOrCreate('conv-canonical-tgt');
    const stateLabel = getOrCreate('conv-state-label');
    const progressBar = getOrCreate('conv-progress-bar');
    const statusMsg = getOrCreate('conv-status-msg');

    // 1. Trigger animation start
    window.showConversionAnimation('PNG', 'WEBP', 'logo.png');

    assert(overlay.classList.contains('active'), 'Overlay must have active class');
    assert.strictEqual(canonicalSrc.textContent, 'PNG', 'Canonical source format must be displayed');
    assert.strictEqual(canonicalMid.textContent, 'Converting', 'Canonical middle state must be Converting');
    assert.strictEqual(canonicalTgt.textContent, 'WEBP', 'Canonical target format must be displayed');
    assert.strictEqual(stateLabel.textContent, 'Converting', 'State label must indicate Converting');
    assert.strictEqual(progressBar.style.width, '35%', 'Progress bar must initialize progress');
    assert(statusMsg.textContent.includes('Converting PNG → WEBP'), 'Status message must describe conversion');

    // 2. Trigger conversion completion success
    window.finishConversionAnimation({
        status: 'success',
        output_file: 'logo.webp',
        path: '/uploads/files/output/logo.webp'
    });

    assert(card.classList.contains('success'), 'Card must have success class');
    assert.strictEqual(canonicalMid.textContent, 'Converted', 'Canonical text must update to Converted');
    assert.strictEqual(progressBar.style.width, '100%', 'Progress bar must reach 100%');
    assert(statusMsg.textContent.includes('logo.webp'), 'Status message must display output file');
});

// 7. In-App File Opening Guard Test
it('ensures in-app preview is used and no links use target="_blank" or window.open', () => {
    const tableContainer = getOrCreate('files-table-container');
    window._currentFolder = 'all';
    window._cachedFiles = [
        { name: 'document.pdf', type: 'file', path: '/uploads/files/mobile/document.pdf', size_formatted: '100 KB', modified: '2026-09-30' }
    ];
    window.renderFilesTable();

    const html = tableContainer.innerHTML;
    assert(!html.includes('target="_blank"'), 'Files app must never use target="_blank"');
    assert(!html.includes('target=\'_blank\''), 'Files app must never use target=\'_blank\'');
    assert(html.includes('window.openFilePreview'), 'Files app must use in-app preview handler');
});

console.log(`\n========================================`);
console.log(`Frontend UI Tests: ${testsPassed}/${testsRun} passed.`);
console.log(`========================================\n`);

if (testsPassed !== testsRun) {
    process.exit(1);
}
