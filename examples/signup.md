---
url: http://localhost:3000/signup
secrets: [SIGNUP_EMAIL, SIGNUP_PASSWORD]
---
# Create a test account

Use a new, disposable local test account. Adapt labels and expected routes to your app.
Set both secrets locally. This test creates account data and is not safe to repeat without resetting that data.
For email verification, complete manual authentication and use authenticated.md instead.

1. Enter SIGNUP_EMAIL in the email field
   - action: Enter SIGNUP_EMAIL in the email field
   - expect: the email field holds the SIGNUP_EMAIL secret
2. Enter SIGNUP_PASSWORD in the password field
   - action: Enter SIGNUP_PASSWORD in the password field
   - expect: the password field is filled
3. Create the account
   - action: Click Create account
   - check: url contains /onboarding
