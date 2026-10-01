"""store-pos: a small till and stock app for a retail-shed store.

Standard library only (http.server + sqlite3) so the image is just the SUSE BCI
Python base plus this file. Everything store-specific comes from the
environment, which Fleet fills from the store cluster's labels, and from the
price list mounted at PRICES_FILE.

The till keeps working when HQ is unreachable: sales are written locally and
the page only reports the WAN state (it probes HQ_URL in the background).

MODE=till (default) serves the till; MODE=collect serves the click & collect
board that flagship stores also run.
"""

import html
import json
import os
import sqlite3
import ssl
import threading
import time
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE = os.environ.get("STORE_ID", "unknown")
REGION = os.environ.get("STORE_REGION", "unknown")
TIER = os.environ.get("STORE_TIER", "standard")
MODE = os.environ.get("MODE", "till")
VERSION = os.environ.get("APP_VERSION", "dev")
BANNER = os.environ.get("BANNER", "")
CURRENCY = os.environ.get("CURRENCY", "£")
PRICES_FILE = os.environ.get("PRICES_FILE", "/config/prices.json")
DB_FILE = os.environ.get("DB_FILE", "/data/store.db")
HQ_URL = os.environ.get("HQ_URL", "")
PORT = int(os.environ.get("PORT", "8080"))

DEFAULT_PRICES = {
    "multiplier": 1.0,
    "items": [
        {"sku": "TEA-001", "name": "Breakfast tea (80)", "price": 3.50, "stock": 40},
        {"sku": "MLK-002", "name": "Semi-skimmed milk 2L", "price": 1.65, "stock": 60},
        {"sku": "BRD-003", "name": "Sourdough loaf", "price": 2.95, "stock": 25},
        {"sku": "JAM-004", "name": "Strawberry jam", "price": 2.20, "stock": 30},
    ],
}

wan = {"online": None, "checked": None}
db_lock = threading.Lock()


def load_prices():
    try:
        with open(PRICES_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return DEFAULT_PRICES


def db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_FILE), exist_ok=True)
    with db_lock, db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS stock (sku TEXT PRIMARY KEY, qty INTEGER NOT NULL)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sales (id INTEGER PRIMARY KEY, ts TEXT, sku TEXT, price REAL, wan_online INTEGER)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, ts TEXT, customer TEXT, status TEXT)"
        )
        # New SKUs from the price list get their opening stock; existing stock is kept
        for item in load_prices()["items"]:
            conn.execute("INSERT OR IGNORE INTO stock VALUES (?, ?)", (item["sku"], item.get("stock", 0)))


def catalogue():
    prices = load_prices()
    mult = float(prices.get("multiplier", 1.0))
    with db_lock, db() as conn:
        stock = {r["sku"]: r["qty"] for r in conn.execute("SELECT sku, qty FROM stock")}
    return [
        {"sku": i["sku"], "name": i["name"], "price": round(i["price"] * mult, 2), "stock": stock.get(i["sku"], 0)}
        for i in prices["items"]
    ]


def sell(sku):
    item = next((i for i in catalogue() if i["sku"] == sku), None)
    if item is None:
        return 404, {"error": f"unknown sku {sku}"}
    with db_lock, db() as conn:
        cur = conn.execute("UPDATE stock SET qty = qty - 1 WHERE sku = ? AND qty > 0", (sku,))
        if cur.rowcount == 0:
            return 409, {"error": f"{sku} is out of stock"}
        conn.execute(
            "INSERT INTO sales (ts, sku, price, wan_online) VALUES (?, ?, ?, ?)",
            (now(), sku, item["price"], 1 if wan["online"] else 0),
        )
    return 200, {"sold": sku, "price": item["price"]}


def summary():
    with db_lock, db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(price), 0) total, COALESCE(SUM(1 - wan_online), 0) offline FROM sales"
        ).fetchone()
    return {"sales": row["n"], "takings": round(row["total"], 2), "sold_while_offline": row["offline"]}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def probe_hq():
    """Background WAN check: can this store reach HQ?"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # reachability only; nothing is sent
    while True:
        ok = False
        if HQ_URL:
            try:
                with urllib.request.urlopen(HQ_URL, timeout=3, context=ctx) as r:
                    ok = r.status < 500
            except Exception:
                ok = False
        wan["online"], wan["checked"] = ok, now()
        time.sleep(10)


def info():
    return {"store": STORE, "region": REGION, "tier": TIER, "mode": MODE, "version": VERSION,
            "wan_online": wan["online"], "wan_checked": wan["checked"]}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg:#f6f7f9; --card:#fff; --ink:#1b1f24; --muted:#5b6470; --accent:#30ba78; --warn:#c0392b; --line:#dde1e6; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#14171b; --card:#1d2127; --ink:#e8eaed; --muted:#9aa3ad; --line:#2c323a; }} }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font:16px/1.4 system-ui,sans-serif; background:var(--bg); color:var(--ink); }}
header {{ padding:16px; background:var(--card); border-bottom:1px solid var(--line); display:flex; flex-wrap:wrap; gap:12px; align-items:center; }}
header h1 {{ font-size:20px; margin:0 auto 0 0; }}
.pill {{ padding:3px 10px; border-radius:99px; border:1px solid var(--line); font-size:13px; color:var(--muted); }}
.on {{ color:#fff; background:var(--accent); border-color:var(--accent); }}
.off {{ color:#fff; background:var(--warn); border-color:var(--warn); }}
.banner {{ margin:16px; padding:12px 16px; border-radius:8px; background:var(--accent); color:#fff; }}
main {{ padding:0 16px 16px; display:grid; gap:12px; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px; }}
.price {{ font-size:24px; font-weight:600; }}
button {{ width:100%; margin-top:10px; padding:10px; font-size:16px; border:0; border-radius:8px; background:var(--accent); color:#fff; cursor:pointer; }}
button:disabled {{ background:var(--line); color:var(--muted); cursor:default; }}
footer {{ padding:0 16px 24px; color:var(--muted); font-size:14px; }}
</style></head><body>
<header><h1>{title}</h1>
<span class="pill">{region}</span><span class="pill">{tier}</span><span class="pill">v{version}</span>
<span id="wan" class="pill">WAN …</span></header>
{banner}
<main id="main"></main>
<footer id="foot"></footer>
<script>
const cur = {currency};
async function refresh() {{
  const i = await (await fetch('api/info')).json();
  const w = document.getElementById('wan');
  w.textContent = i.wan_online === null ? 'WAN …' : (i.wan_online ? 'HQ online' : 'HQ offline - trading locally');
  w.className = 'pill ' + (i.wan_online ? 'on' : (i.wan_online === null ? '' : 'off'));
  {mode_js}
}}
async function sell(sku) {{
  const r = await fetch('api/sale', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{sku}})}});
  if (!r.ok) alert((await r.json()).error);
  refresh();
}}
async function order() {{
  const name = prompt('Customer name'); if (!name) return;
  await fetch('api/orders', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{customer:name}})}});
  refresh();
}}
async function ready(id) {{ await fetch('api/orders/' + id + '/ready', {{method:'POST'}}); refresh(); }}
const esc = s => String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
refresh(); setInterval(refresh, 5000);
</script></body></html>"""

TILL_JS = """
  const items = await (await fetch('api/items')).json();
  document.getElementById('main').innerHTML = items.map(it => `<div class="card">
    <div>${esc(it.name)}</div><div class="price">${cur}${it.price.toFixed(2)}</div>
    <div style="color:var(--muted)">${esc(it.sku)} · ${it.stock} in stock</div>
    <button ${it.stock > 0 ? '' : 'disabled'} onclick="sell('${esc(it.sku)}')">Sell</button></div>`).join('');
  const s = await (await fetch('api/summary')).json();
  document.getElementById('foot').textContent =
    `${s.sales} sales · takings ${cur}${s.takings.toFixed(2)} · ${s.sold_while_offline} sold while HQ was offline`;"""

COLLECT_JS = """
  const orders = await (await fetch('api/orders')).json();
  document.getElementById('main').innerHTML = `<div class="card"><button onclick="order()">New click &amp; collect order</button></div>` +
    orders.map(o => `<div class="card"><div class="price">#${o.id}</div><div>${esc(o.customer)}</div>
    <div style="color:var(--muted)">${esc(o.status)} · ${esc(o.ts)}</div>
    <button ${o.status === 'waiting' ? '' : 'disabled'} onclick="ready(${o.id})">Ready for collection</button></div>`).join('');
  document.getElementById('foot').textContent = `${orders.filter(o => o.status === 'waiting').length} orders waiting`;"""


def page():
    kind = "Click & collect" if MODE == "collect" else "Till"
    banner = f'<div class="banner">{html.escape(BANNER)}</div>' if BANNER else ""
    return PAGE.format(
        title=html.escape(f"{kind} · store {STORE}"), region=html.escape(REGION), tier=html.escape(TIER),
        version=html.escape(VERSION), banner=banner, currency=json.dumps(CURRENCY),
        mode_js=COLLECT_JS if MODE == "collect" else TILL_JS,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "store-pos"

    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self.send(200, page(), "text/html; charset=utf-8")
        elif path == "/healthz":
            self.send(200, {"ok": True})
        elif path == "/api/info":
            self.send(200, info())
        elif path == "/api/items":
            self.send(200, catalogue())
        elif path == "/api/summary":
            self.send(200, summary())
        elif path == "/api/orders":
            with db_lock, db() as conn:
                rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 50").fetchall()
            self.send(200, [dict(r) for r in rows])
        else:
            self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/sale":
            self.send(*sell(str(self.body().get("sku", ""))))
        elif path == "/api/orders":
            customer = str(self.body().get("customer", "")).strip()[:60] or "walk-in"
            with db_lock, db() as conn:
                cur = conn.execute(
                    "INSERT INTO orders (ts, customer, status) VALUES (?, ?, 'waiting')", (now(), customer)
                )
            self.send(201, {"id": cur.lastrowid})
        elif path.startswith("/api/orders/") and path.endswith("/ready"):
            oid = path.split("/")[3]
            with db_lock, db() as conn:
                conn.execute("UPDATE orders SET status = 'ready' WHERE id = ?", (oid,))
            self.send(200, {"id": oid, "status": "ready"})
        else:
            self.send(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        if not self.path.startswith(("/healthz", "/api/info")):
            super().log_message(fmt, *args)


if __name__ == "__main__":
    init_db()
    threading.Thread(target=probe_hq, daemon=True).start()
    print(f"store-pos {VERSION}: store {STORE} ({REGION}, {TIER}), mode {MODE}, port {PORT}", flush=True)
    ThreadingHTTPServer(("", PORT), Handler).serve_forever()
