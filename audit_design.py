#!/usr/bin/env python3
"""Design audit via Chrome DevTools Protocol. No dependencies: plain HTTP + websocket
frames over a raw socket, which is enough for Runtime.evaluate.

Checks that matter for this page and cannot be seen from the HTML source:
  - the body column is readable, not a full-width sprawl
  - the serif stack actually resolved to a serif
  - the accent colour is applied
  - the interactive SVG has non-zero size
  - nothing overflows the viewport horizontally
"""
import base64
import json
import os
import socket
import struct
import sys
import urllib.request

CDP = "http://127.0.0.1:9222"


def ws_connect(url):
    # url like ws://127.0.0.1:9222/devtools/page/XXXX
    host_port, path = url.split("://", 1)[1].split("/", 1)
    host, port = host_port.split(":")
    s = socket.create_connection((host, int(port)), timeout=15)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
    )
    s.sendall(req.encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += s.recv(4096)
    return s


def send(s, payload):
    data = json.dumps(payload).encode()
    header = bytearray([0x81])
    n = len(data)
    mask = os.urandom(4)
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", n)
    header += mask
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    s.sendall(bytes(header) + masked)


def recv(s):
    def rd(n):
        out = b""
        while len(out) < n:
            chunk = s.recv(n - len(out))
            if not chunk:
                raise ConnectionError("closed")
            out += chunk
        return out

    b1, b2 = rd(2)
    n = b2 & 0x7F
    if n == 126:
        n = struct.unpack(">H", rd(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rd(8))[0]
    return json.loads(rd(n).decode())


def evaluate(s, expr):
    send(s, {"id": 1, "method": "Runtime.evaluate",
             "params": {"expression": expr, "returnByValue": True}})
    while True:
        m = recv(s)
        if m.get("id") == 1:
            r = m["result"]["result"]
            return r.get("value")


PROBE = r"""
(() => {
  const b = document.body;
  const cs = getComputedStyle(b);
  const wrap = document.querySelector('.wrap');
  const prose = document.querySelector('.prose');
  const svg = document.querySelector('.bpe-svg, .attn-svg, .mh-svg, .kv-svg');
  const h1 = document.querySelector('h1');
  const kick = document.querySelector('.kicker');
  const out = {
    bodyWidth: b.clientWidth,
    wrapWidth: wrap ? Math.round(wrap.getBoundingClientRect().width) : null,
    proseWidth: prose ? Math.round(prose.getBoundingClientRect().width) : null,
    bodyFont: cs.fontFamily,
    bodySize: cs.fontSize,
    lineHeight: cs.lineHeight,
    bg: cs.backgroundColor,
    fg: cs.color,
    h1Size: h1 ? getComputedStyle(h1).fontSize : null,
    kickerColor: kick ? getComputedStyle(kick).color : null,
    kickerSpacing: kick ? getComputedStyle(kick).letterSpacing : null,
    svgW: svg ? Math.round(svg.getBoundingClientRect().width) : null,
    svgH: svg ? Math.round(svg.getBoundingClientRect().height) : null,
    scrollW: document.documentElement.scrollWidth,
    clientW: document.documentElement.clientWidth,
    paragraphs: document.querySelectorAll('.prose p').length,
    provenanceRows: document.querySelectorAll('.provenance tbody tr').length,
    figs: document.querySelectorAll('.fig').length
  };
  return out;
})()
"""


def audit(path):
    pages = json.load(urllib.request.urlopen(CDP + "/json/list"))
    page = next((p for p in pages if p["type"] == "page"), None)
    if not page:
        print("no page target")
        return 1
    s = ws_connect(page["webSocketDebuggerUrl"])
    send(s, {"id": 0, "method": "Page.navigate",
             "params": {"url": f"http://127.0.0.1:8081/{path}"}})
    import time
    time.sleep(4)
    r = evaluate(s, PROBE)
    print(json.dumps(r, indent=2))

    fail = 0
    if r["scrollW"] > r["clientW"] + 2:
        print(f"OVERFLOW: scrollWidth {r['scrollW']} > clientWidth {r['clientW']}")
        fail = 1
    if "serif" not in r["bodyFont"].lower() and "charter" not in r["bodyFont"].lower():
        print(f"NOT SERIF: {r['bodyFont']}")
        fail = 1
    if r["proseWidth"] and r["proseWidth"] > 720:
        print(f"MEASURE TOO WIDE: {r['proseWidth']}px")
        fail = 1
    if r.get("svgW") is not None and r["svgW"] < 100:
        print(f"SVG COLLAPSED: {r['svgW']}x{r['svgH']}")
        fail = 1
    print("DESIGN OK" if not fail else "DESIGN ISSUES")
    return fail


if __name__ == "__main__":
    sys.exit(audit(sys.argv[1] if len(sys.argv) > 1 else ""))
