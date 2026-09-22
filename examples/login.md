---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
---
# Sign in

Adapt the labels and expected route to your app. Use an existing test account.

1. Enter LOGIN_EMAIL in the email field
   - action: Enter LOGIN_EMAIL in the email field
   - expect: the email field holds the LOGIN_EMAIL secret
2. Enter LOGIN_PASSWORD in the password field
   - action: Enter LOGIN_PASSWORD in the password field
   - expect: the password field is filled
3. Submit the sign-in form
   - action: Submit the sign-in form
   - check: url contains /dashboard
4. Check the dashboard
   - mode: observe
   - check: url contains /dashboard
