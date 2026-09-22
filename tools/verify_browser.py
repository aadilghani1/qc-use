"""Check real Chrome capture and viewport evidence on disposable, local-only content."""

import base64
import io
import time
import traceback
from pathlib import Path
from urllib.parse import quote

from PIL import Image

from qc_use.capture import masked
from qc_use.chrome import Chrome, connect, disconnect

HTML = """<!doctype html><html><head><style>
body{margin:0;background:linear-gradient(white,#eee);font:18px sans-serif}
#secret{position:absolute;left:20px;top:20px}#safe{position:absolute;left:20px;top:100px}
#generated::before{content:attr(data-private);position:fixed;left:600px;top:20px}
img,canvas,iframe,secret-box,svg{display:block;position:absolute;left:300px;top:20px;width:120px;height:60px}
canvas{top:100px}iframe{top:200px}secret-box{top:300px}svg{top:400px}
#footer{position:absolute;top:1600px}input{position:absolute;top:60px;left:20px}
</style></head><body>
<div id="secret">fixture-<span>password</span></div><input value="fixture-password">
<div id="safe">Safe content stays visible</div><div id="generated" data-private="fixture-password"></div>
<img alt="opaque" src="IMAGE">
<canvas></canvas><iframe srcdoc="fixture-password"></iframe><secret-box></secret-box>
<svg><text y="20">fixture-password</text></svg><div id="footer">Below the viewport</div>
<script>
customElements.define('secret-box',class extends HTMLElement{constructor(){super();
this.attachShadow({mode:'closed'}).innerHTML='<div style="position:fixed;left:500px;top:500px">fixture-password</div>'
}});
const c=document.querySelector('canvas').getContext('2d');c.fillText('fixture-password',0,20);
</script></body></html>"""


def main():
    """Exercise masking against actual pixels, then restore the private browser."""
    chrome = Chrome(headless=True)
    browser = None
    try:
        connect(chrome)
        from qc_use.engine.browser import Browser

        svg = "<svg xmlns='http://www.w3.org/2000/svg'><text y='20'>fixture-password</text></svg>"
        html = HTML.replace("IMAGE", "data:image/svg+xml," + quote(svg))
        browser = Browser("data:text/html," + quote(html))
        state = browser.observe(screenshot=False)
        assert "Below the viewport" not in state["text"]
        assert "Below the viewport" in state["document_text"]
        from qc_use.engine.agent import Policy
        from qc_use.spec import Check, Step, TestSpec
        from qc_use.verification import verify

        browser.evaluate(
            "document.querySelector('#safe').textContent='Loading';"
            "setTimeout(()=>document.querySelector('#safe').textContent='Ready',3500)"
        )
        step = Step(text="Observe delayed result", mode="observe", check=[Check.parse("text contains Ready")])
        spec = TestSpec(title="Delayed fixture", url="http://localhost:3000", steps=[step], verify_timeout=6)
        started = time.monotonic()
        checks, _ = verify(spec, step, browser, "Observe", guard=Policy())
        assert all(c.outcome == "pass" for c in checks) and time.monotonic() - started >= 3
        original_call = browser.call

        def diagnostic_call(method, **params):
            try:
                return original_call(method, **params)
            except Exception:
                print(f"Fixture browser command failed: {method}", flush=True)
                traceback.print_exc()
                raise

        browser.call = diagnostic_call
        before = browser.evaluate("document.documentElement.outerHTML")
        image = masked(browser, None, {"PASSWORD": "fixture-password"})
        assert image is not None, browser.capture_reason
        assert browser.evaluate("document.documentElement.outerHTML") == before
        pixels = Image.open(io.BytesIO(image))
        assert max(pixels.getpixel((30, 25))) < 70  # Known text is blacked out.
        assert min(pixels.getpixel((610, 25))) > 200  # Generated text outside its host is hidden.
        assert min(pixels.getpixel((510, 505))) > 200  # Closed-shadow overflow is hidden by host opacity.
        assert browser.evaluate("document.querySelector('input').value") == "fixture-password"
        assert browser.evaluate("getComputedStyle(document.querySelector('img')).opacity") == "1"
        Path("/tmp/qc-use-browser-fixture.jpg").write_bytes(image)
        browser.call = original_call

        def changed_capture(method, **params):
            result = original_call(method, **params)
            if method == "Page.captureScreenshot":
                browser.evaluate("document.querySelector('#secret').style.top='180px'")
            return result

        browser.call = changed_capture
        assert masked(browser, None, {"PASSWORD": "fixture-password"}) is None
        assert "changed" in browser.capture_reason
        browser.call = original_call
        raw = browser.call("Page.captureScreenshot", format="jpeg")["data"]
        assert base64.b64decode(raw)
        for size, key in [(3000, "text"), (10000, "document_text")]:
            browser.evaluate(
                "document.body.innerHTML='<span>'+ 'a'.repeat(" + str(size) + ") + '</span><span>' +"
                " 'b'.repeat(" + str(size - 1) + ") + 'Z</span>';"
                "document.body.style.cssText='font-size:1px;word-break:break-all'"
            )
            state = browser.observe(screenshot=False)
            assert state[key + "_truncated"], key
            assert "Z" not in state[key]
            try:
                Check.parse(("document" if key == "document_text" else "text") + " does not contain Z").evaluate(state)
            except ValueError:
                pass
            else:
                raise AssertionError("Truncated absence must not pass")
        print("PASS: real Chrome masks split text, fields, images, generated content, and opaque shadow content.")
        print("PASS: styles restored, changed captures withheld, viewport and document evidence separated.")
    finally:
        try:
            disconnect(browser)
        finally:
            chrome.close()


if __name__ == "__main__":
    main()
