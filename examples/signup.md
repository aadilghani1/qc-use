---
url: http://localhost:3000/signup
secrets: [SIGNUP_PASSWORD]
persona:
  name: Sam Okafor
  role: Founder
  company: QA Test Co
  team_size: 1-10
rate:
  signup_ease: [confusing, effortful, okay, smooth, effortless]
---
# Sign up

A founder creates a new account. The text helper writes a fake test email address, and the report lists it.
Password fields accept secrets only, so the password comes from SIGNUP_PASSWORD.

1. Create an account as the persona with a test email address and SIGNUP_PASSWORD
   - expect: the app shows a welcome or onboarding screen
2. Finish the first screen as the persona
   - expect: the main screen of the app is showing
