() => {
  if (window.__luyaoUi) {
    window.__luyaoUi.sync();
    return;
  }
  const composing = new WeakSet();
  const field = () => document.querySelector('#luyao-message textarea');
  const isMessage = target => Boolean(target?.closest?.('#luyao-message'));
  const titles = {'#luyao-send':'发送消息', '#luyao-stop':'停止回复', '#luyao-refresh':'刷新状态', '#luyao-new-chat':'新对话'};
  let inputWasDisabled = false;
  let voiceAvailable = null;
  function sync() {
    const input = field();
    const send = document.querySelector('#luyao-send');
    const stop = document.querySelector('#luyao-stop');
    const busy = Boolean(stop?.getClientRects().length);
    const badge = document.querySelector('.connection-badge');
    const capability = badge?.getAttribute('data-voice-ready');
    if (capability != null) voiceAvailable = capability === 'true';
    const voice = document.querySelector('#luyao-voice-toggle input');
    if (voice) {
      const disabled = busy || voiceAvailable === false;
      if (voice.disabled !== disabled) voice.disabled = disabled;
      if (voiceAvailable === false && voice.checked) {
        voice.checked = false;
        voice.dispatchEvent(new Event('change', {bubbles:true}));
      }
    }
    if (input && send) {
      const disabled = input.disabled || busy || !input.value.trim();
      if (send.disabled !== disabled) send.disabled = disabled;
      if (inputWasDisabled && !input.disabled && window.matchMedia?.('(pointer:fine)').matches && document.activeElement === document.body) input.focus({preventScroll:true});
      inputWasDisabled = input.disabled;
      input.setAttribute?.('enterkeyhint', 'send');
    }
    for (const [selector, title] of Object.entries(titles)) {
      const button = document.querySelector(selector);
      if (button) {
        button.setAttribute('title', title);
        button.setAttribute('aria-label', title);
      }
    }
    const height = `${Math.round(window.visualViewport?.height || window.innerHeight)}px`;
    const style = document.documentElement.style;
    if (style.getPropertyValue('--luyao-viewport-height') !== height) style.setProperty('--luyao-viewport-height', height);
  }
  window.__luyaoUi = {sync};
  document.addEventListener('compositionstart', event => {
    if (isMessage(event.target)) composing.add(event.target);
  }, true);
  document.addEventListener('compositionend', event => {
    composing.delete(event.target);
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || !isMessage(event.target)) return;
    event.stopImmediatePropagation();
    if (event.isComposing || event.keyCode === 229 || composing.has(event.target) || event.shiftKey || event.altKey) return;
    event.preventDefault();
    sync();
    const input = field();
    const send = document.querySelector('#luyao-send');
    if (event.repeat || !input?.value.trim() || input.disabled || !send || send.disabled) return;
    send.click();
  }, true);
  // Gradio also handles Enter in keypress; keep native newlines but suppress its submit handlers.
  for (const name of ['keypress', 'keyup']) {
    document.addEventListener(name, event => {
      if (event.key === 'Enter' && isMessage(event.target)) event.stopImmediatePropagation();
    }, true);
  }
  document.addEventListener('input', sync, true);
  let scheduled = false;
  const schedule = () => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {scheduled = false; sync();});
  };
  new MutationObserver(schedule).observe(document.documentElement, {
    childList:true, subtree:true, characterData:true, attributes:true,
    attributeFilter:['disabled', 'hidden', 'style', 'class'],
  });
  window.addEventListener('resize', schedule);
  window.visualViewport?.addEventListener('resize', schedule);
  sync();
}
