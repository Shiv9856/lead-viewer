#!/usr/bin/env python3
"""
Generate the Lead Journey Viewer HTML from a Spinny call_history CSV.

Usage:
    python generate_viewer_fixed.py <input_csv> [output_html]

Examples:
    python generate_viewer_fixed.py call_history.csv
    python generate_viewer_fixed.py call_history.csv viewer.html

Requires: pandas  (install with: pip install pandas)
"""
import sys
import os
import json
import ast
import re
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("ERROR: pandas is not installed. Run: pip install pandas")
    sys.exit(1)


# Calls are considered "connected" if the hangup reason is one of these
CONNECTED_HANGUPS = {"CLIENT_INITIATED", "PARTICIPANT_REMOVED"}

# Max transcript length before truncation
MAX_TRANSCRIPT_CHARS = 10000


# =============================================================================
# DATA EXTRACTION
# =============================================================================

def _clean(v):
    """Return a JSON-friendly Python value or None."""
    if pd.isna(v):
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _parse_summary(raw):
    if pd.isna(raw) or not str(raw).strip():
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            parsed = parser(raw)
            if isinstance(parsed, list) and parsed:
                return parsed[0]
            return parsed
        except Exception:
            continue
    return None


_SSML_TAG = re.compile(r"<break[^>]*/?>")


def _clean_transcript(text):
    if not text:
        return ""
    text = _SSML_TAG.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+(Assistant|User):\s*", r"\n\1: ", text)
    return text.strip()


def build_leads_data(df: pd.DataFrame) -> list:
    leads: dict[str, dict] = {}

    for _, row in df.iterrows():
        lid = str(_clean(row["buylead"]))
        if lid in ("None", "nan", ""):
            continue

        pre = {
            "city":          _clean(row.get("city")) or _clean(row.get("updated_city")) or "",
            "intent":        _clean(row.get("preferences.customer_intent")) or "",
            "body_type":     _clean(row.get("preferences.customer_filter_data.body_type")) or "",
            "fuel":          _clean(row.get("preferences.customer_filter_data.fuel_type")) or "",
            "transmission":  _clean(row.get("preferences.customer_filter_data.transmission")) or "",
            "min_price":     _clean(row.get("preferences.customer_filter_data.min_price")),
            "max_price":     _clean(row.get("preferences.customer_filter_data.max_price")),
            "make_pref":     _clean(row.get("preferences.customer_filter_data.make")) or "",
            "crm_milestone": _clean(row.get("milestone_data.milestone.display_name")) or "",
            "crm_status":    _clean(row.get("milestone_data.status.description")) or "",
        }

        if lid not in leads:
            leads[lid] = {"id": lid, "pre": pre, "interested_cars": [], "calls": []}

        hangup = _clean(row.get("Hangup Reason")) or ""
        duration = _clean(row.get("Call Duration"))
        summary = _parse_summary(row.get("summary"))

        call = {
            "date":           _clean(row.get("Call Date")) or "",
            "time":           _clean(row.get("Call Time")) or "",
            "duration":       round(duration, 1) if isinstance(duration, (int, float)) else None,
            "recording":      _clean(row.get("Call Recording")) or "",
            "transcript":     _clean_transcript(_clean(row.get("Call Transcript"))),
            "hangup":         hangup,
            "connected":      hangup in CONNECTED_HANGUPS,
            "scenario":       _clean(row.get("added_scenario")) or "",
            "mark_dnd":       bool(row.get("Mark_DND")) if not pd.isna(row.get("Mark_DND")) else False,
            "handoff":        bool(row.get("human_handoff")) if not pd.isna(row.get("human_handoff")) else False,
            "handoff_reason": _clean(row.get("human_handoff_reason")) or "",
            "ndoa":           _clean(row.get("ndoa")) or "",
            "milestone":      _clean(row.get("milestone")) or "",
        }
        if summary:
            call.update({
                "disposition":      summary.get("disposition", "") or "",
                "pitched_cars":     summary.get("pitched_car_ids", "") or "",
                "rejected_cars":    summary.get("rejected_car_ids", "") or "",
                "rejected_reasons": summary.get("rejected_reasons", "") or "",
                "liked_cars":       summary.get("liked_cars_id", "") or "",
                "budget":           summary.get("budget", "") or "",
            })

        t = call["transcript"]
        if len(t) > MAX_TRANSCRIPT_CHARS:
            call["transcript"] = (
                t[:MAX_TRANSCRIPT_CHARS]
                + f"\n\n[… transcript truncated, {len(t) - MAX_TRANSCRIPT_CHARS} more chars]"
            )

        leads[lid]["calls"].append(call)
        leads[lid]["pre"] = pre

    for lead in leads.values():
        lead["calls"].sort(key=lambda c: c.get("time") or c.get("date") or "")

    return list(leads.values())


# =============================================================================
# HTML TEMPLATE (FIXED)
# =============================================================================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Lead Journey Viewer</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #FAF8F5; --surface: #FFFFFF; --surface-2: #F3EFE8;
    --border: #E8E4DC; --border-strong: #D4CEC1;
    --text: #1A1814; --text-muted: #6B6458; --text-faint: #9E9688;
    --accent: #C4633F; --accent-soft: #F4E4D9;
    --success: #4A7C59; --success-soft: #DCE8DE;
    --warning: #B8823D; --warning-soft: #F2E4CC;
    --info: #3F6B9C; --info-soft: #DDE6F0;
    --danger: #9C3F3F; --danger-soft: #F0DDDD;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; }
  body { font-family: 'IBM Plex Sans', sans-serif; background: var(--bg); color: var(--text); font-size: 14px; line-height: 1.5; overflow: hidden; }
  code, .mono { font-family: 'IBM Plex Mono', monospace; }
  .app { display: flex; flex-direction: column; height: 100vh; }
  header { padding: 12px 24px; background: var(--surface); border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 16px; flex-shrink: 0; flex-wrap: wrap; }
  .brand { font-family: 'Instrument Serif', serif; font-weight: 400; font-style: italic; font-size: 22px; white-space: nowrap; }
  .search-box { flex: 1; max-width: 420px; min-width: 200px; position: relative; }
  .search-box input { width: 100%; padding: 9px 14px 9px 36px; border: 1px solid var(--border-strong); background: var(--bg); border-radius: 4px; font-family: inherit; font-size: 13px; color: var(--text); outline: none; transition: border-color 0.15s; }
  .search-box input:focus { border-color: var(--accent); }
  .search-box::before { content: ''; position: absolute; left: 12px; top: 50%; width: 14px; height: 14px; transform: translateY(-50%); background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236B6458' stroke-width='2'><circle cx='11' cy='11' r='7'/><path d='m21 21-4.3-4.3'/></svg>"); background-size: contain; }
  .filters { display: flex; gap: 6px; flex-wrap: wrap; }
  .fchip { padding: 5px 11px; border: 1px solid var(--border-strong); background: transparent; color: var(--text-muted); border-radius: 20px; cursor: pointer; font-family: inherit; font-size: 12px; transition: all 0.1s; white-space: nowrap; }
  .fchip:hover { border-color: var(--text-muted); color: var(--text); }
  .fchip.active { background: var(--text); color: var(--bg); border-color: var(--text); }
  .fchip.active-success { background: var(--success); color: #fff; border-color: var(--success); }
  .fchip.active-warning { background: var(--warning); color: #fff; border-color: var(--warning); }
  .date-filter { display: flex; align-items: center; gap: 6px; }
  .sort-control { display: flex; align-items: center; gap: 6px; }
  .header-stats { display: flex; gap: 14px; margin-left: auto; }
  .hstat { text-align: right; }
  .hstat-val { font-family: 'IBM Plex Mono', monospace; font-weight: 500; font-size: 15px; }
  .hstat-label { font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.08em; }
  main { flex: 1; display: flex; overflow: hidden; }
  .sidebar { width: 340px; min-width: 340px; border-right: 1px solid var(--border); background: var(--surface); overflow-y: auto; }
  .sh { padding: 10px 20px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--surface); z-index: 1; }
  .li { padding: 12px 20px; border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.08s; position: relative; }
  .li:hover { background: var(--surface-2); }
  .li.active { background: var(--accent-soft); }
  .li.active::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); }
  .ltop { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
  .lid { font-family: 'IBM Plex Mono', monospace; font-size: 13px; font-weight: 500; }
  .ct-row { display: flex; gap: 4px; margin-left: auto; }
  .ct { padding: 1px 7px; background: var(--surface-2); border-radius: 10px; font-size: 11px; font-family: 'IBM Plex Mono', monospace; color: var(--text-muted); }
  .ct.conn { background: var(--success-soft); color: var(--success); }
  .ct.nc { background: var(--surface-2); color: var(--text-faint); }
  .li.active .ct { background: var(--surface); }
  .li.active .ct.conn { background: var(--success-soft); }
  .lmeta { font-size: 12px; color: var(--text-muted); display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
  .detail { flex: 1; overflow-y: auto; background: var(--bg); }
  .dempty { height: 100%; display: flex; align-items: center; justify-content: center; color: var(--text-faint); font-family: 'Instrument Serif', serif; font-style: italic; font-size: 22px; }
  .di { padding: 28px 40px; max-width: 980px; }
  .dh { margin-bottom: 20px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
  .dt { font-family: 'Instrument Serif', serif; font-weight: 400; font-size: 38px; line-height: 1.1; }
  .ds { color: var(--text-muted); font-size: 13px; display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin-top: 8px; }
  .ds .sep { color: var(--text-faint); }
  .ds .mono { font-family: 'IBM Plex Mono', monospace; }
  .pre-block { background: var(--surface); border: 1px solid var(--border); border-radius: 4px; padding: 16px 18px; margin-bottom: 20px; }
  .pre-label { font-family: 'Instrument Serif', serif; font-style: italic; font-size: 14px; color: var(--text-muted); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
  .pre-label::before { content: ''; width: 4px; height: 4px; background: var(--accent); border-radius: 50%; }
  .fg { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px 22px; }
  .fl { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); margin-bottom: 2px; }
  .fv { font-size: 13px; color: var(--text); word-break: break-word; }
  .fv.mono { font-family: 'IBM Plex Mono', monospace; font-size: 12px; }
  .cars { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .car { padding: 5px 10px; background: var(--surface-2); border-radius: 3px; font-size: 12px; }
  .car b { font-weight: 500; }
  .car .meta { color: var(--text-muted); margin-left: 4px; }
  .section-hdr { display: flex; align-items: baseline; justify-content: space-between; margin: 24px 0 14px; }
  .sec-title { font-family: 'Instrument Serif', serif; font-style: italic; font-size: 22px; }
  .sec-sub { font-size: 12px; color: var(--text-muted); }
  .tl { position: relative; padding-left: 24px; }
  .tl::before { content: ''; position: absolute; left: 6px; top: 8px; bottom: 8px; width: 1px; background: var(--border-strong); }
  .call { position: relative; background: var(--surface); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 10px; }
  .call::before { content: ''; position: absolute; left: -22px; top: 18px; width: 9px; height: 9px; border-radius: 50%; background: var(--surface); border: 2px solid var(--text-faint); }
  .call.connected::before { background: var(--success); border-color: var(--success); }
  .call.disconnected::before { background: var(--surface); border-color: var(--border-strong); }
  .ch { padding: 12px 16px; cursor: pointer; display: flex; align-items: center; gap: 10px; user-select: none; flex-wrap: wrap; }
  .cn { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--text-faint); min-width: 24px; }
  .ctime { font-family: 'IBM Plex Mono', monospace; font-size: 12px; color: var(--text); font-weight: 500; }
  .cdur { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--text-muted); padding: 1px 6px; background: var(--surface-2); border-radius: 3px; }
  .csum { flex: 1 1 200px; color: var(--text-muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .caret { color: var(--text-faint); font-size: 10px; transition: transform 0.15s; }
  .call.open .caret { transform: rotate(90deg); }
  .cb { display: none; padding: 0 18px 16px; border-top: 1px dashed var(--border); padding-top: 14px; }
  .call.open .cb { display: block; }
  .sub-section-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-faint); margin-bottom: 8px; margin-top: 14px; }
  .sub-section-label:first-child { margin-top: 0; }
  .cfields { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px 20px; margin-bottom: 4px; }
  .summary-box { background: var(--surface-2); border-radius: 3px; padding: 10px 12px; font-size: 13px; line-height: 1.6; }
  .rejected-box { background: var(--danger-soft); border-left: 2px solid var(--danger); padding: 10px 12px; border-radius: 0 3px 3px 0; font-size: 13px; line-height: 1.5; }
  .rejected-box b { color: var(--danger); font-weight: 500; }
  .transcript-box { background: var(--surface-2); border-radius: 3px; padding: 12px 14px; font-family: 'IBM Plex Mono', monospace; font-size: 12px; line-height: 1.8; white-space: pre-wrap; max-height: 360px; overflow-y: auto; border-left: 2px solid var(--accent); }
  .rec-player { margin-top: 6px; }
  .rec-player audio { width: 100%; height: 36px; }
  .rec-link { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--info); text-decoration: none; margin-top: 4px; }
  .rec-link:hover { text-decoration: underline; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; font-weight: 500; line-height: 1.5; white-space: nowrap; }
  .b-success { background: var(--success-soft); color: var(--success); }
  .b-warning { background: var(--warning-soft); color: var(--warning); }
  .b-info { background: var(--info-soft); color: var(--info); }
  .b-danger { background: var(--danger-soft); color: var(--danger); }
  .b-neutral { background: var(--surface-2); color: var(--text-muted); }
  .none { padding: 40px 20px; text-align: center; color: var(--text-faint); font-style: italic; }
  ::-webkit-scrollbar { width: 8px; height: 8px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-faint); }
</style>
</head>
<body>
<div class="app">
  <header>
    <div class="brand">Lead Journey</div>
    <div class="search-box"><input id="q" type="text" placeholder="Search by buylead, city, car, hangup, disposition…"></div>
    <div class="filters" id="filters"></div>
    <div class="date-filter">
      <label for="dateFilter" style="font-size:12px;color:var(--text-muted);margin-right:4px;">Start date</label>
      <input type="date" id="dateFilter" style="padding:5px 10px;border:1px solid var(--border-strong);border-radius:4px;font-family:inherit;font-size:12px;color:var(--text);background:var(--bg);outline:none;cursor:pointer;" />
      <button id="dateReset" style="padding:5px 8px;border:1px solid var(--border-strong);border-radius:4px;background:transparent;color:var(--text-muted);cursor:pointer;font-size:11px;font-family:inherit;display:none;">Clear</button>
    </div>
    <div class="sort-control">
      <label for="sortBy" style="font-size:12px;color:var(--text-muted);margin-right:4px;">Sort</label>
      <select id="sortBy" style="padding:5px 10px;border:1px solid var(--border-strong);border-radius:4px;font-family:inherit;font-size:12px;color:var(--text);background:var(--bg);outline:none;cursor:pointer;">
        <option value="first_call_asc">First call (oldest)</option>
        <option value="first_call_desc">First call (newest)</option>
        <option value="total_calls">Most calls attempted</option>
        <option value="connected_calls">Most connected calls</option>
        <option value="milestone">Highest milestone</option>
        <option value="duration">Longest call (connected)</option>
        <option value="total_duration">Most total talk time</option>
      </select>
    </div>
    <div class="header-stats">
      <div class="hstat"><div class="hstat-val" id="sL">0</div><div class="hstat-label">Leads</div></div>
      <div class="hstat"><div class="hstat-val" id="sC">0</div><div class="hstat-label">Calls</div></div>
      <div class="hstat"><div class="hstat-val" id="sCon">0</div><div class="hstat-label">Connected</div></div>
    </div>
  </header>
  <main>
    <aside class="sidebar">
      <div class="sh" id="sh">Leads</div>
      <div id="list"></div>
    </aside>
    <section class="detail" id="detail"><div class="dempty">Select a lead to see their journey</div></section>
  </main>
</div>

<script>
const DATA = __DATA__;
const state = { filtered: DATA.map(l => l.id), active: null, filter: 'all', dateFilter: null, sortBy: 'first_call_asc' };
const $ = s => document.querySelector(s);
const esc = s => s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
const fmtPrice = n => !n ? '' : '\u20B9' + (n >= 100000 ? (n/100000).toFixed(1) + 'L' : (n/1000).toFixed(0) + 'k');
const parseDate = t => { if (!t) return null; const m = String(t).match(/^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2}))?/); if (m) return new Date(+m[3], +m[2]-1, +m[1], +(m[4]||0), +(m[5]||0)); const d = new Date(t); return isNaN(d) ? null : d; };
const fmtTime = t => { if (!t) return ''; const d = parseDate(t); return d ? d.toLocaleString('en-IN',{day:'2-digit',month:'short',year:'2-digit',hour:'2-digit',minute:'2-digit'}) : String(t); };
const fmtDur = s => { if (s == null || isNaN(s)) return ''; const total = Math.round(Number(s)); if (total < 60) return total + 's'; const m = Math.floor(total / 60), sec = total % 60; return m + ':' + String(sec).padStart(2, '0'); };
const tr = (s, n) => !s ? '' : (String(s).length > n ? String(s).slice(0,n) + '\u2026' : String(s));
const HANGUP_LBL = { 'CLIENT_INITIATED':'Client hung up', 'PARTICIPANT_REMOVED':'Agent ended', 'USER_UNAVAILABLE':'Not reachable', 'USER_UNRESPONSIVE':'No response', 'USER_REJECTED':'Rejected', 'VOICEMAIL_DETECTED':'Voicemail', 'OUTSIDE_TRIGGER_WINDOW':'Outside window' };
const HANGUP_BDG = { 'CLIENT_INITIATED':'b-success', 'PARTICIPANT_REMOVED':'b-success', 'USER_UNAVAILABLE':'b-neutral', 'USER_UNRESPONSIVE':'b-warning', 'USER_REJECTED':'b-danger', 'VOICEMAIL_DETECTED':'b-warning', 'OUTSIDE_TRIGGER_WINDOW':'b-neutral' };
const MS_LBL = { fresh_lead:'Fresh', minimal_engagement:'Minimal engagement', preference_collected:'Prefs collected', car_pitched:'Car pitched', test_drive_scheduled:'TD scheduled' };
const MS_BDG = { fresh_lead:'b-neutral', minimal_engagement:'b-warning', preference_collected:'b-info', car_pitched:'b-info', test_drive_scheduled:'b-success' };
const dispBadge = d => { const s = String(d || '').toLowerCase(); if (/book|schedul|convert|interested|td|test/.test(s)) return 'b-success'; if (/callback|follow/.test(s)) return 'b-warning'; if (/reject|not[_\s-]?interest|disconn|unreach/.test(s)) return 'b-danger'; if (/engage|pitch/.test(s)) return 'b-info'; return 'b-neutral'; };
const lastMilestone = l => { for (let i = l.calls.length - 1; i >= 0; i--) if (l.calls[i].milestone) return l.calls[i].milestone; return ''; };
const connectedCount = l => l.calls.filter(c => c.connected).length;
const everConnected = l => l.calls.some(c => c.connected);
const firstCallDate = l => { const t = l.calls[0]?.date || l.calls[0]?.time || ''; const d = parseDate(t); if (!d) return ''; return d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'); };
const firstCallTime = l => { const t = l.calls[0]?.time || l.calls[0]?.date || ''; const d = parseDate(t); return d ? d.getTime() : 0; };
const maxConnDuration = l => l.calls.filter(c => c.connected && c.duration).reduce((mx, c) => Math.max(mx, c.duration), 0);
const totalConnDuration = l => l.calls.filter(c => c.connected && c.duration).reduce((s, c) => s + c.duration, 0);
const MS_ORDER = { test_drive_scheduled: 5, car_pitched: 4, preference_collected: 3, minimal_engagement: 2, fresh_lead: 1 };
const SORT_FNS = {
  first_call_asc:  (a, b) => firstCallTime(a) - firstCallTime(b),
  first_call_desc: (a, b) => firstCallTime(b) - firstCallTime(a),
  total_calls:     (a, b) => b.calls.length - a.calls.length || firstCallTime(a) - firstCallTime(b),
  connected_calls: (a, b) => connectedCount(b) - connectedCount(a) || b.calls.length - a.calls.length,
  milestone:       (a, b) => (MS_ORDER[lastMilestone(b)] || 0) - (MS_ORDER[lastMilestone(a)] || 0) || b.calls.length - a.calls.length,
  duration:        (a, b) => maxConnDuration(b) - maxConnDuration(a) || connectedCount(b) - connectedCount(a),
  total_duration:  (a, b) => totalConnDuration(b) - totalConnDuration(a) || connectedCount(b) - connectedCount(a),
};

function renderFilters() {
  const filters = [
    { k: 'all', lbl: 'All leads', count: DATA.length },
    { k: 'connected', lbl: 'Ever connected', count: DATA.filter(everConnected).length, cls: 'active-success' },
    { k: 'never', lbl: 'Never connected', count: DATA.filter(l => !everConnected(l)).length, cls: 'active-warning' },
    { k: 'handoff', lbl: 'Handoff', count: DATA.filter(l => l.calls.some(c => c.handoff)).length },
    { k: 'dnd', lbl: 'DND', count: DATA.filter(l => l.calls.some(c => c.mark_dnd)).length },
    { k: 'td', lbl: 'TD scheduled', count: DATA.filter(l => lastMilestone(l) === 'test_drive_scheduled').length },
    { k: 'pitched', lbl: 'Car pitched', count: DATA.filter(l => lastMilestone(l) === 'car_pitched').length },
  ];
  $('#filters').innerHTML = filters.map(f => {
    const activeCls = state.filter === f.k ? (f.cls ? 'active ' + f.cls : 'active') : '';
    return `<button class="fchip ${activeCls}" data-k="${f.k}">${f.lbl} (${f.count})</button>`;
  }).join('');
  $('#filters').querySelectorAll('.fchip').forEach(btn => {
    btn.addEventListener('click', () => { state.filter = btn.dataset.k; applyFilter(); renderFilters(); });
  });
}

function applyFilter() {
  const q = $('#q').value.trim().toLowerCase();
  state.filtered = DATA.filter(l => {
    if (state.filter === 'connected' && !everConnected(l)) return false;
    if (state.filter === 'never' && everConnected(l)) return false;
    if (state.filter === 'handoff' && !l.calls.some(c => c.handoff)) return false;
    if (state.filter === 'dnd' && !l.calls.some(c => c.mark_dnd)) return false;
    if (state.filter === 'td' && lastMilestone(l) !== 'test_drive_scheduled') return false;
    if (state.filter === 'pitched' && lastMilestone(l) !== 'car_pitched') return false;
    if (state.dateFilter && firstCallDate(l) !== state.dateFilter) return false;
    if (!q) return true;
    const hay = [l.id, l.pre.city, l.pre.intent, l.pre.fuel, l.pre.body_type,
      ...l.interested_cars.map(c => c.make+' '+c.model),
      ...l.calls.map(c => (c.milestone||'')+' '+(c.disposition||'')+' '+(c.hangup||''))
    ].join(' ').toLowerCase();
    return hay.includes(q);
  }).sort(SORT_FNS[state.sortBy] || SORT_FNS.first_call_asc).map(l => l.id);
  renderSide();
}

function updateStats() {
  const leadsF = state.filtered.map(id => DATA.find(l => l.id === id));
  $('#sL').textContent = state.filtered.length;
  $('#sC').textContent = leadsF.reduce((s, l) => s + l.calls.length, 0);
  $('#sCon').textContent = leadsF.reduce((s, l) => s + connectedCount(l), 0);
}

function renderSide() {
  const list = $('#list');
  $('#sh').textContent = state.filtered.length + ' lead' + (state.filtered.length === 1 ? '' : 's');
  updateStats();
  if (!state.filtered.length) { list.innerHTML = '<div class="none">No matches</div>'; return; }
  list.innerHTML = state.filtered.map(id => {
    const l = DATA.find(x => x.id === id);
    const conn = connectedCount(l);
    const m = lastMilestone(l);
    return `<div class="li ${id===state.active?'active':''}" data-id="${esc(id)}">
      <div class="ltop">
        <div class="lid">${esc(id)}</div>
        <div class="ct-row">
          ${conn > 0 ? `<span class="ct conn">${conn} conn</span>` : `<span class="ct nc">0 conn</span>`}
          <span class="ct">${l.calls.length} call${l.calls.length===1?'':'s'}</span>
        </div>
      </div>
      <div class="lmeta">
        ${l.pre.city ? esc(l.pre.city) : ''}
        ${m ? `<span class="badge ${MS_BDG[m]||'b-neutral'}" style="font-size:10px;padding:1px 6px;">${esc(MS_LBL[m]||m)}</span>` : ''}
      </div>
    </div>`;
  }).join('');
  list.querySelectorAll('.li').forEach(el => el.addEventListener('click', () => selectLead(el.dataset.id)));
}

function selectLead(id) { state.active = id; renderSide(); renderDetail(id); }

function renderDetail(id) {
  const l = DATA.find(x => x.id === id);
  const d = $('#detail');
  if (!l) { d.innerHTML = ''; return; }
  const p = l.pre;
  const last = lastMilestone(l);
  const conn = connectedCount(l);
  const budget = (p.min_price || p.max_price) ? (fmtPrice(p.min_price) + ' \u2013 ' + fmtPrice(p.max_price)) : '';

  const preFields = [
    { lbl: 'City', val: p.city }, { lbl: 'Intent', val: (p.intent||'').replace('_',' ') },
    { lbl: 'Budget', val: budget }, { lbl: 'Fuel pref', val: p.fuel },
    { lbl: 'Body type', val: p.body_type }, { lbl: 'Transmission', val: p.transmission },
    { lbl: 'Make pref', val: p.make_pref }, { lbl: 'CRM milestone', val: p.crm_milestone },
    { lbl: 'CRM status', val: p.crm_status },
  ].filter(f => f.val);

  const carsHtml = l.interested_cars.length ? `
    <div class="sub-section-label">Interested cars (shown to agent)</div>
    <div class="cars">${l.interested_cars.map(c =>
      `<div class="car"><b>${esc(c.make)} ${esc(c.model)}</b><span class="meta">${c.price ? fmtPrice(c.price) : ''}${c.fuel ? ' \u00B7 ' + esc(c.fuel) : ''}${c.hub ? ' \u00B7 ' + esc(c.hub) : ''}</span></div>`
    ).join('')}</div>` : '';

  const callsHtml = l.calls.map((c, i) => {
    const connCls = c.connected ? 'connected' : 'disconnected';
    const hangupLbl = HANGUP_LBL[c.hangup] || c.hangup || '';
    const hangupCls = HANGUP_BDG[c.hangup] || 'b-neutral';
    const postFields = [
      { lbl: 'Hangup', val: hangupLbl, mono: true },
      { lbl: 'Scenario', val: (c.scenario||'').replace(/^S\d+_/,'').replace(/_/g,' ').toLowerCase() },
      { lbl: 'Milestone', val: MS_LBL[c.milestone] || c.milestone },
      { lbl: 'Disposition', val: (c.disposition||'').replace(/_/g,' ') },
      { lbl: 'Budget mentioned', val: c.budget ? fmtPrice(Number(c.budget)) : '' },
      { lbl: 'Pitched cars', val: c.pitched_cars, mono: true },
      { lbl: 'Rejected cars', val: c.rejected_cars, mono: true },
      { lbl: 'Liked cars', val: c.liked_cars, mono: true },
      { lbl: 'Marked DND', val: c.mark_dnd ? 'Yes' : '' },
      { lbl: 'Human handoff', val: c.handoff ? 'Yes' : '' },
      { lbl: 'Handoff reason', val: c.handoff_reason },
      { lbl: 'Next attempt (ndoa)', val: c.ndoa ? fmtTime(c.ndoa) : '' },
    ].filter(f => f.val);
    return `<div class="call ${connCls}">
      <div class="ch">
        <span class="cn">${String(i+1).padStart(2,'0')}</span>
        <span class="ctime">${esc(fmtTime(c.time))}</span>
        ${c.duration != null ? `<span class="cdur">${esc(fmtDur(c.duration))}</span>` : ''}
        <span class="badge ${c.connected ? 'b-success' : 'b-neutral'}">${c.connected ? 'Connected' : 'Not connected'}</span>
        <span class="badge ${hangupCls}">${esc(hangupLbl)}</span>
        ${c.handoff ? '<span class="badge b-warning">Handoff</span>' : ''}
        ${c.mark_dnd ? '<span class="badge b-danger">DND</span>' : ''}
        <span class="csum">${esc(tr((c.disposition||'').replace(/_/g,' '), 120))}</span>
        <span class="caret">\u25B6</span>
      </div>
      <div class="cb">
        ${c.rejected_reasons ? `<div class="sub-section-label">Why rejected</div><div class="rejected-box"><b>Reason: </b>${esc(c.rejected_reasons)}</div>` : ''}
        ${postFields.length ? `<div class="sub-section-label">Post-call details</div><div class="cfields">${postFields.map(f => `<div><div class="fl">${esc(f.lbl)}</div><div class="fv ${f.mono?'mono':''}">${esc(f.val)}</div></div>`).join('')}</div>` : ''}
        ${c.recording ? `<div class="sub-section-label">Recording</div><div class="rec-player"><audio controls preload="none" src="${esc(c.recording)}"></audio></div><a class="rec-link" href="${esc(c.recording)}" target="_blank" rel="noopener">Open recording in new tab \u2197</a>` : ''}
        ${c.transcript ? `<div class="sub-section-label">Transcript</div><div class="transcript-box">${esc(c.transcript)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  d.innerHTML = `
    <div class="di">
      <div class="dh">
        <div class="dt">${esc(l.id)}</div>
        <div class="ds">
          <span>${l.calls.length} call${l.calls.length===1?'':'s'}</span>
          <span class="sep">\u00B7</span><span>${conn} connected</span>
          ${p.city ? `<span class="sep">\u00B7</span><span>${esc(p.city)}</span>` : ''}
          ${last ? `<span class="sep">\u00B7</span><span class="badge ${MS_BDG[last]||'b-neutral'}">${esc(MS_LBL[last]||last)}</span>` : ''}
        </div>
      </div>
      <div class="pre-block">
        <div class="pre-label">Pre-call context &mdash; what we knew about the lead</div>
        <div class="fg">${preFields.map(f => `<div><div class="fl">${esc(f.lbl)}</div><div class="fv ${f.mono?'mono':''}">${esc(f.val)}</div></div>`).join('')}</div>
        ${carsHtml}
      </div>
      <div class="section-hdr"><div class="sec-title">Call timeline</div><div class="sec-sub">${l.calls.length} attempts, ${conn} connected</div></div>
      <div class="tl">${callsHtml}</div>
    </div>
  `;
  d.querySelectorAll('.call .ch').forEach(h => h.addEventListener('click', () => h.parentElement.classList.toggle('open')));
  const firstOpen = d.querySelector('.call.connected') || d.querySelector('.call');
  if (firstOpen) firstOpen.classList.add('open');
  d.scrollTop = 0;
}

let tmr = null;
$('#q').addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(applyFilter, 100); });
$('#dateFilter').addEventListener('change', e => {
  state.dateFilter = e.target.value || null;
  $('#dateReset').style.display = state.dateFilter ? 'inline-block' : 'none';
  applyFilter(); renderFilters();
});
$('#dateReset').addEventListener('click', () => {
  $('#dateFilter').value = '';
  state.dateFilter = null;
  $('#dateReset').style.display = 'none';
  applyFilter(); renderFilters();
});
$('#sortBy').addEventListener('change', e => {
  state.sortBy = e.target.value;
  applyFilter();
});
(function setDateBounds() {
  const dates = DATA.map(firstCallDate).filter(Boolean).sort();
  if (dates.length) { $('#dateFilter').min = dates[0]; $('#dateFilter').max = dates[dates.length - 1]; }
})();
renderFilters();
renderSide();
if (DATA.length) selectLead(DATA[0].id);
</script>
</body>
</html>
"""


# =============================================================================
# MAIN
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: file not found: {csv_path}")
        sys.exit(1)

    out_path = Path(sys.argv[2]) if len(sys.argv) >= 3 else csv_path.with_suffix(".html")

    print(f"Reading  {csv_path}")
    df = pd.read_csv(csv_path, low_memory=False)
    print(f"         {len(df):,} rows, {len(df.columns)} columns")

    print("Processing…")
    leads = build_leads_data(df)

    total_calls     = sum(len(l["calls"]) for l in leads)
    connected_calls = sum(1 for l in leads for c in l["calls"] if c["connected"])
    ever_connected  = sum(1 for l in leads if any(c["connected"] for c in l["calls"]))

    print(f"         {len(leads):,} unique leads")
    print(f"         {total_calls:,} total calls ({connected_calls:,} connected)")
    print(f"         {ever_connected:,}/{len(leads)} leads ever connected")

    data_json = json.dumps(leads, ensure_ascii=False, separators=(",", ":"))
    html = HTML_TEMPLATE.replace("__DATA__", data_json)

    print(f"Writing  {out_path}")
    out_path.write_text(html, encoding="utf-8")
    print(f"         {len(html):,} chars ({os.path.getsize(out_path) / 1024:.0f} KB)")
    print(f"\nOpen {out_path} in your browser.")


if __name__ == "__main__":
    main()