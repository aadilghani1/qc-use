# AGENTS.md

qc-use runs a plain-language test file in a private Chrome. Jev chooses every action from **observed** elements, and code does the action. A step passes only on **evidence**: checks on a fresh read of the page after the step.

Use the words in [CONTEXT.md](CONTEXT.md) in code, messages, and docs. Add a new word there before you use it.

Before you edit anything in `qc_use/engine/`, read [qc_use/engine/AGENTS.md](qc_use/engine/AGENTS.md).

## Done means

A change is done when all four checks pass:

```bash
uv run ruff check .
uv run pytest
node --check qc_use/engine/snapshot.js
uv build
```

And:

- Each behavior change has an offline test that fails without the change.
- Each doc in the [docs table](#docs) that the change touches is updated.
- A change to `runner.py`, `guards.py`, `judge.py`, or `engine/` also passes the live demo: `uv run --env-file .env qc-use demo --headless` exits 0. It needs `AI_GATEWAY_API_KEY` in `.env` and costs less than $0.001. If you cannot run it, say so in your summary.

## Code map

| Module | Job |
| --- | --- |
| `cli.py` | Commands. Parses arguments, prints, and returns exit codes. |
| `spec.py` | Reads a test file into a `TestSpec`. |
| `runner.py` | Runs one test: Chrome, steps, checks, screenshots, and report files. |
| `judge.py` | Jev questions outside the action loop: expectations, the gate, dialogs, diagnosis, and ratings. |
| `guards.py` | The `Policy` hooks: allowed sites, production URLs, the gate, and dialog decisions. |
| `secrets.py` | Resolves secrets and holds the `Redactor`. |
| `report.py` | The report models, exit codes, and `report.md`. |
| `chrome.py` | Starts Chrome with a private profile. |
| `watch.py`, `watch.html` | The read-only live view for `--watch`. |
| `doctor.py`, `scaffold.py`, `skill.py`, `demo/` | The `doctor`, `init`, `skill`, and `demo` commands. |
| `engine/` | Reads a page, asks Jev for one decision, and does one action. |

The QA layer (`qc_use/*.py`) imports the engine. The engine imports nothing from the QA layer.

## Invariants

These are hard guardrails. Each one has a test. Keep the test green.

1. **Jev chooses, code acts.** Every action targets an observed element by its code-owned node id. Model output never becomes a selector, a coordinate, a URL, or code.
2. **Record, then read.** Append each action to the history before the next page read.
3. **One action runs once.** When an action is uncertain, stop the step with `Blocked` or `StalePage` and report it.
4. **Secret values stay local.** Every model request goes through `model.post_json`, the redaction choke point. Every file write goes through the `Redactor`. Every saved screenshot goes through `runner.masked`.
5. **Evidence decides.** Fresh-page checks decide the outcome of a step. Jev's DONE only ends the step.
6. **Tests run offline.** Mock `post_json`, the `judge` functions, or the browser. `tests/conftest.py` fails any test that reaches a real model API.

## Patterns

**Pydantic at the boundary.** Validate data where it enters or leaves qc-use: the test file (`TestSpec`), Jev answers (`ChoiceAnswer`, `NoulAnswer`, `ScoreAnswer`), text helper output (`TextValue`), and the report (`Report`). Inside the action loop, pass plain dicts. Wrap a `ValidationError` in a domain error with a plain message: `SpecError` names the file and the field, and a bad Jev answer raises `ValueError("Invalid TypeSafe response; no action executed.")`.

**Typed questions, one request.** Every Jev question is a `choice`, a `noul`, or a `score`, and its answer is validated before use. When a decision needs one more answer, add a question to the same request (fan-out) before you add a round trip. A new question outside the action loop goes in `judge.py` as one function: build the questions, call `ask()`, validate, and return plain values.

**Exceptions say why a step stopped.**

| Raise | When |
| --- | --- |
| `StalePage` | The page changed since the decision. The agent reads the page again and asks again. |
| `Blocked` | The step cannot continue. The message becomes the reason in the report. |
| `NeedsApproval` | An action can break a never-do rule. |
| `BudgetExceeded` | The run reached `max_cost`. |
| `SpecError` | The test file is invalid. Name the file and the field. |
| `SetupError` | Nothing ran: the URL, a secret, or a key is not ready. |

Library code raises. `cli.py` turns errors into exit codes with `report.EXIT_CODES` and `SETUP_ERROR`. Only the command modules (`cli.py`, `doctor.py`, `demo/`) print. Other modules return values or take an `echo` callback.

**One place for each setting.** Environment variables resolve in one function each: `model.jev_endpoint()`, `model.text_settings()`, `model.text_key()`, and `chrome.find_chrome()`. A new qc-use variable starts with `QC_USE_`. A setting that belongs to a test goes in `TestSpec` with a default.

**Lazy browser import.** `browser_harness` reads `BU_NAME` when Python imports it. Import `engine.browser` only inside `runner.run`, after `connect()`. Modules that load before a run (`guards`, `judge`, `spec`, `report`, `secrets`) import `engine.errors`, `engine.agent`, or `engine.model`, which do not load the browser.

**Plain messages.** An error or log message says what happened. Then it says what to do next, or what did not happen: "Text helper returned no valid field value; nothing typed." Name the file, the field, or the secret.

**Numbers from the trace.** Counts, times, and costs in a report come from the history, the decisions, and the `Meter`, never from model text.

## Style

- Match the code around you: small functions, flat control flow, one job per module. When a module passes about 400 lines, split it by job.
- Give each module and each public function a one-line docstring that says its job or the reason for it.
- Write one-line comments that say why. The code says what.
- Types live in the pydantic models. Helpers stay plain, like the engine.
- Use names from `CONTEXT.md`: step, expectation, exact check, secret, gate, signal, outcome.
- ruff (`E`, `F`, `I`) at 120 columns, `pathlib` for paths, f-strings for text.
- Add a dependency only when the standard library and the current dependencies cannot do the job, and say why in the pull request. The current dependencies are `browser-harness` (pinned), `httpx`, `pydantic`, `pyyaml`, and `pillow`.
- `watch.html` is one file with no build step. Escape every dynamic value with `esc()`.

## Tests

- `tests/test_engine.py` covers engine contracts. `tests/test_qa.py` covers test files, guards, secrets, outcomes, and reports.
- Name a test after the behavior it proves: `test_password_fields_accept_only_declared_secrets`.
- Build inputs with the helpers in the file: `page()`, `login_page()`, `make_agent()`, `write()`, and `spec_for()`. Use `pytest.mark.parametrize` for cases.
- Assert what a user or a report sees: the outcome, the reason, the exit code, and what was sent. For a safety invariant, prove that the forbidden call did not happen with `assert_not_called()`.

## Docs

Write docs in ASD-STE100 simple English: sentences of 25 words or fewer, active voice, one word for each idea (from `CONTEXT.md`), and no em-dashes.

Update each doc that your change touches:

| Change | Update |
| --- | --- |
| A new word | `CONTEXT.md` first |
| A test-file setting | `spec.py`, `docs/test-files.md`, and `qc_use/SKILL.md` if agents should use it |
| A command or a flag | `cli.py`, README "Run a test", and `install.md` if setup changes |
| An outcome or an exit code | `report.py`, `CONTEXT.md`, README, and `qc_use/SKILL.md` |
| Safety behavior | `docs/safety.md` and README "Safety" |
| Engine behavior | `docs/how-it-works.md` |
| An adapted upstream file | `NOTICE` |

A number in a doc (time, cost, or pass rate) comes from a run that you did. Say which run.

## Git

Commit only when the user asks. Write the subject in the imperative, in 72 characters or fewer. In the body, list what changed and how you checked it. Keep `.env`, `qa/.env`, and `qa-results/` out of git.
