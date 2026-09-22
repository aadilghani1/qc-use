---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
---
# Change a setting

A signed-in user changes the display name. The change must still be there when the user opens the page again.

1. Sign in with LOGIN_EMAIL and LOGIN_PASSWORD
   - expect: the app is signed in
2. Open the profile settings and change the display name to "QA Tester"
   - expect: the page confirms that the settings are saved
3. Go to another page, then open the profile settings again
   - expect: the display name field shows QA Tester
   - check: text does not contain Error
