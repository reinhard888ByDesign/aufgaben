#!/usr/bin/env python3
"""Aufgaben-Verwaltung — Task Manager auf Port 8096."""

import sqlite3
from datetime import date, datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "aufgaben.db"

KATEGORIEN = [
    "Immobilien", "KFZ", "Gesundheit", "Business",
    "Haushalt", "Familie", "Finanzen", "Sonstiges",
]
THEMEN = [
    "01-Italien", "02-Finanzen", "03-Immobilien", "04-Digitales",
    "05-Reisen", "06-Routinen", "07-Gesundheit", "08-Familie", "09-FengShui",
]
PRIORITAETEN    = ["hoch", "mittel", "niedrig"]
STATUSWERTE     = ["offen", "in Bearbeitung", "erledigt"]
WIEDERHOLUNGEN  = ["täglich", "wöchentlich", "monatlich", "jährlich"]

app = FastAPI(title="Aufgaben")


# ── DB ────────────────────────────────────────────────────────────────────────

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def ensure_schema():
    with get_db() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS aufgaben (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                was         TEXT    NOT NULL,
                wann        DATE,
                kategorie   TEXT,
                thema       TEXT,
                projekt     TEXT,
                link        TEXT,
                status      TEXT    DEFAULT 'offen',
                prioritaet  TEXT    DEFAULT 'mittel',
                notiz       TEXT,
                reminded_at DATE,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        for col in ["thema TEXT", "projekt TEXT", "link TEXT", "wiederholung TEXT"]:
            try:
                con.execute(f"ALTER TABLE aufgaben ADD COLUMN {col}")
            except Exception:
                pass


ensure_schema()


# ── HTML ──────────────────────────────────────────────────────────────────────

THEMA_LABELS = {
    "01-Italien":    "🇮🇹 01 · Italien",
    "02-Finanzen":   "💶 02 · Finanzen",
    "03-Immobilien": "🏠 03 · Immobilien",
    "04-Digitales":  "💻 04 · Digitales",
    "05-Reisen":     "✈️ 05 · Reisen",
    "06-Routinen":   "🔁 06 · Routinen",
    "07-Gesundheit": "❤️ 07 · Gesundheit",
    "08-Familie":    "👨‍👩‍👧 08 · Familie",
    "09-FengShui":   "☯️ 09 · Feng Shui",
}

CSS = """
:root{
  --bg:#f5f5f5;--card:#fff;--text:#333;--muted:#888;--border:#e0e0e0;
  --accent:#2563eb;--green:#16a34a;--orange:#ea580c;--red:#dc2626;
  --yellow:#ca8a04;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif;
     background:var(--bg);color:var(--text);line-height:1.5;padding:16px}
h1{font-size:1.3rem;margin-bottom:16px;font-weight:700}
.top-bar{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
.btn{padding:7px 14px;border:none;border-radius:6px;cursor:pointer;font-size:.88rem;
     font-weight:500;text-decoration:none;display:inline-block}
.btn-primary{background:var(--accent);color:#fff}
.btn-primary:hover{background:#1d4ed8}
.btn-sm{padding:4px 9px;font-size:.8rem}
.btn-edit{background:#f1f5f9;color:var(--text);border:1px solid var(--border)}
.btn-edit:hover{background:#e2e8f0}
.btn-delete{background:#fee2e2;color:var(--red);border:1px solid #fecaca}
.btn-done{background:#dcfce7;color:var(--green);border:1px solid #bbf7d0}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;align-items:center}
.filters select{padding:5px 10px;border:1px solid var(--border);border-radius:6px;
                background:var(--card);font-size:.88rem;color:var(--text)}
.count{font-size:.82rem;color:var(--muted);margin-left:auto}
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:8px;overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{background:#fafafa;padding:7px 9px;text-align:left;border-bottom:2px solid var(--border);
   white-space:nowrap;font-weight:600;color:var(--muted);font-size:.77rem;text-transform:uppercase;letter-spacing:.4px}
td{padding:7px 9px;border-bottom:1px solid var(--border);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8faff}
tr.erledigt td{opacity:.45}
.was-cell .projekt{font-size:.77rem;color:var(--muted);margin-top:1px}
.was-cell a.ext{font-size:.77rem;color:var(--accent);text-decoration:none;margin-left:4px}
.badge{display:inline-block;padding:2px 7px;border-radius:4px;font-size:.74rem;font-weight:600}
.prio-hoch{background:#fee2e2;color:var(--red)}
.prio-mittel{background:#fef9c3;color:var(--yellow)}
.prio-niedrig{background:#f0fdf4;color:var(--green)}
.status-offen{background:#eff6ff;color:var(--accent)}
.status-in-bearbeitung{background:#fef3c7;color:var(--orange)}
.status-erledigt{background:#f0fdf4;color:var(--green)}
.thema-badge{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.72rem;
             background:#f1f5f9;color:var(--muted);white-space:nowrap}
.faellig{color:var(--red);font-weight:600}
.heute{color:var(--orange);font-weight:600}
.actions{display:flex;gap:4px;white-space:nowrap}
/* View toggle */
.view-toggle{display:flex;gap:0;border:1px solid var(--border);border-radius:6px;overflow:hidden}
.view-toggle button{padding:6px 14px;border:none;background:var(--card);color:var(--muted);
  cursor:pointer;font-size:.85rem;transition:background .15s}
.view-toggle button.active{background:var(--accent);color:#fff}
/* Gruppenansicht */
.group-section{margin-bottom:12px}
.group-header{display:flex;align-items:center;gap:10px;
  padding:9px 13px;background:var(--card);border:1px solid var(--border);
  border-radius:8px;cursor:pointer;user-select:none;transition:background .12s}
.group-header:hover{background:#f0f4ff}
.group-header.open{border-radius:8px 8px 0 0;border-bottom:2px solid var(--accent)}
.group-toggle{font-size:.8rem;color:var(--muted);transition:transform .2s;display:inline-block}
.group-header.open .group-toggle{transform:rotate(90deg)}
.group-header h2{font-size:.93rem;font-weight:700;margin:0}
.group-stats{font-size:.78rem;color:var(--muted);margin-left:auto;display:flex;gap:8px;align-items:center}
.group-stats .overdue{color:var(--red);font-weight:600}
.group-stats .naechste{color:var(--muted)}
.group-body{display:none}
.group-body.open{display:block}
.group-body .table-wrap{border-radius:0 0 8px 8px;border-top:none}
/* Modal */
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:100;
         align-items:center;justify-content:center}
.overlay.open{display:flex}
.modal{background:var(--card);border-radius:10px;padding:22px;width:min(520px,96vw);
       box-shadow:0 8px 32px rgba(0,0,0,.18);max-height:90vh;overflow-y:auto}
.modal h2{font-size:1.05rem;margin-bottom:16px}
.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.form-row{margin-bottom:0}
.form-row.full{grid-column:1/-1}
.form-row label{display:block;font-size:.8rem;color:var(--muted);margin-bottom:3px;font-weight:500}
.form-row input,.form-row select,.form-row textarea{
  width:100%;padding:6px 9px;border:1px solid var(--border);border-radius:6px;
  font-size:.88rem;font-family:inherit;background:var(--card);color:var(--text)}
.form-row textarea{min-height:60px;resize:vertical}
.modal-btns{display:flex;gap:8px;justify-content:flex-end;margin-top:18px}
@media(max-width:600px){body{padding:8px}.form-grid{grid-template-columns:1fr}}
"""

def _prio_badge(p):
    p = p or "mittel"
    labels = {"hoch": "▲ hoch", "mittel": "● mittel", "niedrig": "▽ niedrig"}
    return f'<span class="badge prio-{p}">{labels.get(p, p)}</span>'

def _status_badge(s):
    s = s or "offen"
    cls = "status-" + s.replace(" ", "-")
    return f'<span class="badge {cls}">{s}</span>'

def _wann_cell(wann):
    if not wann:
        return '<span style="color:var(--muted)">–</span>'
    try:
        d = date.fromisoformat(wann)
        today = date.today()
        fmt = d.strftime("%d.%m.%Y")
        if d < today:
            return f'<span class="faellig">⚠ {fmt}</span>'
        elif d == today:
            return f'<span class="heute">● {fmt}</span>'
        return fmt
    except Exception:
        return wann

def _row_html(r, show_thema=True):
    rid = r["id"]
    done_cls = " erledigt" if r["status"] == "erledigt" else ""
    done_btn = "" if r["status"] == "erledigt" else (
        f'<button class="btn btn-sm btn-done" onclick="markDone({rid})">✓</button>'
    )
    wdh = r["wiederholung"] if r["wiederholung"] else None
    wdh_icons = {"täglich":"↻d","wöchentlich":"↻w","monatlich":"↻m","jährlich":"↻y"}
    wdh_badge = (f'<span class="thema-badge" title="Wiederholt {wdh}" '
                 f'style="background:#e0f2fe;color:#0369a1">{wdh_icons.get(wdh,wdh)}</span> '
                 if wdh else "")
    thema_badge = (f'<span class="thema-badge">{r["thema"]}</span> '
                   if r["thema"] and show_thema else "")
    projekt_line = f'<div class="projekt">{r["projekt"]}</div>' if r["projekt"] else ""
    ext_link = (f' <a class="ext" href="{r["link"]}" target="_blank" rel="noopener">↗</a>'
                if r["link"] else "")
    notiz_attr = f' title="{r["notiz"]}"' if r["notiz"] else ""
    return f"""
    <tr id="row-{rid}" class="{done_cls.strip()}" data-id="{rid}">
      <td style="width:28px"><input type="checkbox" class="row-chk" value="{rid}" onchange="onChk()"></td>
      <td class="was-cell"{notiz_attr}>
        {wdh_badge}{thema_badge}<span>{r['was']}{' 📝' if r['notiz'] else ''}{ext_link}</span>
        {projekt_line}
      </td>
      <td>{_wann_cell(r['wann'])}</td>
      <td>{r['kategorie'] or '–'}</td>
      <td>{_prio_badge(r['prioritaet'])}</td>
      <td>{_status_badge(r['status'])}</td>
      <td class="actions">
        {done_btn}
        <button class="btn btn-sm btn-edit" onclick="openEdit({rid})">✏</button>
        <button class="btn btn-sm btn-delete" onclick="del({rid})">🗑</button>
      </td>
    </tr>"""

def _opts(options, selected, placeholder=None):
    html = f'<option value="">{placeholder}</option>' if placeholder else ""
    for o in options:
        sel = " selected" if o == selected else ""
        html += f'<option value="{o}"{sel}>{o}</option>'
    return html

def _group_stats_html(group_rows):
    today = date.today().isoformat()
    offen   = sum(1 for r in group_rows if r["status"] != "erledigt")
    overdue = sum(1 for r in group_rows
                  if r["status"] != "erledigt" and r["wann"] and r["wann"] < today)
    upcoming = sorted(
        (r["wann"] for r in group_rows
         if r["status"] != "erledigt" and r["wann"] and r["wann"] >= today),
    )
    parts = [f'<span>{offen} offen</span>']
    if overdue:
        parts.append(f'<span class="overdue">⚠ {overdue} überfällig</span>')
    if upcoming:
        try:
            nd = date.fromisoformat(upcoming[0]).strftime("%d.%m.")
            parts.append(f'<span class="naechste">nächste {nd}</span>')
        except Exception:
            pass
    return "".join(f'<span style="margin-left:8px">{p}</span>' for p in parts)


def _collapsible_group(key, label, group_rows, show_thema=False):
    stats      = _group_stats_html(group_rows)
    table_rows = "".join(_row_html(r, show_thema=show_thema) for r in group_rows)
    safe_key   = key.replace(" ", "_").replace("/", "_")
    return f"""
    <div class="group-section" data-group="{safe_key}">
      <div class="group-header" onclick="toggleGroup('{safe_key}')">
        <span class="group-toggle">▶</span>
        <h2>{label}</h2>
        <div class="group-stats">{stats}</div>
      </div>
      <div class="group-body" id="gb-{safe_key}">
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th style="width:28px"><input type="checkbox" onchange="toggleGroupAll(this)" onclick="event.stopPropagation()"></th>
              <th>Was / Projekt</th><th>Fällig</th>
              <th>Kategorie</th><th>Priorität</th><th>Status</th><th></th>
            </tr></thead>
            <tbody>{table_rows}</tbody>
          </table>
        </div>
      </div>
    </div>"""


def _build_grouped_html(rows):
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in rows:
        key = r["thema"] or "Sonstiges"
        buckets[key].append(r)
    ordered_keys = [t for t in THEMEN if t in buckets]
    if "Sonstiges" in buckets:
        ordered_keys.append("Sonstiges")
    for k in buckets:
        if k not in ordered_keys:
            ordered_keys.append(k)
    return "\n".join(
        _collapsible_group(k, THEMA_LABELS.get(k, k), buckets[k])
        for k in ordered_keys
    )


def _build_month_html(rows):
    from collections import defaultdict
    today = date.today()
    buckets = defaultdict(list)
    for r in rows:
        if not r["wann"]:
            buckets["__kein_datum"].append(r)
        else:
            try:
                d = date.fromisoformat(r["wann"])
                if d < today.replace(day=1):
                    buckets["__ueberfaellig"].append(r)
                else:
                    buckets[d.strftime("%Y-%m")].append(r)
            except Exception:
                buckets["__kein_datum"].append(r)

    MONAT_DE = ["", "Januar", "Februar", "März", "April", "Mai", "Juni",
                "Juli", "August", "September", "Oktober", "November", "Dezember"]
    ordered = []
    if "__ueberfaellig" in buckets:
        ordered.append("__ueberfaellig")
    month_keys = sorted(k for k in buckets if k.startswith("20"))
    ordered.extend(month_keys)
    if "__kein_datum" in buckets:
        ordered.append("__kein_datum")

    def month_label(key):
        if key == "__ueberfaellig": return "⚠️ Überfällig"
        if key == "__kein_datum":   return "💤 Ohne Datum"
        y, m = key.split("-")
        name = MONAT_DE[int(m)]
        mark = " ●" if key == today.strftime("%Y-%m") else ""
        return f"📅 {name} {y}{mark}"

    return "\n".join(
        _collapsible_group(k, month_label(k), buckets[k], show_thema=True)
        for k in ordered
    )


def build_page(rows, fs="", fk="", fp="", ft="", fq="", view="liste"):
    list_html    = "".join(_row_html(r) for r in rows)
    grouped_html = _build_grouped_html(rows)
    month_html   = _build_month_html(rows)
    return f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Aufgaben</title><style>{CSS}</style></head><body>
<h1>📋 Aufgaben</h1>
<div class="top-bar">
  <button class="btn btn-primary" onclick="openNew()">+ Neue Aufgabe</button>
  <div class="view-toggle">
    <button id="btn-liste"     onclick="setView('liste')"     class="{'active' if view=='liste' else ''}">☰ Liste</button>
    <button id="btn-kategorie" onclick="setView('kategorie')" class="{'active' if view=='kategorie' else ''}">⊞ Thema</button>
    <button id="btn-monat"     onclick="setView('monat')"     class="{'active' if view=='monat' else ''}">📅 Monat</button>
  </div>
  <span class="count">{len(rows)} Aufgaben</span>
</div>
<div class="filters">
  <input type="search" id="f-q" placeholder="🔍 Suche…" value="{fq}"
    oninput="schedSearch()" onkeydown="if(event.key==='Enter')applyFilter()"
    style="padding:5px 10px;border:1px solid var(--border);border-radius:6px;
           background:var(--card);font-size:.88rem;color:var(--text);min-width:180px">
  <select id="f-status" onchange="applyFilter()">
    <option value="">Alle Status</option>
    {"".join(f'<option value="{s}"{" selected" if s==fs else ""}>{s}</option>' for s in STATUSWERTE)}
  </select>
  <select id="f-thema" onchange="applyFilter()">
    <option value="">Alle Themen</option>
    {"".join(f'<option value="{t}"{" selected" if t==ft else ""}>{t}</option>' for t in THEMEN)}
  </select>
  <select id="f-kat" onchange="applyFilter()">
    <option value="">Alle Kategorien</option>
    {"".join(f'<option value="{k}"{" selected" if k==fk else ""}>{k}</option>' for k in KATEGORIEN)}
  </select>
  <select id="f-prio" onchange="applyFilter()">
    <option value="">Alle Prioritäten</option>
    {"".join(f'<option value="{p}"{" selected" if p==fp else ""}>{p}</option>' for p in PRIORITAETEN)}
  </select>
</div>
<!-- Bulk-Action-Bar (erscheint wenn Zeilen markiert) -->
<div id="bulk-bar" style="display:none;align-items:center;gap:8px;flex-wrap:wrap;
  background:#1e3a5f;color:#fff;padding:10px 14px;border-radius:8px;margin-bottom:12px">
  <span id="bulk-count" style="font-weight:600;font-size:.9rem"></span>
  <select id="bulk-thema" style="padding:4px 8px;border-radius:5px;font-size:.85rem">
    <option value="">Thema ändern…</option>
    {"".join(f'<option value="{t}">{t}</option>' for t in THEMEN)}
  </select>
  <select id="bulk-kat" style="padding:4px 8px;border-radius:5px;font-size:.85rem">
    <option value="">Kategorie ändern…</option>
    {"".join(f'<option value="{k}">{k}</option>' for k in KATEGORIEN)}
  </select>
  <select id="bulk-prio" style="padding:4px 8px;border-radius:5px;font-size:.85rem">
    <option value="">Priorität ändern…</option>
    {"".join(f'<option value="{p}">{p}</option>' for p in PRIORITAETEN)}
  </select>
  <input type="date" id="bulk-wann" style="padding:4px 8px;border-radius:5px;font-size:.85rem"
         title="Datum für alle setzen">
  <button class="btn btn-sm" style="background:#3b82f6;color:#fff" onclick="bulkApply()">Anwenden</button>
  <button class="btn btn-sm" style="background:#dc2626;color:#fff" onclick="bulkDelete()">🗑 Löschen</button>
  <button class="btn btn-sm" style="background:rgba(255,255,255,.15);color:#fff" onclick="clearSelection()">✕ Abwählen</button>
</div>

<!-- Listen-Ansicht -->
<div id="view-liste" style="display:{'block' if view=='liste' else 'none'}">
<div class="table-wrap"><table>
  <thead><tr>
    <th style="width:28px"><input type="checkbox" id="chk-all" onchange="toggleAll(this)" title="Alle"></th>
    <th>Was / Thema / Projekt</th><th>Fällig</th>
    <th>Kategorie</th><th>Priorität</th><th>Status</th><th></th>
  </tr></thead>
  <tbody id="tbody">{list_html}</tbody>
</table></div>
</div>

<!-- Thema-Ansicht -->
<div id="view-kategorie" style="display:{'block' if view=='kategorie' else 'none'}">
{grouped_html}
</div>

<!-- Monat-Ansicht -->
<div id="view-monat" style="display:{'block' if view=='monat' else 'none'}">
{month_html}
</div>

<!-- Modal -->
<div class="overlay" id="overlay">
 <div class="modal">
  <h2 id="modal-title">Neue Aufgabe</h2>
  <form id="modal-form">
   <input type="hidden" id="edit-id">
   <div class="form-grid">
    <div class="form-row full">
     <label>Was? *</label>
     <input type="text" id="f-was" required placeholder="Aufgabe…">
    </div>
    <div class="form-row">
     <label>Thema</label>
     <select id="f-thema-m"><option value="">– wählen –</option>
      {"".join(f'<option value="{t}">{t}</option>' for t in THEMEN)}
     </select>
    </div>
    <div class="form-row">
     <label>Projekt</label>
     <input type="text" id="f-projekt" placeholder="Projekt…">
    </div>
    <div class="form-row">
     <label>Wann?</label>
     <input type="date" id="f-wann">
    </div>
    <div class="form-row">
     <label>Kategorie</label>
     <select id="f-kategorie"><option value="">– wählen –</option>
      {"".join(f'<option value="{k}">{k}</option>' for k in KATEGORIEN)}
     </select>
    </div>
    <div class="form-row">
     <label>Priorität</label>
     <select id="f-prioritaet">{_opts(PRIORITAETEN, "mittel")}</select>
    </div>
    <div class="form-row">
     <label>Status</label>
     <select id="f-mstatus">{_opts(STATUSWERTE, "offen")}</select>
    </div>
    <div class="form-row">
     <label>Wiederholung</label>
     <select id="f-wdh"><option value="">keine</option>
      {"".join(f'<option value="{w}">{w}</option>' for w in WIEDERHOLUNGEN)}
     </select>
    </div>
    <div class="form-row">
     <label>Link</label>
     <input type="url" id="f-link" placeholder="https://…">
    </div>
    <div class="form-row full">
     <label>Notiz</label>
     <textarea id="f-notiz" placeholder="Optionale Details…"></textarea>
    </div>
   </div>
   <div class="modal-btns">
    <button type="button" class="btn btn-edit" onclick="closeModal()">Abbrechen</button>
    <button type="submit" class="btn btn-primary" id="modal-submit">Speichern</button>
   </div>
  </form>
 </div>
</div>

<script>
// ── View Toggle ────────────────────────────────────────────────────────────
function setView(v){{
  ['liste','kategorie','monat'].forEach(id=>{{
    document.getElementById('view-'+id).style.display = v===id ? 'block' : 'none';
    document.getElementById('btn-'+id).classList.toggle('active', v===id);
  }});
  localStorage.setItem('aufgaben-view', v);
}}
(function(){{
  const saved = localStorage.getItem('aufgaben-view');
  if(saved && saved !== '{view}') setView(saved);
}})();

// ── Collapsible Groups ─────────────────────────────────────────────────────
const COLLAPSED_KEY = 'aufgaben-collapsed';
function getCollapsed(){{ return JSON.parse(localStorage.getItem(COLLAPSED_KEY)||'{{}}'); }}
function saveCollapsed(c){{ localStorage.setItem(COLLAPSED_KEY, JSON.stringify(c)); }}

function toggleGroup(key){{
  const body = document.getElementById('gb-'+key);
  const hdr  = body?.previousElementSibling;
  if(!body) return;
  const isOpen = body.classList.contains('open');
  body.classList.toggle('open', !isOpen);
  hdr?.classList.toggle('open', !isOpen);
  const c = getCollapsed();
  if(isOpen) c[key] = true; else delete c[key];
  saveCollapsed(c);
}}

function initGroups(){{
  const c = getCollapsed();
  document.querySelectorAll('.group-section').forEach(sec=>{{
    const key  = sec.dataset.group;
    const body = document.getElementById('gb-'+key);
    const hdr  = body?.previousElementSibling;
    if(!body) return;
    const open = !c[key];  // Standard: aufgeklappt
    body.classList.toggle('open', open);
    hdr?.classList.toggle('open', open);
  }});
}}
initGroups();

// ── Filter ─────────────────────────────────────────────────────────────────
let _searchTimer=null;
function schedSearch(){{
  clearTimeout(_searchTimer);
  _searchTimer=setTimeout(applyFilter, 400);
}}
function applyFilter(){{
  const p = new URLSearchParams();
  const s=document.getElementById('f-status').value;
  const k=document.getElementById('f-kat').value;
  const pr=document.getElementById('f-prio').value;
  const t=document.getElementById('f-thema').value;
  const q=document.getElementById('f-q').value.trim();
  if(s)p.set('status',s); if(k)p.set('kat',k);
  if(pr)p.set('prio',pr); if(t)p.set('thema',t);
  if(q)p.set('q',q);
  window.location.search=p.toString();
}}

// ── Multi-Select ───────────────────────────────────────────────────────────
function selectedIds(){{
  return [...document.querySelectorAll('.row-chk:checked')].map(c=>+c.value);
}}
function onChk(){{
  const ids = selectedIds();
  const bar = document.getElementById('bulk-bar');
  bar.style.display = ids.length ? 'flex' : 'none';
  document.getElementById('bulk-count').textContent = ids.length + ' ausgewählt';
}}
function toggleAll(master){{
  document.querySelectorAll('#view-liste .row-chk').forEach(c=>c.checked=master.checked);
  onChk();
}}
function toggleGroupAll(master){{
  const tbody = master.closest('table').querySelector('tbody');
  tbody.querySelectorAll('.row-chk').forEach(c=>c.checked=master.checked);
  onChk();
}}
function clearSelection(){{
  document.querySelectorAll('.row-chk').forEach(c=>c.checked=false);
  const ca = document.getElementById('chk-all');
  if(ca) ca.checked=false;
  onChk();
}}
async function bulkApply(){{
  const ids = selectedIds();
  if(!ids.length) return;
  const body={{}};
  const t=document.getElementById('bulk-thema').value;
  const k=document.getElementById('bulk-kat').value;
  const p=document.getElementById('bulk-prio').value;
  const w=document.getElementById('bulk-wann').value;
  if(t) body.thema=t;
  if(k) body.kategorie=k;
  if(p) body.prioritaet=p;
  if(w) body.wann=w;
  if(!Object.keys(body).length){{ alert('Bitte mindestens ein Feld auswählen.'); return; }}
  await Promise.all(ids.map(id=>fetch('/api/aufgaben/'+id,{{
    method:'PUT', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(body)
  }})));
  location.reload();
}}
async function bulkDelete(){{
  const ids = selectedIds();
  if(!ids.length) return;
  if(!confirm(ids.length + ' Aufgabe(n) wirklich löschen?')) return;
  await Promise.all(ids.map(id=>fetch('/api/aufgaben/'+id,{{method:'DELETE'}})));
  location.reload();
}}
function openNew(){{
  document.getElementById('modal-title').textContent='Neue Aufgabe';
  document.getElementById('modal-submit').textContent='Anlegen';
  ['edit-id','f-was','f-wann','f-projekt','f-link','f-notiz'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('f-thema-m').value='';
  document.getElementById('f-kategorie').value='';
  document.getElementById('f-prioritaet').value='mittel';
  document.getElementById('f-mstatus').value='offen';
  document.getElementById('f-wdh').value='';
  document.getElementById('overlay').classList.add('open');
  document.getElementById('f-was').focus();
}}
async function openEdit(id){{
  const d=await(await fetch('/api/aufgaben/'+id)).json();
  document.getElementById('modal-title').textContent='Aufgabe bearbeiten';
  document.getElementById('modal-submit').textContent='Speichern';
  document.getElementById('edit-id').value=id;
  document.getElementById('f-was').value=d.was||'';
  document.getElementById('f-wann').value=d.wann||'';
  document.getElementById('f-thema-m').value=d.thema||'';
  document.getElementById('f-projekt').value=d.projekt||'';
  document.getElementById('f-kategorie').value=d.kategorie||'';
  document.getElementById('f-prioritaet').value=d.prioritaet||'mittel';
  document.getElementById('f-mstatus').value=d.status||'offen';
  document.getElementById('f-wdh').value=d.wiederholung||'';
  document.getElementById('f-link').value=d.link||'';
  document.getElementById('f-notiz').value=d.notiz||'';
  document.getElementById('overlay').classList.add('open');
  document.getElementById('f-was').focus();
}}
function closeModal(){{document.getElementById('overlay').classList.remove('open');}}
document.getElementById('overlay').addEventListener('click',e=>{{if(e.target===document.getElementById('overlay'))closeModal();}});
document.getElementById('modal-form').addEventListener('submit',async e=>{{
  e.preventDefault();
  const id=document.getElementById('edit-id').value;
  const body={{
    was:document.getElementById('f-was').value,
    wann:document.getElementById('f-wann').value||null,
    thema:document.getElementById('f-thema-m').value||null,
    projekt:document.getElementById('f-projekt').value||null,
    kategorie:document.getElementById('f-kategorie').value||null,
    prioritaet:document.getElementById('f-prioritaet').value,
    status:document.getElementById('f-mstatus').value,
    wiederholung:document.getElementById('f-wdh').value||null,
    link:document.getElementById('f-link').value||null,
    notiz:document.getElementById('f-notiz').value||null,
  }};
  const r=await fetch(id?'/api/aufgaben/'+id:'/api/aufgaben',
    {{method:id?'PUT':'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});
  if(r.ok)location.reload(); else alert('Fehler beim Speichern');
}});
async function del(id){{
  if(!confirm('Aufgabe wirklich löschen?'))return;
  const r=await fetch('/api/aufgaben/'+id,{{method:'DELETE'}});
  if(r.ok)document.querySelectorAll('[data-id="'+id+'"]').forEach(el=>el.remove());
  else alert('Fehler');
}}
async function markDone(id){{
  const r=await fetch('/api/aufgaben/'+id+'/done',{{method:'POST'}});
  if(r.ok)location.reload();
}}
document.addEventListener('keydown',e=>{{if(e.key==='Escape')closeModal();}});
</script></body></html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def index(request: Request, status: str = "", kat: str = "",
          prio: str = "", thema: str = "", q: str = ""):
    with get_db() as con:
        where, params = [], []
        if status: where.append("status=?");    params.append(status)
        if kat:    where.append("kategorie=?"); params.append(kat)
        if prio:   where.append("prioritaet=?");params.append(prio)
        if thema:  where.append("thema=?");     params.append(thema)
        if q:
            where.append("(was LIKE ? OR projekt LIKE ? OR notiz LIKE ? OR thema LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like, like, like])
        sql = "SELECT * FROM aufgaben"
        if where: sql += " WHERE " + " AND ".join(where)
        sql += (" ORDER BY CASE status WHEN 'erledigt' THEN 1 ELSE 0 END,"
                " CASE prioritaet WHEN 'hoch' THEN 0 WHEN 'mittel' THEN 1 ELSE 2 END,"
                " CASE WHEN wann IS NULL THEN 1 ELSE 0 END, wann")
        rows = con.execute(sql, params).fetchall()
    return HTMLResponse(build_page(rows, status, kat, prio, thema, q))


@app.get("/api/aufgaben")
def api_list(status: str = "", faellig: bool = False):
    with get_db() as con:
        if faellig:
            today = date.today().isoformat()
            rows = con.execute(
                "SELECT * FROM aufgaben WHERE status != 'erledigt'"
                " AND wann IS NOT NULL AND wann <= ?"
                " AND (reminded_at IS NULL OR reminded_at < ?)",
                (today, today),
            ).fetchall()
        elif status:
            rows = con.execute(
                "SELECT * FROM aufgaben WHERE status=? ORDER BY wann", (status,)
            ).fetchall()
        else:
            rows = con.execute("SELECT * FROM aufgaben ORDER BY wann").fetchall()
    return [dict(r) for r in rows]


@app.get("/api/aufgaben/{aufgabe_id}")
def api_get(aufgabe_id: int):
    with get_db() as con:
        row = con.execute("SELECT * FROM aufgaben WHERE id=?", (aufgabe_id,)).fetchone()
    if not row:
        return JSONResponse({"error": "nicht gefunden"}, status_code=404)
    return dict(row)


def _next_date(wann_str: str, wiederholung: str) -> str | None:
    """Berechnet das nächste Fälligkeitsdatum für Wiederholungen."""
    if not wann_str or not wiederholung:
        return None
    from dateutil.relativedelta import relativedelta
    try:
        d = date.fromisoformat(wann_str)
        today = date.today()
        delta = {"täglich": relativedelta(days=1), "wöchentlich": relativedelta(weeks=1),
                 "monatlich": relativedelta(months=1), "jährlich": relativedelta(years=1)}
        rd = delta.get(wiederholung)
        if not rd:
            return None
        next_d = d + rd
        while next_d <= today:
            next_d += rd
        return next_d.isoformat()
    except Exception:
        return None


@app.post("/api/aufgaben")
async def api_create(request: Request):
    body = await request.json()
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as con:
        cur = con.execute(
            "INSERT INTO aufgaben (was,wann,kategorie,thema,projekt,link,wiederholung,"
            "prioritaet,status,notiz,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (body.get("was"), body.get("wann"), body.get("kategorie"),
             body.get("thema"), body.get("projekt"), body.get("link"),
             body.get("wiederholung") or None,
             body.get("prioritaet","mittel"), body.get("status","offen"),
             body.get("notiz"), now, now),
        )
    return JSONResponse({"id": cur.lastrowid}, status_code=201)


@app.put("/api/aufgaben/{aufgabe_id}")
async def api_update(aufgabe_id: int, request: Request):
    body = await request.json()
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as con:
        row = con.execute("SELECT * FROM aufgaben WHERE id=?", (aufgabe_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "nicht gefunden"}, status_code=404)
        f = {**dict(row), **{k: v for k, v in body.items() if k not in ("id","created_at")}}
        con.execute(
            "UPDATE aufgaben SET was=?,wann=?,kategorie=?,thema=?,projekt=?,link=?,wiederholung=?,"
            "prioritaet=?,status=?,notiz=?,updated_at=? WHERE id=?",
            (f["was"],f["wann"],f["kategorie"],f.get("thema"),f.get("projekt"),
             f.get("link"),f.get("wiederholung"),
             f["prioritaet"],f["status"],f["notiz"],now,aufgabe_id),
        )
    return {"ok": True}


@app.post("/api/aufgaben/{aufgabe_id}/done")
async def api_done(aufgabe_id: int):
    """Markiert als erledigt. Bei Wiederholung: setzt Datum auf nächste Fälligkeit statt erledigt."""
    now = datetime.now().isoformat(timespec="seconds")
    with get_db() as con:
        row = con.execute("SELECT * FROM aufgaben WHERE id=?", (aufgabe_id,)).fetchone()
        if not row:
            return JSONResponse({"error": "nicht gefunden"}, status_code=404)
        r = dict(row)
        if r.get("wiederholung"):
            next_d = _next_date(r["wann"], r["wiederholung"])
            con.execute(
                "UPDATE aufgaben SET wann=?,status='offen',reminded_at=NULL,updated_at=? WHERE id=?",
                (next_d, now, aufgabe_id),
            )
            return {"ok": True, "action": "rescheduled", "next": next_d}
        else:
            con.execute(
                "UPDATE aufgaben SET status='erledigt',updated_at=? WHERE id=?",
                (now, aufgabe_id),
            )
            return {"ok": True, "action": "done"}


@app.delete("/api/aufgaben/{aufgabe_id}")
def api_delete(aufgabe_id: int):
    with get_db() as con:
        con.execute("DELETE FROM aufgaben WHERE id=?", (aufgabe_id,))
    return {"ok": True}


@app.post("/api/aufgaben/{aufgabe_id}/reminded")
def api_reminded(aufgabe_id: int):
    with get_db() as con:
        con.execute("UPDATE aufgaben SET reminded_at=? WHERE id=?",
                    (date.today().isoformat(), aufgabe_id))
    return {"ok": True}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8096)
