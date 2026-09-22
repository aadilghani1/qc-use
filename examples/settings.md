---
url: http://localhost:3000/dashboard
---
# Save a display name

Use an authenticated dedicated profile. Adapt the route and labels to your app.
Use a disposable test account. This test changes its display name.

1. Open Profile settings
   - action: Click Profile settings
   - check: url contains /settings
2. Enter QA Tester in the display name field
   - action: Enter QA Tester in the display name field
   - expect: the display name field shows QA Tester
3. Save the profile
   - action: Click Save
   - expect: the page confirms that the profile was saved
4. Reload the page
   - action: Reload the page
   - expect: the display name field shows QA Tester
5. Go back in browser history
   - action: Go back in browser history
   - check: url contains /dashboard
