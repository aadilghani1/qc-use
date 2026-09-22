"""Capture fresh images only when secret masking can be checked against a stable page."""

import base64
import contextlib
import io
import json
import secrets as tokens

from PIL import Image, ImageDraw

# Hide opaque pixels before capture; the stylesheet does not change layout or input values.
PREPARE = """(id => {
  if (!document.body) return false;
  const opaque=e=>e.matches('iframe,frame,canvas,video,object,embed,img,svg') ||
    e.shadowRoot || e.localName.includes('-') || getComputedStyle(e).backgroundImage.includes('url(');
  const selector=e=>{
    const parts=[];
    while (e && e!==document.documentElement) {
      parts.unshift(CSS.escape(e.localName)+':nth-child('+([...e.parentNode.children].indexOf(e)+1)+')');
      e=e.parentElement;
    }
    return 'html'+(parts.length?'>'+parts.join('>'):'');
  };
  const selectors=[...document.querySelectorAll('*')].filter(opaque).map(selector);
  const style=document.createElement('style'); style.id=id;
  style.textContent='*::before,*::after{visibility:hidden!important}' +
    (selectors.length ? selectors.join(',')+'{opacity:0!important}' : '');
  document.head.append(style);
  return true;
})"""

# Inspect the whole supported document, including values outside the viewport.
SECRET_RECTS = """(values => {
  if (!document.body) return null;
  const rects=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT), nodes=[];
  let text='';
  for (let node; (node=walker.nextNode());) {
    nodes.push({node,start:text.length,end:text.length+node.textContent.length});
    text+=node.textContent;
  }
  for (const value of values) for (let i=text.indexOf(value); i>=0; i=text.indexOf(value,i+value.length)) {
    const first=nodes.find(n=>n.end>i), last=nodes.find(n=>n.end>=i+value.length);
    if (!first || !last) return null;
    const range=document.createRange();
    range.setStart(first.node,i-first.start); range.setEnd(last.node,i+value.length-last.start);
    for (const r of range.getClientRects()) rects.push([r.x,r.y,r.width,r.height]);
  }
  for (const e of document.querySelectorAll('input,textarea,select')) {
    if (e.type!=='password' && !values.some(v=>(e.value||'').includes(v))) continue;
    const r=e.getBoundingClientRect(); rects.push([r.x,r.y,r.width,r.height]);
  }
  if (values.length) for (const e of document.querySelectorAll('*')) {
    if (e.matches('iframe,frame,canvas,video,object,embed,img,svg') || e.shadowRoot ||
        e.localName.includes('-') || getComputedStyle(e).backgroundImage.includes('url(')) {
      if (getComputedStyle(e).opacity!=='0') return null;
      const r=e.getBoundingClientRect(); rects.push([r.x,r.y,r.width,r.height]);
    }
    for (const p of ['::before','::after']) {
      const css=getComputedStyle(e,p);
      if (!['none','normal','""'].includes(css.content) && css.visibility!=='hidden') return null;
    }
  }
  const geometry=[...document.querySelectorAll('*')].map(e=>{
    const r=e.getBoundingClientRect(); return [r.x,r.y,r.width,r.height];
  });
  return {rects, state:[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.documentElement.outerHTML,geometry,
    [...document.querySelectorAll('input,textarea,select')].map(e=>e.value)]};
})"""


def masked(browser, data, secrets):
    """Mask a new capture; omit images if the page changes or has unsupported secret surfaces."""
    # A cached screenshot cannot be paired safely with rectangles from the current document.
    del data
    values = [v for v in secrets.values() if v]
    expression = f"{SECRET_RECTS}({json.dumps(values)})"
    mask_id = "qc-use-mask-" + tokens.token_hex(8)
    prepared = False
    browser.capture_reason = None
    try:
        if values:
            prepared = True
            if not browser.evaluate(f"{PREPARE}({json.dumps(mask_id)})"):
                browser.capture_reason = "Page is not ready for secret masking."
                return None
        before = browser.evaluate(expression)
        if before is None:
            browser.capture_reason = "Opaque content could not be hidden safely."
            return None
        data = browser.call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        after = browser.evaluate(expression)
        if before != after:
            browser.capture_reason = "Page changed during capture; waiting for a stable view."
            return None
        image = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
        draw = ImageDraw.Draw(image)
        for x, y, w, h in before["rects"]:
            draw.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], fill=(24, 24, 24))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=80)
        return output.getvalue()
    except Exception:
        browser.capture_reason = "Capture or masking failed; no image saved."
        return None
    finally:
        if prepared:
            with contextlib.suppress(Exception):
                browser.evaluate(f"document.getElementById({json.dumps(mask_id)})?.remove()")


def screenshot(browser, page, folder, name, secrets):
    """Save only an image that passed masking and stability checks."""
    image = masked(browser, None, secrets)
    if image is None:
        return None
    (folder / name).write_bytes(image)
    return f"steps/{name}"
