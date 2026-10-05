const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function fixture(options = {}) {
  const listeners = new Map();
  const attributes = new Map();
  const styles = new Map();
  const input = {value: '你好', disabled: false, closest: value => value === '#luyao-message' ? {} : null};
  const send = {disabled: false, clicks: 0, click() {this.clicks += 1;}, setAttribute: (key, value) => attributes.set(key, value)};
  const stop = {setAttribute() {}, getClientRects: () => []};
  const voice = {disabled:false, checked:true, changes:0, dispatchEvent() {this.changes += 1;}};
  const badge = {getAttribute: key => key === 'data-voice-ready' && options.voiceReady != null ? String(options.voiceReady) : null};
  const document = {
    documentElement: {style: {getPropertyValue: key => styles.get(key), setProperty: (key, value) => styles.set(key, value)}},
    querySelector: value => ({'#luyao-message textarea':input, '#luyao-send':send, '#luyao-stop':stop, '#luyao-voice-toggle input':voice, '.connection-badge':badge}[value] || null),
    addEventListener: (name, fn) => listeners.set(name, fn),
  };
  const window = {innerHeight: 900, addEventListener() {}, visualViewport: null};
  const sandbox = {window, document, requestAnimationFrame: fn => fn(), MutationObserver: class {observe() {}}, WeakSet, Event:class {}};
  const source = fs.readFileSync(path.join(__dirname, '..', 'assets', 'ui', 'luyao.js'), 'utf8');
  vm.runInNewContext(`(${source})()`, sandbox);
  function key(overrides = {}) {
    const event = {target:input, key:'Enter', keyCode:13, isComposing:false, repeat:false, shiftKey:false, altKey:false,
      prevented:false, stopped:false,
      preventDefault() {this.prevented = true;}, stopImmediatePropagation() {this.stopped = true;}, ...overrides};
    listeners.get('keydown')(event);
    return event;
  }
  return {input, send, key, listeners, window, styles, voice};
}

test('Enter submits once and prevents Gradio from also processing it', () => {
  const f = fixture();
  const event = f.key();
  assert.equal(f.send.clicks, 1);
  assert.equal(event.prevented, true);
  assert.equal(event.stopped, true);
});

test('Shift+Enter allows the native newline without Gradio submitting', () => {
  const f = fixture();
  const event = f.key({shiftKey:true});
  assert.equal(f.send.clicks, 0);
  assert.equal(event.prevented, false);
  assert.equal(event.stopped, true);
});

test('Enter keypress and keyup never reach a second Gradio submit listener', () => {
  const f = fixture();
  for (const name of ['keypress', 'keyup']) {
    const event = {target:f.input, key:'Enter', stopped:false, stopImmediatePropagation() {this.stopped = true;}};
    f.listeners.get(name)(event);
    assert.equal(event.stopped, true);
  }
  assert.equal(f.send.clicks, 0);
});

test('IME candidate confirmation does not submit or block native composition', () => {
  for (const overrides of [{isComposing:true}, {keyCode:229}]) {
    const f = fixture();
    const event = f.key(overrides);
    assert.equal(f.send.clicks, 0);
    assert.equal(event.prevented, false);
    assert.equal(event.stopped, true);
  }
});

test('composition lifecycle protects candidate selection and then restores Enter', () => {
  const f = fixture();
  f.listeners.get('compositionstart')({target:f.input});
  f.key();
  assert.equal(f.send.clicks, 0);
  f.listeners.get('compositionend')({target:f.input});
  f.key();
  assert.equal(f.send.clicks, 1);
});

test('held Enter, empty input, and disabled input do not submit', () => {
  for (const state of ['repeat', 'empty', 'disabled']) {
    const f = fixture();
    if (state === 'empty') f.input.value = '  \n ';
    if (state === 'disabled') f.input.disabled = true;
    f.key({repeat:state === 'repeat'});
    assert.equal(f.send.clicks, 0);
  }
});

test('viewport height is exported for the responsive shell', () => {
  const f = fixture();
  assert.equal(f.styles.get('--luyao-viewport-height'), '900px');
});

test('unavailable voice is disabled, unchecked, and synchronized once', () => {
  const f = fixture({voiceReady:false});
  assert.equal(f.voice.disabled, true);
  assert.equal(f.voice.checked, false);
  assert.equal(f.voice.changes, 1);
  f.window.__luyaoUi.sync();
  assert.equal(f.voice.changes, 1);
});

test('known-ready and unknown voice preserve the current selection', () => {
  for (const options of [{voiceReady:true}, {}]) {
    const f = fixture(options);
    assert.equal(f.voice.disabled, false);
    assert.equal(f.voice.checked, true);
    assert.equal(f.voice.changes, 0);
  }
});
