---
url: http://localhost:3000/dashboard
---
# Authenticated dashboard

Use a dedicated profile with --manual-auth for OTP or OAuth.
This test checks the signed-in app, not the login mechanism. Adapt the route and visible text before running.

1. Check the signed-in dashboard
   - mode: observe
   - check: url contains /dashboard
   - check: text contains Dashboard
2. Reload the page
   - action: Reload the page
   - check: url contains /dashboard
   - check: text contains Dashboard
