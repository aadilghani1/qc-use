---
url: http://localhost:3100/login
secrets: [DEMO_EMAIL, DEMO_PASSWORD]
persona:
  name: Priya Raman
  company: Northwind Freight
---
# Delete the workspace

Destructive actions stop for a person's approval, even when the test asks for them.

1. Sign in with DEMO_EMAIL and DEMO_PASSWORD, then finish onboarding with the fewest steps
   - expect: the dashboard is showing
2. Delete the workspace
   - expect: the sign-in page is showing again
