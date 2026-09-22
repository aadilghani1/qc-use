"""Beacon: a tiny fictional SaaS for trying qc-use. Login, three onboarding steps, a dashboard, and one real bug.

The invite endpoint fails with HTTP 500 on purpose, so the bundled tests show what a failure looks like.
"""

import html
import json
import secrets
import threading
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

EMAIL, PASSWORD = "demo@qc-use.test", "correct-horse-battery"
ROLES = ["Founder", "Head of Operations", "Engineer", "Other"]
TEAM_SIZES = ["1-10", "11-50", "51-200", "200+"]
USE_CASES = ["Track shipments", "Manage vendors", "Forecast demand"]
SESSIONS = {}

STYLE = """
*{box-sizing:border-box} body{margin:0; font:15px/1.5 system-ui,-apple-system,sans-serif; background:#f4f6f5;
color:#16201d} header{display:flex; align-items:center; gap:10px; padding:16px 28px; background:#fff;
border-bottom:1px solid #dfe5e2} header b{font-size:17px} .dot{width:14px; height:14px; border-radius:50%;
background:#148278} main{max-width:560px; margin:48px auto; padding:0 16px} .card{background:#fff; border:1px
solid #dfe5e2; border-radius:12px; padding:28px} h1{font-size:22px; margin:0 0 4px} p.sub{color:#5d6b66;
margin:0 0 22px} label{display:block; font-weight:600; margin:16px 0 6px}
input[type=text],input[type=email],input[type=password],select{width:100%; padding:10px 12px; border:1px solid
#c9d3cf; border-radius:8px; font:inherit} .row{display:flex; gap:14px; flex-wrap:wrap} .row
label{font-weight:400; margin:6px 0} button,.button{display:inline-block; margin-top:22px; padding:10px 18px;
border:0; border-radius:8px; background:#148278; color:#fff; font:600 15px system-ui; cursor:pointer;
text-decoration:none} .ghost{background:#e7eeeb; color:#16201d} .danger{background:#b3261e}
.error{background:#fdecea; color:#8c1d18; padding:10px 12px; border-radius:8px; margin-top:14px}
.steps{color:#5d6b66; font-size:13px; letter-spacing:.04em; text-transform:uppercase}
.upload{display:inline-block; padding:8px 14px; border:1px dashed #9fb3ab; border-radius:8px; cursor:pointer;
font-weight:400} ul.check{list-style:none; padding:0} ul.check li{padding:6px 0} .muted{color:#5d6b66}
"""


def page(title, body, user=None):
    who = f'<span class="muted" style="margin-left:auto">{html.escape(user)}</span>' if user else ""
    return (
        f"<!doctype html><html lang=en><head><meta charset=utf-8><title>{html.escape(title)} · Beacon</title>"
        f"<meta name=viewport content='width=device-width,initial-scale=1'><style>{STYLE}</style></head><body>"
        f'<header><span class="dot"></span><b>Beacon</b>{who}</header><main><div class="card">{body}</div></main>'
        "</body></html>"
    )


def login(error=""):
    note = f'<div class="error" role="alert">{html.escape(error)}</div>' if error else ""
    return page("Sign in", f"""<h1>Sign in to Beacon</h1><p class="sub">Operations tracking for growing teams.</p>
<form method=post action=/login>{note}
<label for=email>Email</label><input id=email name=email type=email autocomplete=username>
<label for=password>Password</label><input id=password name=password type=password autocomplete=current-password>
<button type=submit>Sign in</button></form>""")


def profile(s):
    roles = "".join(f"<option{' selected' if s.get('role') == r else ''}>{r}</option>" for r in ["", *ROLES])
    sizes = "".join(
        f'<label><input type=radio name=team value="{t}"{" checked" if s.get("team") == t else ""}> {t}</label>'
        for t in TEAM_SIZES
    )
    avatar = s.get("avatar") or "No file chosen"
    return page("About you", f"""<div class="steps">Step 1 of 3</div><h1>About you</h1>
<p class="sub">Tell us who is setting up Beacon.</p><form method=post action=/onboarding/profile>
<label for=name>Full name</label><input id=name name=name type=text value="{html.escape(s.get('name', ''))}">
<label for=role>Role</label><select id=role name=role>{roles}</select>
<label>Team size</label><div class="row">{sizes}</div>
<label>Avatar</label><label class="upload">Upload avatar<input id=avatar type=file accept="image/*" hidden
onchange="document.getElementById('avatar-name').textContent=this.files[0]?.name||'No file chosen';
fetch('/api/avatar',{{method:'POST',body:this.files[0]?.name||''}})"></label>
<span id=avatar-name class="muted">{html.escape(avatar)}</span>
<div><button type=submit>Continue</button></div></form>""", s["email"])


def workspace(s):
    boxes = "".join(
        f'<label><input type=checkbox name=use value="{u}"{" checked" if u in s.get("uses", []) else ""}> {u}</label>'
        for u in USE_CASES
    )
    return page("Your workspace", f"""<div class="steps">Step 2 of 3</div><h1>Create your workspace</h1>
<p class="sub">A workspace holds your team's shipments and vendors.</p><form method=post action=/onboarding/workspace>
<label for=workspace>Workspace name</label>
<input id=workspace name=workspace type=text value="{html.escape(s.get('workspace', ''))}">
<label>What will you use Beacon for?</label><div class="row">{boxes}</div>
<button type=submit>Continue</button></form>""", s["email"])


def invite(s):
    return page("Invite your team", """<div class="steps">Step 3 of 3</div><h1>Invite your team</h1>
<p class="sub">Beacon works best with your whole team. You can also do this later.</p>
<label for=teammate>Teammate email</label><input id=teammate type=email>
<button type=button onclick="send()">Send invite</button> <div id=status></div>
<form method=post action=/onboarding/finish><button type=submit class="ghost">Skip for now</button></form>
<script>
async function send(){
  const status=document.getElementById('status');
  const response=await fetch('/api/invite',{method:'POST',body:document.getElementById('teammate').value});
  if(response.ok){status.innerHTML='<p>Invite sent.</p><form method=post action=/onboarding/finish>'+
    '<button type=submit>Finish setup</button></form>';return}
  console.error('Invite failed with HTTP '+response.status);
  status.innerHTML='<div class="error" role="alert">Something went wrong. Try again.</div>';
}
</script>""", s["email"])


def dashboard(s):
    name = html.escape((s.get("name") or "there").split()[0])
    items = [("Profile", bool(s.get("name"))), ("Workspace", bool(s.get("workspace"))),
             ("Team", s.get("invited") or s.get("done"))]
    checklist = "".join(f"<li>{'✓' if done else '○'} {label}</li>" for label, done in items)
    uses = ", ".join(s.get("uses", [])) or "Not chosen"
    return page("Dashboard", f"""<h1>Welcome, {name}!</h1>
<p class="sub">Workspace: <b>{html.escape(s.get('workspace') or 'Untitled')}</b> · {html.escape(uses)}</p>
<h2 style="font-size:16px">Setup checklist</h2><ul class="check">{checklist}</ul>
<button class="danger" onclick="if(confirm('Delete this workspace? This cannot be undone.'))
fetch('/api/workspace',{{method:'DELETE'}}).then(()=>location='/login')">Delete workspace</button>""", s["email"])


class Handler(BaseHTTPRequestHandler):
    def session(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        token = cookie["beacon"].value if "beacon" in cookie else None
        return SESSIONS.get(token)

    def send(self, status, body="", kind="text/html; charset=utf-8", headers=()):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, headers=()):
        self.send(303, headers=[("Location", location), *headers])

    def form(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode() if length else ""
        return raw, parse_qs(raw)

    def do_GET(self):
        path, s = urlparse(self.path).path, self.session()
        if path in {"/", "/login"}:
            return self.send(200, login())
        if not s:
            return self.redirect("/login")
        views = {"/onboarding/profile": profile, "/onboarding/workspace": workspace, "/onboarding/invite": invite,
                 "/dashboard": dashboard}
        if path in views:
            return self.send(200, views[path](s))
        self.send(404, page("Not found", "<h1>Not found</h1>"))

    def do_POST(self):
        path, s = urlparse(self.path).path, self.session()
        raw, form = self.form()

        def field(name):
            return form.get(name, [""])[0].strip()

        if path == "/login":
            if field("email").lower() == EMAIL and field("password") == PASSWORD:
                token = secrets.token_urlsafe(16)
                SESSIONS[token] = {"email": EMAIL}
                return self.redirect("/onboarding/profile", [("Set-Cookie", f"beacon={token}; Path=/; HttpOnly")])
            return self.send(401, login("Email or password is incorrect."))
        if not s:
            return self.send(401, json.dumps({"error": "signed out"}), "application/json")
        if path == "/onboarding/profile":
            s.update(name=field("name"), role=field("role"), team=field("team"))
            return self.redirect("/onboarding/workspace")
        if path == "/onboarding/workspace":
            s.update(workspace=field("workspace"), uses=form.get("use", []))
            return self.redirect("/onboarding/invite")
        if path == "/onboarding/finish":
            s["done"] = True
            return self.redirect("/dashboard")
        if path == "/api/avatar":
            s["avatar"] = raw[:200]
            return self.send(204)
        if path == "/api/invite":
            # The planted bug: invites always fail on the server.
            return self.send(500, json.dumps({"error": "mailer unavailable"}), "application/json")
        self.send(404, json.dumps({"error": "not found"}), "application/json")

    def do_DELETE(self):
        s = self.session()
        if s and urlparse(self.path).path == "/api/workspace":
            s["workspace"] = ""
            return self.send(204)
        self.send(404, "")

    def log_message(self, *_args):
        pass


def serve(port=3100):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
