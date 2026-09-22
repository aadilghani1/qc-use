# Engine rules

The engine reads a page, asks Jev for one decision, and does one action. It is adapted from [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) (see `NOTICE`). Keep its structure close to upstream, so upstream fixes stay easy to port.

The root [AGENTS.md](../../AGENTS.md) applies here too.

## One decision

Each decision takes these steps, in this order:

1. `snapshot.js` reads the page in one evaluation: visible text, controls, and freshness guards.
2. `model.action_space` gives each observed element one index and builds one target head for each operation.
3. `model.choose` sends one request with the operation question, every target head, and `step_done` (fan-out). It validates the operation, then only the head of the chosen operation.
4. `Agent.act` consumes the decision before any mutation, then calls `Policy.before_act`, then `Browser.act`.
5. `Browser.act` checks freshness again right before input.
6. `Agent.act` records the action in the history, then reads the page again.

## Add an action kind

Change these places in order, and add a test at each place:

1. `snapshot.js`: emit the action with its `kind` and `node`.
2. `model.action_space`: map the kind to an operation and build its targets. Describe each target in `describe()`.
3. `model.choose`: add the operation label.
4. `Agent.act`: supply the value to send. It comes from code (a secret, a declared file, or the text helper output), never from Jev.
5. `browser.browser_operation`: add the executor. Resolve the node by its id, and check that it is connected and enabled.
6. `Browser.fresh`: choose the freshness rule for the kind.
7. `docs/how-it-works.md`: describe the new action.

## snapshot.js

- It is one expression that returns the whole state. It only reads the page.
- A value that must stay in the page goes through `shown()`. A password field reports only `[filled]`.
- A new field that must invalidate old decisions goes into `marker` or `guards`.
- Keep the caps: 6,000 characters of text and 250 actions.
- Check it with `node --check qc_use/engine/snapshot.js`.

## browser.py

- It is the only engine module that imports `browser_harness`.
- All input goes through `Browser.input()`. A native dialog blocks the CDP call, and `input()` decides the dialog on the main thread.
- A dropdown choice that may have fired its change event raises `RuntimeError`, not `StalePage`, so that nothing repeats it.

## model.py and questions.py

- Every model request goes through `post_json`. It redacts secrets and meters cost.
- Provider defaults live in `jev_endpoint()` and `text_settings()`.
- Each Jev answer passes `validate_choice` or a pydantic answer model before use.
- The text in `questions.py` is the policy. After you change it, run `uv run --env-file .env qc-use run qc_use/demo/tests/onboarding.md --repeat 3 --headless` and report the pass rate.
