# Words we use

This file defines the words in qc-use. The code, the docs, and the reports use these words with these meanings only.

| Word | Meaning |
| --- | --- |
| **qc-use** | This tool. It runs a critical path in a browser and tells you if each step works. |
| **Critical path** | The most important journey a user takes in your app. For example: sign in, finish onboarding, see the first result. |
| **Test file** | A Markdown file that describes one critical path. It has settings at the top and numbered steps below. |
| **Step** | One numbered line in a test file. It says what to do. |
| **Expectation** | An `expect:` line under a step. It says what the page must show when the step works. Jev checks it. |
| **Exact check** | A `check:` line under a step. Code checks it exactly, for example `url contains /dashboard`. |
| **Jev** | A model from TypeSafe. It chooses one option from a list and gives a probability for each option. It does not write text. |
| **Text helper** | A small language model that writes text for a text field, such as a name or a company. It never sees secrets. |
| **Secret** | A private value, such as a password. A test file contains the secret's name only. qc-use types the value. No model sees it. |
| **Persona** | The user that qc-use acts as. It is a list of facts, such as a role or a team size. |
| **Never-do rule** | Something qc-use must not do without a person's approval, such as "delete stored data". |
| **Gate** | The question that qc-use asks Jev before each chosen input action: "Can this action break a never-do rule?" |
| **Signal** | A problem that the browser reports: a console error, a JavaScript exception, or a failed request. |
| **Rating** | Jev's score for the whole run on levels that you choose, for example from "confusing" to "effortless". |
| **Live view** | The read-only local page that shows a run, its actions, and masked images. |
| **Provider** | The service that receives a model request and returns an answer. |
| **Run** | One time that qc-use runs a test file. Each run uses a new, empty Chrome profile. |
| **Report** | The result of a run: `report.md` for people and `report.json` for programs. |
| **Skill** | The `SKILL.md` instructions that teach a coding agent to write, run, and explain qc-use tests. `qc-use skill install`, the Claude Code plugin, and `npx skills` install the same file. |
| **Outcome** | The result of a step or a run: pass, fail, inconclusive, blocked, or needs approval. |

## Outcomes

| Outcome | Meaning |
| --- | --- |
| **pass** | The step is done, and every expectation and exact check is true. |
| **fail** | An expectation or exact check is false, or a signal from `fail_on` occurred. The app probably has a bug. |
| **inconclusive** | Jev is not sure if an expectation is true. qc-use never counts this as a pass. |
| **blocked** | qc-use cannot continue. The report says why, for example "the page opened a new tab". |
| **needs approval** | The next action can break a never-do rule. A person must allow it. |

## Evidence and run setup

- **Observation step**: a read-only step that checks the page without input.
- **Action evidence**: recorded input checked against an explicit `action:` requirement.
- **Document text**: rendered text across the document, including text outside the viewport, with a size limit.
- **Verification timeout**: the polling window for rereading a step's result. In-flight checks can finish later. Input never repeats.
- **Rating issue**: a saved reason that a rating is unavailable.
- **Coverage**: completed steps compared with all planned steps.
- **Manual authentication**: the user signs in inside a dedicated test profile before the automated steps start.
- **Secret template**: an explicitly declared secret whose `{tag}` placeholder expands once for each run.

- **Provider unavailable**: transient model failures exhausted the retry deadline. The run stops without more model requests.
- **Preflight**: a small, validated Jev question before Chrome starts. It checks current availability, not future availability.
- **Retry deadline**: the total time allowed for one model request, including attempts and waits.

- **Validation**: offline checks of a test file. Validation does not run the browser or require credentials.
- **Saved view**: the local inspector showing an existing report and its saved step images.
- **Back**: navigation to the previous observed browser-history entry.
- **Reload**: loading the current page again through Chrome.
- **Uncertain action**: input that an error stopped after it may have run. qc-use records it once and never repeats it.

- **Base URL**: another origin for a test's start URL, such as a preview deployment. The path of the start URL stays the same.
- **CI summary**: the Markdown table and the JUnit XML that one `qc-use run` command writes for CI. They contain no secret values.
- **Command result**: a versioned JSON response containing every report, setup error, and the command exit code.
