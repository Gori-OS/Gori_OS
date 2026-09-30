/**
 * Integration unit test for WindowManager and BridgeClient close flow.
 * Validates that:
 * 1. app.close action from bridge message calls window.WindowManager.closeWindow(target)
 * 2. The corresponding application window is removed from DOM and WindowManager map
 * 3. Unrelated applications remain open and unaffected
 * 4. All 6 app targets (terminal, files, editor, settings, workspace, nova-voice) function correctly
 * Run with: node Ai_voice/frontend/tests/test_window_close.js
 */

const fs = require('fs');
const path = require('path');

// Simple DOM Mock
class MockElement {
    constructor(tagName, id = '') {
        this.tagName = tagName;
        this.id = id;
        this.className = '';
        this.children = [];
        this.parentElement = null;
        this.style = {};
        this.dataset = {};
        this._innerHTML = '';
        this.listeners = {};
    }

    get innerHTML() {
        return this._innerHTML;
    }

    set innerHTML(val) {
        this._innerHTML = val;
        this.children = [];
    }

    get textContent() {
        return this._textContent || '';
    }

    set textContent(val) {
        this._textContent = val;
    }

    appendChild(child) {
        child.parentElement = this;
        this.children.push(child);
        return child;
    }

    remove() {
        if (this.parentElement) {
            const idx = this.parentElement.children.indexOf(this);
            if (idx !== -1) {
                this.parentElement.children.splice(idx, 1);
            }
            this.parentElement = null;
        }
    }

    addEventListener(event, handler) {
        if (!this.listeners[event]) this.listeners[event] = [];
        this.listeners[event].push(handler);
    }

    querySelector(selector) {
        return new MockElement('div');
    }

    querySelectorAll(selector) {
        return [];
    }

    get classList() {
        const self = this;
        return {
            add: (cls) => {
                const classes = (self.className || '').split(' ').filter(Boolean);
                if (!classes.includes(cls)) classes.push(cls);
                self.className = classes.join(' ');
            },
            remove: (cls) => {
                const classes = (self.className || '').split(' ').filter(Boolean);
                self.className = classes.filter(c => c !== cls).join(' ');
            },
            contains: (cls) => (self.className || '').split(' ').includes(cls)
        };
    }
}

const mockWindowContainer = new MockElement('div', 'window-manager');
const mockTaskbarApps = new MockElement('div', 'taskbar-apps');
const mockHistory = new MockElement('div', 'nova-history');

global.window = global;
global.document = {
    getElementById: (id) => {
        if (id === 'window-manager') return mockWindowContainer;
        if (id === 'taskbar-apps') return mockTaskbarApps;
        if (id === 'nova-history') return mockHistory;
        return new MockElement('div', id);
    },
    createElement: (tag) => new MockElement(tag)
};

// Mock SpeechService
let speechStopCalled = false;
global.window.SpeechService = {
    isActive: () => true,
    stop: () => { speechStopCalled = true; }
};

// Load WindowManager code
const wmCode = fs.readFileSync(path.join(__dirname, '../js/window_manager.js'), 'utf8');
eval(wmCode);

// Load BridgeClient class definition and inspect handleMessage
const bcCode = fs.readFileSync(path.join(__dirname, '../js/bridge_client.js'), 'utf8');
// Mock WebSocket and fetch
global.WebSocket = class {
    constructor() {}
    send() {}
};
global.fetch = () => Promise.resolve({ ok: false });

eval(bcCode);

// Test assertions
let failures = 0;
function assert(cond, msg) {
    if (cond) {
        console.log(`[PASS] ${msg}`);
    } else {
        console.error(`[FAIL] ${msg}`);
        failures++;
    }
}

console.log('--- Testing WindowManager & BridgeClient App Close Flow ---');

const apps = ['terminal', 'files', 'editor', 'settings', 'workspace', 'nova-voice'];

// 1. Open all 6 apps
apps.forEach((appId) => {
    window.WindowManager.openApp(appId);
});

assert(window.WindowManager.windows.size === 6, 'All 6 applications opened in WindowManager');
assert(mockWindowContainer.children.length === 6, 'All 6 window DOM elements attached to container');

// Verify all 6 are present
apps.forEach((appId) => {
    assert(window.WindowManager.windows.has(appId), `WindowManager contains '${appId}'`);
    assert(mockWindowContainer.children.some(c => c.id === `win-${appId}`), `DOM contains 'win-${appId}'`);
});

// 2. Simulate Bridge command_result message for 'close terminal'
console.log('\n--- Test: BridgeClient receives app.close for terminal ---');
window.BridgeClient.handleMessage({
    type: 'command_result',
    success: true,
    data: {
        status: 'completed',
        action: { action: 'app.close', target: 'terminal' },
        message: 'Closed Terminal'
    }
});

assert(!window.WindowManager.windows.has('terminal'), 'Terminal removed from WindowManager.windows Map');
assert(!mockWindowContainer.children.some(c => c.id === 'win-terminal'), 'win-terminal removed from DOM');

// Verify the other 5 apps remain open!
const remainingAfterTerminal = ['files', 'editor', 'settings', 'workspace', 'nova-voice'];
remainingAfterTerminal.forEach((appId) => {
    assert(window.WindowManager.windows.has(appId), `Unrelated app '${appId}' remains open in WindowManager`);
    assert(mockWindowContainer.children.some(c => c.id === `win-${appId}`), `Unrelated window 'win-${appId}' remains in DOM`);
});
assert(window.WindowManager.windows.size === 5, 'Exactly 5 windows remain open');

// 3. Simulate Bridge command_result message for 'close files'
console.log('\n--- Test: BridgeClient receives app.close for files ---');
window.BridgeClient.handleMessage({
    type: 'command_result',
    success: true,
    data: {
        status: 'completed',
        action: { action: 'app.close', target: 'files' },
        message: 'Closed Files'
    }
});

assert(!window.WindowManager.windows.has('files'), 'Files removed from WindowManager.windows Map');
assert(!mockWindowContainer.children.some(c => c.id === 'win-files'), 'win-files removed from DOM');

// 4. Simulate Bridge command_result message for 'close editor'
console.log('\n--- Test: BridgeClient receives app.close for editor ---');
window.BridgeClient.handleMessage({
    type: 'command_result',
    success: true,
    data: {
        status: 'completed',
        action: { action: 'app.close', target: 'editor' },
        message: 'Closed Text Editor'
    }
});

assert(!window.WindowManager.windows.has('editor'), 'Editor removed from WindowManager.windows Map');
assert(!mockWindowContainer.children.some(c => c.id === 'win-editor'), 'win-editor removed from DOM');

// 5. Simulate Bridge command_result message for 'close settings'
console.log('\n--- Test: BridgeClient receives app.close for settings ---');
window.BridgeClient.handleMessage({
    type: 'command_result',
    success: true,
    data: {
        status: 'completed',
        action: { action: 'app.close', target: 'settings' },
        message: 'Closed Settings'
    }
});

assert(!window.WindowManager.windows.has('settings'), 'Settings removed from WindowManager.windows Map');
assert(!mockWindowContainer.children.some(c => c.id === 'win-settings'), 'win-settings removed from DOM');

// 6. Simulate Bridge command_result message for 'close workspace'
console.log('\n--- Test: BridgeClient receives app.close for workspace ---');
window.BridgeClient.handleMessage({
    type: 'command_result',
    success: true,
    data: {
        status: 'completed',
        action: { action: 'app.close', target: 'workspace' },
        message: 'Closed Workspace'
    }
});

assert(!window.WindowManager.windows.has('workspace'), 'Workspace removed from WindowManager.windows Map');
assert(!mockWindowContainer.children.some(c => c.id === 'win-workspace'), 'win-workspace removed from DOM');

// Nova voice should still be open
assert(window.WindowManager.windows.has('nova-voice'), 'nova-voice remains open alone');
assert(mockWindowContainer.children.some(c => c.id === 'win-nova-voice'), 'win-nova-voice remains in DOM');

// 7. Simulate Bridge command_result message for 'close nova voice'
console.log('\n--- Test: BridgeClient receives app.close for nova-voice ---');
speechStopCalled = false;
window.BridgeClient.handleMessage({
    type: 'command_result',
    success: true,
    data: {
        status: 'completed',
        action: { action: 'app.close', target: 'nova-voice' },
        message: 'Closed Nova Voice'
    }
});

assert(!window.WindowManager.windows.has('nova-voice'), 'nova-voice removed from WindowManager.windows Map');
assert(!mockWindowContainer.children.some(c => c.id === 'win-nova-voice'), 'win-nova-voice removed from DOM');
assert(speechStopCalled === true, 'SpeechService.stop() was called when closing nova-voice');
assert(window.WindowManager.windows.size === 0, 'All windows are now closed');
assert(mockWindowContainer.children.length === 0, 'DOM container is empty');

// 8. Re-opening works after close
console.log('\n--- Test: Re-opening works after close ---');
window.WindowManager.openApp('terminal');
assert(window.WindowManager.windows.has('terminal'), 'Terminal re-opened cleanly');
assert(mockWindowContainer.children.some(c => c.id === 'win-terminal'), 'win-terminal re-added to DOM');

if (failures > 0) {
    console.error(`\nFAILED: ${failures} assertions failed.`);
    process.exit(1);
} else {
    console.log('\nALL 27 INTEGRATION ASSERTIONS PASSED!');
    process.exit(0);
}
