#!/usr/bin/env python3
"""Aufgaben-Verwaltung — Task Manager auf Port 8096.

Migriert auf die Ryzen-Hub-UI (UI-RICHTLINIE.md §11): Shell und
Komponenten kommen vom Hub (/ui/hub-ui.css, /ui/hub-ui.js), das
App-Styling liegt in static/aufgaben.css (relativ referenziert —
läuft über das Hub-<base> im Proxy UND direkt auf :8096).

Navigation: die KPI-Kacheln sind die einzige In-App-Navigation
(Aufgaben / Überfällig / Thema) — die frühere Ansichts-Umschaltung
(Liste/Thema/Monat) ist durch echte Seiten ersetzt. Das
Dialog-Muster (§7) und die Bulk-Aktionen bleiben erhalten.
Datenlogik und SQL sind unverändert.
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path
from html import escape

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

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

# Direktzugriff auf :8096 (über den Hub liefert der Hub /ui selbst aus).
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
app.mount("/ui", StaticFiles(directory="/home/reinhard/ryzen-hub/static/ui"), name="ui")


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


# ── Formate & Textbausteine (UI-RICHTLINIE §5, §7, §8) ────────────────────────

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
# Für Tabellenzellen ohne Emoji (Sortierung läuft über den Zelltext —
# „01 · Italien" sortiert chronologisch, ein Emoji davor nicht).
THEMA_KURZ = {k: v.split(" ", 1)[-1] for k, v in THEMA_LABELS.items()}
PRIO_LABELS = {"hoch": "▲ hoch", "mittel": "● mittel", "niedrig": "▽ niedrig"}
STATUS_KLASSEN = {"offen": "offen", "in-bearbeitung": "in-bearbeitung", "erledigt": "erledigt"}
WDH_ICONS = {"täglich": "↻d", "wöchentlich": "↻w", "monatlich": "↻m", "jährlich": "↻j"}


def t(val, default="–"):
    """„null"-Strings und None als leer (Hub-Konvention), HTML-escaped."""
    if val in (None, "null", "None"):
        return default
    return escape(str(val))


def _prio_badge(p):
    wert = (p or "mittel").strip().lower()
    if wert not in PRIO_LABELS:
        return f'<span class="badge badge-thema">{t(p)}</span>'
    return f'<span class="badge badge-prio-{wert}">{PRIO_LABELS[wert]}</span>'


def _status_badge(s):
    wert = (s or "offen").strip()
    schluessel = wert.lower().replace(" ", "-")
    if schluessel not in STATUS_KLASSEN:
        return f'<span class="badge badge-thema">{t(wert)}</span>'
    return f'<span class="badge badge-status-{schluessel}">{escape(wert)}</span>'


def _thema_badge(k):
    if not k:
        return ""
    return (f'<span class="badge badge-thema" title="{escape(str(k))}">'
            f'{escape(THEMA_KURZ.get(k, str(k)))}</span>')


def _wdh_badge(w):
    if not w:
        return ""
    return (f'<span class="badge badge-wdh" title="Wiederholt {escape(str(w))}">'
            f'{escape(WDH_ICONS.get(w, str(w)))}</span>')


def _wann_cell(wann):
    """Fälligkeit als DD.MM.YYYY; überfällig/heute mit Symbol + Text."""
    if not wann:
        return '<span class="mut">–</span>'
    try:
        d = date.fromisoformat(str(wann))
    except Exception:
        return t(wann)
    heute = date.today()
    fmt = d.strftime("%d.%m.%Y")
    if d < heute:
        return f'<span class="faellig">⚠ {fmt}</span>'
    if d == heute:
        return f'<span class="heute">● {fmt}</span>'
    return fmt


def _option(value, label, selected):
    sel = " selected" if selected else ""
    return f'<option value="{escape(str(value))}"{sel}>{escape(str(label))}</option>'


def _opts(options, selected, placeholder=None):
    html = f'<option value="">{escape(placeholder)}</option>' if placeholder else ""
    return html + "".join(_option(o, o, o == selected) for o in options)


def _seite(titel):
    """<head> nach UI-RICHTLINIE §3: FOUC-Script, /ui-Assets, relatives App-CSS.

    Keine eigene Kopfzeile und keine Navigation — die Shell injiziert der
    Hub, die Navigation sind die KPI-Kacheln (§7)."""
    return (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(titel)}</title>'
        "<script>try{var t=localStorage.getItem('hub-theme');"
        "if(t)document.documentElement.setAttribute('data-theme',t)}catch(e){}</script>"
        '<link rel="stylesheet" href="/ui/hub-ui.css">'
        '<link rel="stylesheet" href="static/aufgaben.css">'
        '<script src="/ui/hub-ui.js" defer></script>'
        '</head><body class="hub-ui"><div class="container">'
        '<div class="alert alert-error" id="seiten-fehler" role="alert" hidden></div>'
    )


def _seite_ende():
    return '</div></body></html>'


# ── KPI-Kacheln = Navigation (UI-RICHTLINIE §7) ───────────────────────────────

def _kachel(icon, name, value, label, href):
    return (
        f'<a class="widget" href="{href}"><div class="widget-top">'
        f'<span class="widget-icon">{icon}</span></div>'
        f'<div class="widget-name">{name}</div>'
        f'<div class="widget-kpi"><span class="kpi-value">{value}</span>'
        f'<span class="kpi-label">{label}</span></div>'
        f'<div class="widget-fuss"><span class="widget-ms"></span>'
        f'<span class="widget-pfeil" aria-hidden="true">›</span></div></a>'
    )


def kpi_counts(con):
    """Die KPI-Werte der Kachel-Zeile — ungefiltert, auf jeder Seite identisch."""
    heute = date.today().isoformat()
    return {
        "gesamt": con.execute("SELECT COUNT(*) FROM aufgaben").fetchone()[0],
        "offen": con.execute(
            "SELECT COUNT(*) FROM aufgaben "
            "WHERE COALESCE(status,'offen') != 'erledigt'").fetchone()[0],
        "ueberfaellig": con.execute(
            "SELECT COUNT(*) FROM aufgaben "
            "WHERE COALESCE(status,'offen') != 'erledigt'"
            "  AND wann IS NOT NULL AND wann < ?", (heute,)).fetchone()[0],
        "themen": con.execute(
            "SELECT COUNT(DISTINCT thema) FROM aufgaben "
            "WHERE thema IS NOT NULL AND TRIM(thema) != ''").fetchone()[0],
    }


def _kacheln(aktiv, counts):
    """Kachel-Zeile auf JEDER Seite; aktive Kachel nicht klickbar (§7).

    Die Start-Kachel verlinkt auf „./" — ein href="/" führte über den
    Hub-Proxy zum Hub selbst (AP210)."""
    tiles = [
        ("aufgaben", "📋", "Aufgaben", f'{counts["offen"]}/{counts["gesamt"]}',
         "offen / gesamt", "./"),
        ("faellig", "⏰", "Überfällig", str(counts["ueberfaellig"]),
         "Aufgaben", "/faellig"),
        ("thema", "🗂️", "Thema", str(counts["themen"]), "Themen", "/thema"),
    ]
    h = ['<nav class="widgets" aria-label="Bereiche">']
    for key, icon, name, value, label, href in tiles:
        if key == aktiv:
            h.append(f'<div class="widget widget-aktiv"><div class="widget-top">'
                     f'<span class="widget-icon">{icon}</span></div>'
                     f'<div class="widget-name">{name}</div>'
                     f'<div class="widget-kpi"><span class="kpi-value">{value}</span>'
                     f'<span class="kpi-label">{label}</span></div>'
                     f'<div class="widget-fuss"><span class="widget-ms"></span>'
                     f'<span class="widget-pfeil" aria-hidden="true">›</span></div></div>')
        else:
            h.append(_kachel(icon, name, value, label, href))
    h.append('</nav>')
    return "".join(h)


# ── Liste, Filter, Zeilen ─────────────────────────────────────────────────────

def _hole_aufgaben(con, status, kat, prio, thema, q):
    """Aufgabenliste mit den Filtern der Altfassung (SQL unverändert)."""
    where, params = [], []
    if status: where.append("status=?");     params.append(status)
    if kat:    where.append("kategorie=?");  params.append(kat)
    if prio:   where.append("prioritaet=?"); params.append(prio)
    if thema:  where.append("thema=?");      params.append(thema)
    if q:
        where.append("(was LIKE ? OR projekt LIKE ? OR notiz LIKE ? OR thema LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like, like])
    sql = "SELECT * FROM aufgaben"
    if where: sql += " WHERE " + " AND ".join(where)
    sql += (" ORDER BY CASE status WHEN 'erledigt' THEN 1 ELSE 0 END,"
            " CASE prioritaet WHEN 'hoch' THEN 0 WHEN 'mittel' THEN 1 ELSE 2 END,"
            " CASE WHEN wann IS NULL THEN 1 ELSE 0 END, wann")
    return con.execute(sql, params).fetchall()


def _ist_erledigt(r):
    return (r["status"] or "offen").strip().lower() == "erledigt"


def _ist_ueberfaellig(r, heute):
    return (not _ist_erledigt(r)) and r["wann"] and str(r["wann"]) < heute


def _toolbar(pfad, fs, fk, fp, ft, fq, anzahl, ueberfaellig):
    """Server-Filter (§7) — wird von hub-ui.js mit dem Suchfeld zu
    .liste-kopf verbunden; deshalb direkt vor .hub-table-wrap rendern."""
    h = ['<form class="toolbar" method="get">']
    h.append(f'<select name="status" aria-label="Status">'
             f'{_opts(STATUSWERTE, fs, "Alle Status")}</select>')
    h.append(f'<select name="thema" aria-label="Thema">'
             f'{_opts(THEMEN, ft, "Alle Themen")}</select>')
    h.append(f'<select name="kat" aria-label="Kategorie">'
             f'{_opts(KATEGORIEN, fk, "Alle Kategorien")}</select>')
    h.append(f'<select name="prio" aria-label="Priorität">'
             f'{_opts(PRIORITAETEN, fp, "Alle Prioritäten")}</select>')
    h.append('<button type="submit" class="btn">Filtern</button>')
    if fs or fk or fp or ft or fq:
        h.append(f'<a class="btn" href="{pfad}">✕ Zurücksetzen</a>')
    h.append(f'<span class="toolbar-count">{anzahl} Aufgaben</span>')
    if ueberfaellig:
        h.append(f'<span class="badge badge-down">⚠ {ueberfaellig} überfällig</span>')
    h.append('</form>')
    return "".join(h)


def _zeile(r, mit_thema):
    rid = r["id"]
    erledigt = _ist_erledigt(r)
    kls = ' class="zeile-erledigt"' if erledigt else ""
    h = [f'<tr{kls} data-id="{rid}">']
    h.append('<td class="spalte-chk"><label class="chk-treffer">'
             f'<input type="checkbox" class="row-chk" value="{rid}" '
             'aria-label="Aufgabe auswählen" onchange="onChk()"></label></td>')
    if mit_thema:
        h.append(f'<td>{_thema_badge(r["thema"]) or t(None)}</td>')
    notiz = t(r["notiz"], "")
    teile = []
    if r["wiederholung"]:
        teile.append(_wdh_badge(r["wiederholung"]))
    if not mit_thema and r["thema"]:
        teile.append(_thema_badge(r["thema"]))
    teile.append(f'<span>{t(r["was"], "")}</span>')
    if notiz:
        teile.append('<span title="Notiz vorhanden">📝</span>')
    if r["link"]:
        teile.append(f'<a class="ext-link" href="{escape(str(r["link"]))}"'
                     f' target="_blank" rel="noopener" aria-label="Externer Link">↗</a>')
    zelle = " ".join(teile)
    projekt = t(r["projekt"], "")
    if projekt:
        zelle += f'<div class="projekt">{projekt}</div>'
    h.append(f'<td title="{notiz}">{zelle}</td>' if notiz else f'<td>{zelle}</td>')
    h.append(f'<td>{_wann_cell(r["wann"])}</td>')
    h.append(f'<td class="mut">{t(r["kategorie"])}</td>')
    h.append(f'<td>{_prio_badge(r["prioritaet"])}</td>')
    h.append(f'<td>{_status_badge(r["status"])}</td>')
    h.append('<td><div class="aktionen">')
    if not erledigt:
        h.append(f'<button type="button" class="btn btn-sm btn-ok" onclick="markDone({rid})"'
                 f' aria-label="Als erledigt markieren" title="Erledigt">✓</button>')
    h.append(f'<button type="button" class="btn btn-sm" onclick="openEdit({rid})"'
             f' aria-label="Bearbeiten" title="Bearbeiten">✏</button>')
    h.append(f'<button type="button" class="btn btn-sm btn-del" onclick="del({rid})"'
             f' aria-label="Löschen" title="Löschen">🗑</button>')
    h.append('</div></td></tr>')
    return "".join(h)


def _tabelle(rows, mit_thema):
    """Eine HubTable je Seite: sortierbar, clientseitig filterbar (§7)."""
    if not rows:
        return ('<div class="empty-state">'
                '<div class="empty-state-icon">🗒️</div>'
                '<div class="empty-state-title">Keine Aufgaben</div>'
                '<div class="empty-state-text">Für diese Auswahl gibt es keine '
                'Aufgaben. Filter zurücksetzen oder eine neue Aufgabe anlegen.'
                '</div></div>')
    h = ['<div class="hub-table-wrap"><table class="hub-table" data-sort data-filter="Suchen…">']
    h.append('<thead><tr>')
    h.append('<th class="spalte-chk"><label class="chk-treffer">'
             '<input type="checkbox" id="chk-all" onchange="toggleAll(this)"'
             ' aria-label="Alle auswählen" title="Alle auswählen"></label></th>')
    if mit_thema:
        h.append('<th data-sort data-sort-erste="1">Thema</th>')
        h.append('<th data-sort>Was / Projekt</th>')
    else:
        h.append('<th data-sort data-sort-erste="1">Was / Thema / Projekt</th>')
    h.append('<th data-sort data-sort-typ="datum">Fällig</th>')
    h.append('<th data-sort>Kategorie</th>')
    h.append('<th data-sort>Priorität</th>')
    h.append('<th data-sort>Status</th>')
    h.append('<th></th></tr></thead><tbody>')
    h.extend(_zeile(r, mit_thema) for r in rows)
    h.append('</tbody></table></div>')
    return "".join(h)


# ── Bulk-Aktionen und Dialog (§7) ─────────────────────────────────────────────

def _bulk_bar():
    return (
        '<div class="bulk-bar" id="bulk-bar">'
        '<span class="bulk-anzahl" id="bulk-count"></span>'
        '<select id="bulk-thema" aria-label="Thema ändern">'
        f'<option value="">Thema ändern…</option>{_opts(THEMEN, None)}</select>'
        '<select id="bulk-kat" aria-label="Kategorie ändern">'
        f'<option value="">Kategorie ändern…</option>{_opts(KATEGORIEN, None)}</select>'
        '<select id="bulk-prio" aria-label="Priorität ändern">'
        f'<option value="">Priorität ändern…</option>{_opts(PRIORITAETEN, None)}</select>'
        '<input type="date" id="bulk-wann" aria-label="Fälligkeit setzen"'
        ' title="Datum für alle setzen">'
        '<button type="button" class="btn btn-sm btn-primary" onclick="bulkApply()">Anwenden</button>'
        '<button type="button" class="btn btn-sm btn-del" onclick="bulkDelete()">🗑 Löschen</button>'
        '<button type="button" class="btn btn-sm" onclick="clearSelection()">✕ Abwählen</button>'
        '</div>'
    )


def _modal():
    return (
        '<div class="overlay" id="overlay">'
        '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">'
        '<h2 id="modal-title">Neue Aufgabe</h2>'
        '<form id="modal-form">'
        '<input type="hidden" id="edit-id">'
        '<div class="form-grid">'
        '<div class="form-row full"><label for="f-was">Was? *</label>'
        '<input type="text" id="f-was" required placeholder="Aufgabe…"></div>'
        '<div class="form-row"><label for="f-thema-m">Thema</label>'
        f'<select id="f-thema-m">{_opts(THEMEN, None, "– wählen –")}</select></div>'
        '<div class="form-row"><label for="f-projekt">Projekt</label>'
        '<input type="text" id="f-projekt" placeholder="Projekt…"></div>'
        '<div class="form-row"><label for="f-wann">Wann?</label>'
        '<input type="date" id="f-wann"></div>'
        '<div class="form-row"><label for="f-kategorie">Kategorie</label>'
        f'<select id="f-kategorie">{_opts(KATEGORIEN, None, "– wählen –")}</select></div>'
        '<div class="form-row"><label for="f-prioritaet">Priorität</label>'
        f'<select id="f-prioritaet">{_opts(PRIORITAETEN, "mittel")}</select></div>'
        '<div class="form-row"><label for="f-mstatus">Status</label>'
        f'<select id="f-mstatus">{_opts(STATUSWERTE, "offen")}</select></div>'
        '<div class="form-row"><label for="f-wdh">Wiederholung</label>'
        f'<select id="f-wdh"><option value="">keine</option>{_opts(WIEDERHOLUNGEN, None)}</select></div>'
        '<div class="form-row"><label for="f-link">Link</label>'
        '<input type="url" id="f-link" placeholder="https://…"></div>'
        '<div class="form-row full"><label for="f-notiz">Notiz</label>'
        '<textarea id="f-notiz" placeholder="Optionale Details…"></textarea></div>'
        '</div>'
        '<div class="form-fehler" id="modal-fehler" role="alert"></div>'
        '<div class="modal-btns">'
        '<button type="button" class="btn" onclick="closeModal()">Abbrechen</button>'
        '<button type="submit" class="btn btn-primary" id="modal-submit">Speichern</button>'
        '</div></form></div></div>'
        '<div class="overlay" id="confirm-overlay">'
        '<div class="modal" role="dialog" aria-modal="true" aria-labelledby="confirm-titel">'
        '<h2 id="confirm-titel">Aufgabe löschen?</h2>'
        '<p id="confirm-text"></p>'
        '<div class="modal-btns">'
        '<button type="button" class="btn" onclick="closeConfirm()">Abbrechen</button>'
        '<button type="button" class="btn btn-danger" id="confirm-ok" onclick="confirmOk()">Löschen</button>'
        '</div></div></div>'
    )


# ── JavaScript (Dialog-Muster §7, Bulk-Aktionen, Zeilen-Aktionen) ─────────────
# Kein Server-Wert interpoliert — deshalb ein einfacher String (keine f-Strings).

JS = """
<script>
// ── Seiten-Fehler (Alert am Seitenanfang) ──────────────────────────────────
function seitenFehler(text){
  const el = document.getElementById('seiten-fehler');
  if(!el) return;
  el.textContent = text || '';
  el.hidden = !text;
}

// ── Dialoge (§7: Overlay + Karte, Esc schließt, Klick aufs Overlay schließt) ──
function openOverlay(id){ document.getElementById(id).classList.add('open'); }
function closeOverlay(id){ document.getElementById(id).classList.remove('open'); }

function modalFehler(text){
  const el = document.getElementById('modal-fehler');
  el.textContent = text || '';
  el.classList.toggle('sichtbar', !!text);
}
function closeModal(){ closeOverlay('overlay'); modalFehler(''); }

// Bestätigung im eigenen Dialog statt window.confirm
// (Buttons „Löschen"/„Abbrechen" — nie „OK", §7).
let _bestaetigung = null;
function askConfirm(titel, text, fn){
  document.getElementById('confirm-titel').textContent = titel;
  document.getElementById('confirm-text').textContent = text;
  _bestaetigung = fn;
  openOverlay('confirm-overlay');
  document.getElementById('confirm-ok').focus();
}
function closeConfirm(){ closeOverlay('confirm-overlay'); _bestaetigung = null; }
function confirmOk(){ const f = _bestaetigung; closeConfirm(); if(f) f(); }

document.addEventListener('keydown', e => {
  if(e.key !== 'Escape') return;
  if(document.getElementById('confirm-overlay').classList.contains('open')) closeConfirm();
  else closeModal();
});
document.getElementById('overlay').addEventListener('click', e => {
  if(e.target === document.getElementById('overlay')) closeModal();
});
document.getElementById('confirm-overlay').addEventListener('click', e => {
  if(e.target === document.getElementById('confirm-overlay')) closeConfirm();
});

// ── Mehrfachauswahl + Bulk-Aktionen ────────────────────────────────────────
function selectedIds(){
  return [...document.querySelectorAll('.row-chk:checked')].map(c => +c.value);
}
function onChk(){
  const ids = selectedIds();
  document.getElementById('bulk-bar').classList.toggle('sichtbar', ids.length > 0);
  document.getElementById('bulk-count').textContent = ids.length + ' ausgewählt';
}
function toggleAll(master){
  document.querySelectorAll('.row-chk').forEach(c => c.checked = master.checked);
  onChk();
}
function clearSelection(){
  document.querySelectorAll('.row-chk').forEach(c => c.checked = false);
  const ca = document.getElementById('chk-all');
  if(ca) ca.checked = false;
  onChk();
}
async function bulkApply(){
  const ids = selectedIds();
  if(!ids.length) return;
  const body = {};
  const t = document.getElementById('bulk-thema').value;
  const k = document.getElementById('bulk-kat').value;
  const p = document.getElementById('bulk-prio').value;
  const w = document.getElementById('bulk-wann').value;
  if(t) body.thema = t;
  if(k) body.kategorie = k;
  if(p) body.prioritaet = p;
  if(w) body.wann = w;
  if(!Object.keys(body).length){ seitenFehler('Bitte mindestens ein Feld auswählen.'); return; }
  const rs = await Promise.all(ids.map(id => fetch('/api/aufgaben/' + id, {
    method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
  })));
  if(rs.every(r => r.ok)) location.reload();
  else seitenFehler('Nicht alle Aufgaben konnten geändert werden.');
}
function bulkDelete(){
  const ids = selectedIds();
  if(!ids.length) return;
  askConfirm('Aufgaben löschen?', ids.length + ' Aufgabe(n) werden endgültig entfernt.', async () => {
    const rs = await Promise.all(ids.map(id => fetch('/api/aufgaben/' + id, {method:'DELETE'})));
    if(rs.every(r => r.ok)) location.reload();
    else seitenFehler('Nicht alle Aufgaben konnten gelöscht werden.');
  });
}

// ── Anlegen / Bearbeiten ───────────────────────────────────────────────────
function openNew(){
  document.getElementById('modal-title').textContent = 'Neue Aufgabe';
  ['edit-id','f-was','f-wann','f-projekt','f-link','f-notiz'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('f-thema-m').value = '';
  document.getElementById('f-kategorie').value = '';
  document.getElementById('f-prioritaet').value = 'mittel';
  document.getElementById('f-mstatus').value = 'offen';
  document.getElementById('f-wdh').value = '';
  modalFehler('');
  openOverlay('overlay');
  document.getElementById('f-was').focus();
}
async function openEdit(id){
  const d = await (await fetch('/api/aufgaben/' + id)).json();
  document.getElementById('modal-title').textContent = 'Aufgabe bearbeiten';
  document.getElementById('edit-id').value = id;
  document.getElementById('f-was').value = d.was || '';
  document.getElementById('f-wann').value = d.wann || '';
  document.getElementById('f-thema-m').value = d.thema || '';
  document.getElementById('f-projekt').value = d.projekt || '';
  document.getElementById('f-kategorie').value = d.kategorie || '';
  document.getElementById('f-prioritaet').value = d.prioritaet || 'mittel';
  document.getElementById('f-mstatus').value = d.status || 'offen';
  document.getElementById('f-wdh').value = d.wiederholung || '';
  document.getElementById('f-link').value = d.link || '';
  document.getElementById('f-notiz').value = d.notiz || '';
  modalFehler('');
  openOverlay('overlay');
  document.getElementById('f-was').focus();
}
document.getElementById('modal-form').addEventListener('submit', async e => {
  e.preventDefault();
  const id = document.getElementById('edit-id').value;
  const body = {
    was:document.getElementById('f-was').value,
    wann:document.getElementById('f-wann').value || null,
    thema:document.getElementById('f-thema-m').value || null,
    projekt:document.getElementById('f-projekt').value || null,
    kategorie:document.getElementById('f-kategorie').value || null,
    prioritaet:document.getElementById('f-prioritaet').value,
    status:document.getElementById('f-mstatus').value,
    wiederholung:document.getElementById('f-wdh').value || null,
    link:document.getElementById('f-link').value || null,
    notiz:document.getElementById('f-notiz').value || null,
  };
  const r = await fetch(id ? '/api/aufgaben/' + id : '/api/aufgaben', {
    method: id ? 'PUT' : 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify(body)
  });
  if(r.ok) location.reload();
  else modalFehler('Speichern fehlgeschlagen — bitte erneut versuchen.');
});

// ── Zeilen-Aktionen ────────────────────────────────────────────────────────
function del(id){
  askConfirm('Aufgabe löschen?', 'Die Aufgabe wird endgültig entfernt.', async () => {
    const r = await fetch('/api/aufgaben/' + id, {method:'DELETE'});
    if(r.ok) document.querySelectorAll('[data-id="' + id + '"]').forEach(el => el.remove());
    else seitenFehler('Löschen fehlgeschlagen.');
  });
}
async function markDone(id){
  const r = await fetch('/api/aufgaben/' + id + '/done', {method:'POST'});
  if(r.ok) location.reload();
  else seitenFehler('Aufgabe konnte nicht als erledigt markiert werden.');
}
</script>
"""


# ── Seiten ────────────────────────────────────────────────────────────────────

def _liste_html(rows, kpis, aktiv, titel, pfad, fs, fk, fp, ft, fq, mit_thema):
    heute = date.today().isoformat()
    ueberfaellig = sum(1 for r in rows if _ist_ueberfaellig(r, heute))
    seitentitel = "Aufgaben" if aktiv == "aufgaben" else f"Aufgaben – {titel}"
    h = [_seite(seitentitel), _kacheln(aktiv, kpis)]
    h.append('<div class="seite-kopf">')
    h.append(f'<div class="section-header">{escape(titel)}</div>')
    h.append('<button type="button" class="btn btn-primary" onclick="openNew()">'
             '＋ Neue Aufgabe</button>')
    h.append('</div>')
    h.append(_bulk_bar())
    h.append(_toolbar(pfad, fs, fk, fp, ft, fq, len(rows), ueberfaellig))
    h.append(_tabelle(rows, mit_thema))
    h.append(_modal())
    h.append(JS)
    h.append(_seite_ende())
    return "".join(h)


@app.get("/", response_class=HTMLResponse)
def index(request: Request, status: str = "", kat: str = "",
          prio: str = "", thema: str = "", q: str = ""):
    with get_db() as con:
        rows = _hole_aufgaben(con, status, kat, prio, thema, q)
        kpis = kpi_counts(con)
    return HTMLResponse(_liste_html(rows, kpis, "aufgaben", "Aufgaben", "./",
                                    status, kat, prio, thema, q, mit_thema=False))


@app.get("/faellig", response_class=HTMLResponse)
def faellig(request: Request, status: str = "", kat: str = "",
            prio: str = "", thema: str = "", q: str = ""):
    """Überfällige Aufgaben — dieselbe Abfrage, Auswahl im Seitenaufbau."""
    with get_db() as con:
        rows = _hole_aufgaben(con, status, kat, prio, thema, q)
        kpis = kpi_counts(con)
    heute = date.today().isoformat()
    rows = [r for r in rows if _ist_ueberfaellig(r, heute)]
    return HTMLResponse(_liste_html(rows, kpis, "faellig", "Überfällig", "/faellig",
                                    status, kat, prio, thema, q, mit_thema=False))


@app.get("/thema", response_class=HTMLResponse)
def thema(request: Request, status: str = "", kat: str = "",
          prio: str = "", thema: str = "", q: str = ""):
    """Aufgaben nach Thema — eine HubTable, vorsortiert auf der Thema-Spalte."""
    with get_db() as con:
        rows = _hole_aufgaben(con, status, kat, prio, thema, q)
        kpis = kpi_counts(con)
    return HTMLResponse(_liste_html(rows, kpis, "thema", "Nach Thema", "/thema",
                                    status, kat, prio, thema, q, mit_thema=True))


@app.get("/health")
def health():
    return {"status": "ok"}


# ── API (unverändert) ─────────────────────────────────────────────────────────

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
    uvicorn.run(app, host="127.0.0.1", port=8096)
