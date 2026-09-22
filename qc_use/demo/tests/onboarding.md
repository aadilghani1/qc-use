---
url: http://localhost:3100/login
secrets: [DEMO_EMAIL, DEMO_PASSWORD]
files:
  avatar: avatar.png
persona:
  name: Priya Raman
  role: Head of Operations
  team_size: 51-200
  company: Northwind Freight
rate:
  onboarding_ease: [confusing, effortful, okay, smooth, effortless]
---
# Onboarding critical path

A new operations lead signs in for the first time and finishes onboarding.

1. Sign in with DEMO_EMAIL and DEMO_PASSWORD
   - expect: the "About you" onboarding step is showing
2. Fill in the profile as the persona, upload the avatar, and continue
   - expect: the workspace step is showing
3. Name the workspace after the persona's company, choose shipment tracking, and continue
   - expect: the invite step is showing
4. Skip inviting teammates for now
   - expect: the dashboard welcomes Priya and shows the Northwind Freight workspace
   - check: url contains /dashboard
