# Luyao UI Interaction Update

## Goal

Make the existing Chinese Gradio chat interface work as a compact, predictable chat tool. Keep the portrait, green/white identity, existing public-domain entry, server-only credentials, and actual backend behavior.

## Acceptance

- Enter submits once; Shift+Enter inserts a newline; composition/candidate confirmation does not submit.
- Empty or duplicate submissions do not create extra turns.
- Missing chat configuration or an unreachable backend keeps the draft and conversation intact, with an accurate status instead of a simulated assistant reply.
- Busy controls expose a stop action; cancelling returns controls to idle and keeps coherent conversation history.
- New chat resets conversation and playback without changing another session's state.
- Text chat can work when voice is unavailable; unavailable voice is not selectable.
- Desktop, 390px mobile, and shortened mobile viewports keep the input and controls visible without horizontal overflow.

## Scope And Style

Implementation lives in `ui.py`, `assets/ui/luyao.css`, and a small `assets/ui/luyao.js`. Retain stable component IDs; add `luyao-stop` and `luyao-submit-controls`. Use the existing portrait and Lucide icons. Keep a full-height unframed shell, restrained typography, accessible focus states, and stable control dimensions. Status copy describes actual state; do not add shortcut instructions or marketing copy to the screen.

## Verification Commands

Python: `.venv/bin/python -m unittest discover -s tests -v`

Keyboard policy: `node --test tests/ui_interactions.test.cjs`

Use a local-only deterministic test backend and a separate UI port for browser checks. Exercise Enter, Shift+Enter, stop/reset, service-unconfigured, and unavailable-network states. Save screenshots and check loaded assets, console errors, and desktop/mobile geometry. The test backend is never part of the production Docker image.

## Boundaries

Do not configure an unknown API Key, call paid APIs during testing, alter auth/public-mode settings, change persona or memory logic, overwrite existing user history, or modify unrelated Hexo posts and diaries. Publish reviewed source changes, retain server configuration/data volumes, and verify the deployed main-domain iframe after updating the Docker image.

## Completed Local Checks

- Native Enter submitted one Chinese-text test; Shift+Enter inserted a newline without a second submission.
- Unconfigured service preserved the draft and made zero chat/voice requests.
- Stop restored an unanswered draft and closed the nested generator; completed raw model text and prior emotion tags remained intact.
- A delayed health refresh concurrent with New chat did not resurrect old history; the next request had an empty history.
- Desktop 1440x900, mobile 390x844, and short mobile 390x460 kept controls visible without horizontal overflow.
- IME composition and key-code 229 are covered by Node policy tests; a physical IME candidate-selection session and real paid-provider replies were not tested.
