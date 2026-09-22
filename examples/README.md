# Example test files

Copy a file to your app's `qa/` folder and change the URL, the steps, and the expectations.

| File | Flow |
| --- | --- |
| [login.md](login.md) | An existing account signs in with separate credential steps. |
| [observation.md](observation.md) | Exact read-only checks without browser input. |
| [authenticated.md](authenticated.md) | Continue after manual OTP or OAuth sign-in. |
| [signup.md](signup.md) | A new user creates an account and reaches the first screen. |
| [settings.md](settings.md) | A user changes a setting, and the change is still there after a reload. |

The demo app tests are also good examples: [qc_use/demo/tests](../qc_use/demo/tests).

Run `qc-use validate qa/*.md` before starting a run. These examples require your app’s routes, labels, and test fixtures.
