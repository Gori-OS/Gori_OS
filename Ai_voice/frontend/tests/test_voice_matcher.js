/**
 * Unit tests for Nova Voice Confirmation & Normalisation Matcher.
 * Tests cases A, B, and C including mid-sentence and substring safety.
 * Can be run via: node Ai_voice/frontend/tests/test_voice_matcher.js
 */

const CONFIRM_PHRASES = [
    'ok', 'okay', 'okk', 'okey',
    'ok do it', 'okay do it', 'ok execute it', 'ok please',
    'yes ok', 'yes okay',
    'ओके', 'ठीक है', 'ओके कर दो', 'ठीक है कर दो', 'ok kar do'
];

function normaliseVoiceText(text) {
    if (!text) return '';
    return text
        .toLowerCase()
        .replace(/[.,!?;:]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function buildConfirmationRegex(phrases) {
    const sorted = [...phrases].sort((a, b) => b.length - a.length);
    const escaped = sorted.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    return new RegExp(`(?:^|\\s)(${escaped.join('|')})$`, 'i');
}

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

// Assert helper
let failures = 0;
function assertEqual(label, actual, expected) {
    const actStr = JSON.stringify(actual);
    const expStr = JSON.stringify(expected);
    if (actStr === expStr) {
        console.log(`[PASS] ${label}`);
    } else {
        console.error(`[FAIL] ${label}\n  Expected: ${expStr}\n  Actual:   ${actStr}`);
        failures++;
    }
}

console.log('--- Running Nova Voice Matcher Unit Tests ---');

// Case 1: Say "open terminal", pause, then say "ok".
const step1 = parseVoiceTurn('open terminal');
assertEqual('Case 1: Step 1 (task)', step1, { type: 'C', task: 'open terminal', confirm: '' });

const step2 = parseVoiceTurn('ok');
assertEqual('Case 1: Step 2 (confirmation alone)', step2, { type: 'A', task: '', confirm: 'ok' });

// Case 2: Say "open terminal okay" in one breath.
const oneBreath = parseVoiceTurn('open the terminal okay');
assertEqual('Case 2: One breath task + confirmation', oneBreath, { type: 'B', task: 'open the terminal', confirm: 'okay' });

// Case 3: Say "open terminal" and do not say ok.
const noConfirm = parseVoiceTurn('open terminal');
assertEqual('Case 3: Task alone without confirm', noConfirm, { type: 'C', task: 'open terminal', confirm: '' });

// Case 4: Say "ok" alone with an empty input.
const bareOk = parseVoiceTurn('ok.');
assertEqual('Case 4: Bare ok alone with punctuation', bareOk, { type: 'A', task: '', confirm: 'ok' });

// Case 5: Say "I want to book a flight okay". Substrings ("book") must not trigger.
const bookFlight = parseVoiceTurn('I want to book a flight okay');
assertEqual('Case 5: "book" substring in sentence does not falsely trigger, only trailing "okay"', bookFlight, {
    type: 'B',
    task: 'i want to book a flight',
    confirm: 'okay'
});

// Additional edge cases:
// Mid-sentence "ok" does not trigger
const midSentenceOk = parseVoiceTurn('open ok terminal');
assertEqual('Mid-sentence "ok" does not trigger confirmation', midSentenceOk, {
    type: 'C',
    task: 'open ok terminal',
    confirm: ''
});

// Substring "book" alone does not trigger
const bookAlone = parseVoiceTurn('book');
assertEqual('"book" alone does not trigger', bookAlone, { type: 'C', task: 'book', confirm: '' });

// Substring "token" alone does not trigger
const tokenAlone = parseVoiceTurn('token');
assertEqual('"token" alone does not trigger', tokenAlone, { type: 'C', task: 'token', confirm: '' });

// Multi-word phrase: "ok please"
const multiWordConfirm = parseVoiceTurn('open terminal ok please');
assertEqual('Multi-word confirm phrase "ok please"', multiWordConfirm, {
    type: 'B',
    task: 'open terminal',
    confirm: 'ok please'
});

// Hindi phrase: "ठीक है" alone
const hindiAlone = parseVoiceTurn('ठीक है');
assertEqual('Hindi confirmation alone', hindiAlone, { type: 'A', task: '', confirm: 'ठीक है' });

// Hindi phrase with task: "terminal kholo ok kar do"
const hindiTask = parseVoiceTurn('terminal kholo ok kar do');
assertEqual('Hindi task with "ok kar do"', hindiTask, {
    type: 'B',
    task: 'terminal kholo',
    confirm: 'ok kar do'
});

if (failures > 0) {
    console.error(`\nFAILED: ${failures} test(s) failed.`);
    process.exit(1);
} else {
    console.log('\nALL TESTS PASSED!');
    process.exit(0);
}
