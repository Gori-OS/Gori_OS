const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Test Config.js in various simulated environments
function runConfigTest(mockLocation, mockStorage, testFn) {
    global.window = {
        location: mockLocation,
        document: {
            readyState: 'complete',
            getElementById: () => null,
            addEventListener: () => {}
        }
    };
    global.localStorage = mockStorage || { getItem: () => null, setItem: () => {} };
    global.document = global.window.document;

    const configCode = fs.readFileSync(path.join(__dirname, '../js/config.js'), 'utf8');
    eval(configCode);
    testFn(global.window);
}

console.log('--- Testing Frontend config.js ---');

// Case 1: Localhost
runConfigTest({ hostname: 'localhost', port: '7890', protocol: 'http:', search: '' }, null, (win) => {
    assert.strictEqual(win.IS_LOCAL_ENV, true, 'localhost must be detected as local');
    assert.strictEqual(win.apiUrl('/token'), '/token', 'local apiUrl must return relative path');
    assert.strictEqual(win.wsUrl(0), 'ws://localhost:7891/ws', 'local wsUrl(0) must alternate to port 7891');
    assert.strictEqual(win.wsUrl(1), 'ws://localhost:7890/ws', 'local wsUrl(1) must alternate to port 7890');
    console.log('[PASS] Localhost detection and port alternation');
});

// Case 2: LAN IP
runConfigTest({ hostname: '192.168.1.55', port: '7890', protocol: 'http:', search: '' }, null, (win) => {
    assert.strictEqual(win.IS_LOCAL_ENV, true, '192.168.x.x must be detected as local');
    assert.strictEqual(win.apiUrl('/files'), '/files', 'LAN apiUrl must return relative path');
    console.log('[PASS] Private LAN IP detection');
});

// Case 3: Vercel deployment
runConfigTest({ hostname: 'gorios-frontend.vercel.app', port: '', protocol: 'https:', search: '' }, null, (win) => {
    assert.strictEqual(win.IS_LOCAL_ENV, false, 'Vercel must be detected as non-local');
    assert.strictEqual(win.apiUrl('/token'), 'https://gori-os.onrender.com/token', 'Vercel apiUrl must point to Render backend');
    assert.strictEqual(win.apiUrl('/upload/file'), 'https://gori-os.onrender.com/upload/file');
    assert.strictEqual(win.wsUrl(), 'wss://gori-os.onrender.com/ws', 'Vercel wsUrl must be single wss URL');
    console.log('[PASS] Vercel environment detection and Render URL mapping');
});

// Case 4: Query parameter override
runConfigTest({ hostname: 'gorios-frontend.vercel.app', port: '', protocol: 'https:', search: '?api=https://custom-backend.example.com' }, null, (win) => {
    assert.strictEqual(win.apiUrl('/files'), 'https://custom-backend.example.com/files', 'Query override ?api must override backend URL');
    assert.strictEqual(win.wsUrl(), 'wss://custom-backend.example.com/ws', 'wsUrl must follow custom override');
    console.log('[PASS] Query param ?api override');
});

// Case 5: External URLs must be untouched
runConfigTest({ hostname: 'gorios-frontend.vercel.app', port: '', protocol: 'https:', search: '' }, null, (win) => {
    assert.strictEqual(win.apiUrl('https://www.google.com'), 'https://www.google.com', 'External URLs must stay untouched');
    assert.strictEqual(win.apiUrl('wss://streaming.assemblyai.com/v2'), 'wss://streaming.assemblyai.com/v2', 'External streaming URLs must stay untouched');
    console.log('[PASS] External URLs left untouched');
});

console.log('========================================');
console.log('ALL CONFIG.JS ASSERTIONS PASSED!');
console.log('========================================');
