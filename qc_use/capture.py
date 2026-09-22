"""Capture fresh images only when secret masking can be checked against a stable page."""

import base64
import io
import json

from PIL import Image, ImageDraw

# Inspect the whole supported document, including values outside the viewport.
SECRET_RECTS = """(values => {
  if (!document.body) return null;
  if (values.length && (document.querySelector('iframe,frame,canvas,video,object,embed,img') ||
      [...document.querySelectorAll('*')].some(e=>e.shadowRoot || e.localName.includes('-') ||
        ['::before','::after'].some(p=>!['none','normal','""'].includes(getComputedStyle(e,p).content))))) return null;
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
    try:
        before = browser.evaluate(expression)
        if before is None:
            return None
        data = browser.call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        after = browser.evaluate(expression)
        if before != after:
            return None
        image = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
        draw = ImageDraw.Draw(image)
        for x, y, w, h in before["rects"]:
            draw.rectangle([x - 3, y - 3, x + w + 3, y + h + 3], fill=(24, 24, 24))
        output = io.BytesIO()
        image.save(output, "JPEG", quality=80)
        return output.getvalue()
    except Exception:
        return None


def screenshot(browser, page, folder, name, secrets):
    """Save only an image that passed masking and stability checks."""
    image = masked(browser, None, secrets)
    if image is None:
        return None
    (folder / name).write_bytes(image)
    return f"steps/{name}"
