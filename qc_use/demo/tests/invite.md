---
url: http://localhost:3100/login
secrets: [DEMO_EMAIL, DEMO_PASSWORD]
persona:
  name: Priya Raman
  role: Head of Operations
  team_size: 51-200
  company: Northwind Freight
fail_on: [http_5xx]
# This test sends an invite on purpose, to a test address. It keeps its own never-do rules instead of the defaults.
never_defaults: false
never:
  - delete an account, workspace, or stored data
  - make a payment or a purchase
---
# Invite a teammate during onboarding

The invite step is where a new team grows. Beacon's demo server has a planted bug here.

1. Sign in with DEMO_EMAIL and DEMO_PASSWORD
   - expect: the "About you" onboarding step is showing
2. Complete the profile and the workspace steps as the persona
   - expect: the invite step is showing
3. Invite a teammate at the address qa-teammate@example.test
   - expect: the page confirms the invite was sent
