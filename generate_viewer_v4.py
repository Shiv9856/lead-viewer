#!/usr/bin/env python3
"""Enhanced Lead Journey Viewer — extracts per-call metadata + post-call variables."""
import sys, os, json, ast, re
from pathlib import Path
import pandas as pd

CONNECTED_HANGUPS = {"CLIENT_INITIATED", "PARTICIPANT_REMOVED", "SESSION_TIMEOUT"}
MAX_TRANSCRIPT_CHARS = 10000

def _c(v):
    if pd.isna(v): return None
    if isinstance(v, float) and v.is_integer(): return int(v)
    return v

def _s(v):
    """Return cleaned string or empty."""
    if pd.isna(v) or v is None: return ""
    s = str(v).strip()
    # Clean JSON-ish arrays like '["petrol"]' → 'petrol'
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s.replace("'", '"'))
            if isinstance(parsed, list):
                return ", ".join(str(x) for x in parsed)
        except: pass
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, list):
                return ", ".join(str(x) for x in parsed)
        except: pass
    return s

def _b(v):
    if pd.isna(v): return False
    if isinstance(v, bool): return v
    return str(v).strip().lower() in ("true", "1", "yes")

def _parse_summary(raw):
    if pd.isna(raw) or not str(raw).strip(): return None
    for parser in (json.loads, ast.literal_eval):
        try:
            p = parser(raw)
            if isinstance(p, list) and p: return p[0]
            return p
        except: continue
    return None

_SSML = re.compile(r"<break[^>]*/?>")
def _clean_tx(text):
    if not text: return ""
    text = _SSML.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+(Assistant|User):\s*", r"\n\1: ", text)
    return text.strip()

def _extract_prefs(row, prefix):
    """Extract agent or customer filter data."""
    p = {}
    for key in ("fuel_type", "transmission", "body_type", "color", "rto",
                 "make", "min_price", "max_price", "min_year", "max_year",
                 "min_mileage", "max_mileage", "no_of_owners"):
        v = _s(row.get(f"preferences.{prefix}.{key}"))
        if v: p[key] = v
    # City
    city = _s(row.get(f"preferences.{prefix}.city.display_name"))
    if city: p["city"] = city
    return p if any(p.values()) else None

def _extract_comments(row):
    comments = []
    for i in range(5):
        c = _s(row.get(f"comments.{i}.comment"))
        if c:
            comments.append({
                "text": c,
                "date": _s(row.get(f"comments.{i}.submit_date")),
                "user": _s(row.get(f"comments.{i}.full_name")) or _s(row.get(f"comments.{i}.user")),
            })
    return comments if comments else None

def _extract_visits(row):
    visits = []
    for i in range(3):
        vid = _s(row.get(f"all_visits.{i}.id"))
        stime = _s(row.get(f"all_visits.{i}.scheduled_time"))
        if vid or stime:
            visits.append({
                "id": vid,
                "time": stime,
                "type": _s(row.get(f"all_visits.{i}.visit_type_display_name")),
                "hub": _s(row.get(f"all_visits.{i}.hub_name")),
                "status": _s(row.get(f"all_visits.{i}.status")),
                "at_home": _b(row.get(f"all_visits.{i}.at_home")),
                "td_status": _s(row.get(f"all_visits.{i}.test_drives.0.status_name")),
                "td_cancelled": _b(row.get(f"all_visits.{i}.test_drives.0.cancelled")),
                "cancel_reason": _s(row.get(f"all_visits.{i}.test_drives.0.reason_for_cancellation")),
            })
    return visits if visits else None

def build_leads(df):
    leads = {}
    for _, row in df.iterrows():
        lid = str(_c(row["buylead"]))
        if lid in ("None", "nan", ""): continue

        # --- Per-call METADATA (what was known BEFORE this call) ---
        agent_prefs = _extract_prefs(row, "agent_filter_data")
        cust_prefs = _extract_prefs(row, "customer_filter_data")
        comments = _extract_comments(row)
        visits = _extract_visits(row)

        meta = {}
        if agent_prefs: meta["agent_prefs"] = agent_prefs
        if cust_prefs: meta["cust_prefs"] = cust_prefs
        if comments: meta["comments"] = comments
        if visits: meta["visits"] = visits

        # Visit context for this specific call
        vt = _s(row.get("visit_time"))
        if vt: meta["visit_time"] = vt
        vtype = _s(row.get("visit_type"))
        if vtype: meta["visit_type"] = vtype
        hub = _s(row.get("hub_name"))
        if hub: meta["hub_name"] = hub

        # Last call context
        lcm = _s(row.get("last_call_milestone"))
        if lcm:
            meta["last_call"] = {
                "milestone": lcm,
                "disposition": _s(row.get("last_call_disposition")),
                "budget": _s(row.get("last_call_budget")),
                # "pitched": _s(row.get("last_call_pitched_cars_id")),
                # "rejected": _s(row.get("last_call_rejected_cars_id")),
                # "liked": _s(row.get("last_call_liked_car_id")),
            }

        intent = _s(row.get("preferences.customer_intent"))
        if intent: meta["intent"] = intent

        scenario = _s(row.get("added_scenario"))
        cap = _s(row.get("starting_capability"))

        # --- POST-CALL variables ---
        summary = _parse_summary(row.get("summary"))
        hangup = _s(row.get("Hangup Reason"))
        duration = _c(row.get("Call Duration"))

        call = {
            "date": _s(row.get("Call Date")),
            "time": _s(row.get("Call Time")),
            "duration": round(duration, 1) if isinstance(duration, (int, float)) else None,
            "recording": _s(row.get("Call Recording")),
            "transcript": _clean_tx(_s(row.get("Call Transcript"))),
            "hangup": hangup,
            "connected": hangup in CONNECTED_HANGUPS,
            "scenario": scenario,
            "capability": cap,
            # Post-call booleans
            "mark_dnd": _b(row.get("Mark_DND")),
            "soft_dnd": _b(row.get("Soft_DND")),
            "handoff": _b(row.get("human_handoff")),
            "handoff_reason": _s(row.get("human_handoff_reason")),
            "car_pitched": _b(row.get("car_pitched")),
            "interested_for_td": _b(row.get("interested_for_test_drive")),
            "interested_buying": _b(row.get("interested_in_buying")),
            "interested_sell": _b(row.get("interested_to_sell")),
            "lang_switch": _b(row.get("requested_language_switch")),
            "loan_interest": _b(row.get("user_loan_finance_response")),
            "conversion": _b(row.get("conversion_status")),
            "confirmed_visit": _b(row.get("Confirmed_Visit")),
            "cancellation": _b(row.get("cancellation")),
            "rescheduled": _b(row.get("rescheduled")),
            "inconclusive": _b(row.get("inconclusive")),
            # Post-call text
            "milestone": _s(row.get("milestone")),
            "ndoa": _s(row.get("ndoa")),
            "dispose": _s(row.get("dispose")),
            "cancel_reason": _s(row.get("cancellation_reason")),
            "rescheduled_time": _s(row.get("rescheduled_time")),
            "selected_td_slot": _s(row.get("selected_test_drive_slot")),
            "updated_city": _s(row.get("updated_city")),
            "review": _s(row.get("review")),
            # Car IDs (only kept: liked + td)
            # "liked_cars": _s(row.get("liked_cars_id")),
            # "td_cars": _s(row.get("test_drive_scheduled_car_ids")),
            # User preferences (post-call updated)
            "user_budget_min": _s(row.get("user_budget_minimum")),
            "user_budget_max": _s(row.get("user_budget_maximum")),
            "user_fuel": _s(row.get("user_fuel_type")),
            "user_trans": _s(row.get("user_transmission_preference")),
            "user_body": _s(row.get("user_car_type")),
            "user_color": _s(row.get("user_preferred_color")),
            "user_make": _s(row.get("user_preferred_make")),
            "user_model": _s(row.get("user_preferred_model")),
            "user_seats": _s(row.get("user_preferred_seating_capacity")),
        }

        if summary:
            call["budget"] = _s(summary.get("budget"))
            call["rejected_reasons"] = _s(summary.get("rejected_reasons"))
            if not call["dispose"]:
                call["dispose"] = _s(summary.get("disposition"))

        if meta: call["meta"] = meta

        # Truncate transcript
        t = call["transcript"]
        if len(t) > MAX_TRANSCRIPT_CHARS:
            call["transcript"] = t[:MAX_TRANSCRIPT_CHARS] + f"\n\n[… truncated, {len(t)-MAX_TRANSCRIPT_CHARS} more chars]"

        if lid not in leads:
            leads[lid] = {
                "id": lid,
                "city": _s(row.get("city")),
                "calls": [],
            }
        leads[lid]["city"] = _s(row.get("city")) or leads[lid]["city"]
        leads[lid]["calls"].append(call)

    for lead in leads.values():
        lead["calls"].sort(key=lambda c: c.get("time") or c.get("date") or "")
    return list(leads.values())

# ============================================================
# HTML
# ============================================================
HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>SQL</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--bg:#FAF8F5;--s:#FFF;--s2:#F3EFE8;--bd:#E8E4DC;--bds:#D4CEC1;--tx:#1A1814;--tm:#6B6458;--tf:#9E9688;--ac:#C4633F;--as:#F4E4D9;--ok:#4A7C59;--oks:#DCE8DE;--wn:#B8823D;--wns:#F2E4CC;--in:#3F6B9C;--ins:#DDE6F0;--dn:#9C3F3F;--dns:#F0DDDD;--or:#8B5E3C;--ors:#F0E6D6}
*{box-sizing:border-box;margin:0;padding:0}html,body{height:100%}
body{font-family:'IBM Plex Sans',sans-serif;background:var(--bg);color:var(--tx);font-size:14px;line-height:1.5;overflow:hidden}
code,.mono{font-family:'IBM Plex Mono',monospace}
.app{display:flex;flex-direction:column;height:100vh}
header{padding:10px 20px;background:var(--s);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:12px;flex-shrink:0;flex-wrap:wrap}
.brand{font-family:'Instrument Serif',serif;font-weight:400;font-style:italic;font-size:22px;white-space:nowrap}
.sbox{flex:1;max-width:380px;min-width:180px;position:relative}
.sbox input{width:100%;padding:8px 12px 8px 34px;border:1px solid var(--bds);background:var(--bg);border-radius:4px;font-family:inherit;font-size:13px;outline:none}
.sbox input:focus{border-color:var(--ac)}
.sbox::before{content:'';position:absolute;left:11px;top:50%;width:13px;height:13px;transform:translateY(-50%);background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236B6458' stroke-width='2'><circle cx='11' cy='11' r='7'/><path d='m21 21-4.3-4.3'/></svg>");background-size:contain}
.filters{display:flex;gap:5px;flex-wrap:wrap}
.fch{padding:4px 10px;border:1px solid var(--bds);background:transparent;color:var(--tm);border-radius:18px;cursor:pointer;font-family:inherit;font-size:11px;transition:all .1s;white-space:nowrap}
.fch:hover{border-color:var(--tm);color:var(--tx)}.fch.on{background:var(--tx);color:var(--bg);border-color:var(--tx)}
.fch.on-ok{background:var(--ok);color:#fff;border-color:var(--ok)}.fch.on-wn{background:var(--wn);color:#fff;border-color:var(--wn)}
.fch.on-dn{background:var(--dn);color:#fff;border-color:var(--dn)}.fch.on-or{background:var(--or);color:#fff;border-color:var(--or)}
.dfl{display:flex;align-items:center;gap:5px}
.dfl label{font-size:11px;color:var(--tm)}
.dfl input,.dfl select{padding:4px 8px;border:1px solid var(--bds);border-radius:4px;font-family:inherit;font-size:11px;background:var(--bg);outline:none}
.dfl button{padding:4px 7px;border:1px solid var(--bds);border-radius:4px;background:transparent;color:var(--tm);cursor:pointer;font-size:10px;display:none}
.hst{display:flex;gap:12px;margin-left:auto}
.hst>div{text-align:right}.hst-v{font-family:'IBM Plex Mono',monospace;font-weight:500;font-size:14px}
.hst-l{font-size:9px;color:var(--tm);text-transform:uppercase;letter-spacing:.08em}
main{flex:1;display:flex;overflow:hidden}
.sidebar{width:330px;min-width:330px;border-right:1px solid var(--bd);background:var(--s);overflow-y:auto}
.sh{padding:8px 18px;font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf);border-bottom:1px solid var(--bd);position:sticky;top:0;background:var(--s);z-index:1}
.li{padding:10px 18px;border-bottom:1px solid var(--bd);cursor:pointer;transition:background .08s;position:relative}
.li:hover{background:var(--s2)}.li.act{background:var(--as)}
.li.act::before{content:'';position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--ac)}
.ltop{display:flex;align-items:center;gap:6px;margin-bottom:3px}
.lid{font-family:'IBM Plex Mono',monospace;font-size:12px;font-weight:500}
.ctr{display:flex;gap:3px;margin-left:auto}
.ct{padding:1px 6px;background:var(--s2);border-radius:9px;font-size:10px;font-family:'IBM Plex Mono',monospace;color:var(--tm)}
.ct.cn{background:var(--oks);color:var(--ok)}.ct.nc{color:var(--tf)}
.lm{font-size:11px;color:var(--tm);display:flex;gap:5px;align-items:center;flex-wrap:wrap}
.detail{flex:1;overflow-y:auto;background:var(--bg)}
.de{height:100%;display:flex;align-items:center;justify-content:center;color:var(--tf);font-family:'Instrument Serif',serif;font-style:italic;font-size:20px}
.di{padding:24px 36px;max-width:1020px}
.dh{margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--bd)}
.dt{font-family:'Instrument Serif',serif;font-size:34px;line-height:1.1}
.ds{color:var(--tm);font-size:12px;display:flex;flex-wrap:wrap;gap:5px 10px;align-items:center;margin-top:6px}
.ds .sep{color:var(--tf)}
.badge{display:inline-block;padding:1px 7px;border-radius:3px;font-size:10px;font-weight:500;line-height:1.5;white-space:nowrap}
.b-ok{background:var(--oks);color:var(--ok)}.b-wn{background:var(--wns);color:var(--wn)}
.b-in{background:var(--ins);color:var(--in)}.b-dn{background:var(--dns);color:var(--dn)}
.b-ne{background:var(--s2);color:var(--tm)}.b-or{background:var(--ors);color:var(--or)}
.fg{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px 18px}
.fl{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf);margin-bottom:1px}
.fv{font-size:12px;word-break:break-word}.fv.mono{font-family:'IBM Plex Mono',monospace;font-size:11px}
/* Timeline */
.sec-h{display:flex;align-items:baseline;justify-content:space-between;margin:18px 0 12px}
.sec-t{font-family:'Instrument Serif',serif;font-style:italic;font-size:20px}
.sec-s{font-size:11px;color:var(--tm)}
.tl{position:relative;padding-left:22px}
.tl::before{content:'';position:absolute;left:5px;top:8px;bottom:8px;width:1px;background:var(--bds)}
.call{position:relative;background:var(--s);border:1px solid var(--bd);border-radius:4px;margin-bottom:8px}
.call::before{content:'';position:absolute;left:-20px;top:16px;width:8px;height:8px;border-radius:50%;background:var(--s);border:2px solid var(--tf)}
.call.conn::before{background:var(--ok);border-color:var(--ok)}
.call.disc::before{background:var(--s);border-color:var(--bds)}
.ch{padding:10px 14px;cursor:pointer;display:flex;align-items:center;gap:8px;user-select:none;flex-wrap:wrap}
.cnum{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--tf);min-width:20px}
.ctm{font-family:'IBM Plex Mono',monospace;font-size:11px;font-weight:500}
.cdur{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--tm);padding:1px 5px;background:var(--s2);border-radius:3px}
.cdisp{flex:1 1 140px;color:var(--tm);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}
.caret{color:var(--tf);font-size:9px;transition:transform .15s}
.call.open .caret{transform:rotate(90deg)}
.cb{display:none;border-top:1px dashed var(--bd)}
.call.open .cb{display:block}
/* Inner tabs per call */
.ctabs{display:flex;gap:0;border-bottom:1px solid var(--bd);background:var(--s2)}
.ctab{padding:6px 12px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--tm);cursor:pointer;border-bottom:2px solid transparent}
.ctab:hover{color:var(--tx)}.ctab.on{color:var(--ac);border-bottom-color:var(--ac)}
.cpanel{display:none;padding:12px 16px}.cpanel.on{display:block}
.slbl{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf);margin-bottom:6px;margin-top:10px}
.slbl:first-child{margin-top:0}
.cf{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px 16px;margin-bottom:4px}
.rbox{background:var(--dns);border-left:2px solid var(--dn);padding:8px 10px;border-radius:0 3px 3px 0;font-size:12px;line-height:1.5}
.rbox b{color:var(--dn);font-weight:500}
.txbox{background:var(--s2);border-radius:3px;padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:11px;line-height:1.8;white-space:pre-wrap;max-height:340px;overflow-y:auto;border-left:2px solid var(--ac)}
/* Transcript status row */
.txstatus{display:flex;gap:16px;padding:8px 12px;background:var(--s2);border-radius:3px;margin-bottom:8px;border-left:2px solid var(--in)}
.txstatus .item{display:flex;flex-direction:column;gap:2px}
.txstatus .item .k{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf)}
.txstatus .item .v{font-size:12px;color:var(--tx);font-family:'IBM Plex Mono',monospace}
.rec{margin-bottom:8px}
.rec a{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--in);text-decoration:none;margin-top:3px}
.rec a:hover{text-decoration:underline}
.rec audio{width:100%;height:36px}
.none{padding:30px;text-align:center;color:var(--tf);font-style:italic}
.cmt{background:var(--s2);border-radius:3px;padding:8px 10px;font-size:12px;margin-bottom:4px;border-left:2px solid var(--wn)}
.cmt .cu{font-size:10px;color:var(--tm);margin-bottom:2px}
::-webkit-scrollbar{width:7px;height:7px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--bds);border-radius:4px}::-webkit-scrollbar-thumb:hover{background:var(--tf)}
</style>
</head>
<body>
<div class="app">
<header>
 <div class="brand">SQL</div>
 <div class="sbox"><input id="q" type="text" placeholder="Search buylead, city, scenario, disposition…"></div>
 <div class="filters" id="fil"></div>
 <div class="dfl">
  <label>Date</label><input type="date" id="df"><button id="dr">×</button>
 </div>
 <div class="dfl">
  <label>Sort</label>
  <select id="so">
   <option value="fca">First call ↑</option><option value="fcd">First call ↓</option>
   <option value="tc">Most calls</option><option value="cc">Most connected</option>
   <option value="ms">Milestone</option><option value="dur">Longest call</option>
   <option value="tdur">Total talk time</option>
  </select>
 </div>
 <div class="hst">
  <div><div class="hst-v" id="sL">0</div><div class="hst-l">Leads</div></div>
  <div><div class="hst-v" id="sC">0</div><div class="hst-l">Calls</div></div>
  <div><div class="hst-v" id="sCo">0</div><div class="hst-l">Connected</div></div>
 </div>
</header>
<main>
 <aside class="sidebar"><div class="sh" id="sh">Leads</div><div id="list"></div></aside>
 <section class="detail" id="det"><div class="de">Select a lead to see their journey</div></section>
</main>
</div>
<script>
const D=__DATA__;
const st={fil:D.map(l=>l.id),act:null,fk:'all',df:null,so:'fca'};
const $=s=>document.querySelector(s);
const esc=s=>s==null?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fp=n=>!n?'':`₹${n>=1e5?(n/1e5).toFixed(1)+'L':(n/1e3).toFixed(0)+'k'}`;
const pd=t=>{if(!t)return null;const m=String(t).match(/^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?/);if(m)return new Date(+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0),+(m[6]||0));const d=new Date(t);return isNaN(d)?null:d;};
const ft=t=>{if(!t)return'';const d=pd(t);return d?d.toLocaleString('en-IN',{day:'2-digit',month:'short',year:'2-digit',hour:'2-digit',minute:'2-digit'}):String(t)};
const fd=s=>{if(s==null||isNaN(s))return'';const t=Math.round(+s);if(t<60)return t+'s';const m=Math.floor(t/60),r=t%60;return m+':'+String(r).padStart(2,'0')};
const tr=(s,n)=>!s?'':s.length>n?s.slice(0,n)+'…':s;
const HL={'CLIENT_INITIATED':'Client hung up','PARTICIPANT_REMOVED':'Agent ended','SESSION_TIMEOUT':'Session timeout','USER_UNAVAILABLE':'Unreachable','USER_UNRESPONSIVE':'No response','USER_REJECTED':'Rejected','VOICEMAIL_DETECTED':'Voicemail','OUTSIDE_TRIGGER_WINDOW':'Outside window'};
const HB={'CLIENT_INITIATED':'b-ok','PARTICIPANT_REMOVED':'b-ok','SESSION_TIMEOUT':'b-ok','USER_UNAVAILABLE':'b-ne','USER_UNRESPONSIVE':'b-wn','USER_REJECTED':'b-dn','VOICEMAIL_DETECTED':'b-wn','OUTSIDE_TRIGGER_WINDOW':'b-ne'};
const ML={'fresh_lead':'Fresh','minimal_engagement':'Minimal','preference_collected':'Prefs','car_pitched':'Pitched','test_drive_scheduled':'TD Sched'};
const MB={'fresh_lead':'b-ne','minimal_engagement':'b-wn','preference_collected':'b-in','car_pitched':'b-in','test_drive_scheduled':'b-ok'};
const MO={test_drive_scheduled:5,car_pitched:4,preference_collected:3,minimal_engagement:2,fresh_lead:1};
const lm=l=>{for(let i=l.calls.length-1;i>=0;i--)if(l.calls[i].milestone)return l.calls[i].milestone;return''};
const cc=l=>l.calls.filter(c=>c.connected).length;
const ec=l=>l.calls.some(c=>c.connected);
const fcd=l=>{const t=l.calls[0]?.date||l.calls[0]?.time||'';const d=pd(t);if(!d)return'';return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0')};
const fct=l=>{const t=l.calls[0]?.time||l.calls[0]?.date||'';const d=pd(t);return d?d.getTime():0};
const mcd=l=>l.calls.filter(c=>c.connected&&c.duration).reduce((m,c)=>Math.max(m,c.duration),0);
const tcd=l=>l.calls.filter(c=>c.connected&&c.duration).reduce((s,c)=>s+c.duration,0);
const SF={fca:(a,b)=>fct(a)-fct(b),fcd:(a,b)=>fct(b)-fct(a),tc:(a,b)=>b.calls.length-a.calls.length,cc:(a,b)=>cc(b)-cc(a),ms:(a,b)=>(MO[lm(b)]||0)-(MO[lm(a)]||0),dur:(a,b)=>mcd(b)-mcd(a),tdur:(a,b)=>tcd(b)-tcd(a)};

function renderFil(){
 const fs=[
  {k:'all',l:'All',c:D.length},
  {k:'conn',l:'Connected',c:D.filter(ec).length,cl:'on-ok'},
  {k:'never',l:'Never conn',c:D.filter(l=>!ec(l)).length,cl:'on-wn'},
  {k:'handoff',l:'Handoff',c:D.filter(l=>l.calls.some(c=>c.handoff)).length},
  {k:'dnd',l:'DND',c:D.filter(l=>l.calls.some(c=>c.mark_dnd)).length,cl:'on-dn'},
  {k:'sdnd',l:'Soft DND',c:D.filter(l=>l.calls.some(c=>c.soft_dnd)).length,cl:'on-or'},
  {k:'td',l:'TD Sched',c:D.filter(l=>lm(l)==='test_drive_scheduled').length},
  {k:'pit',l:'Pitched',c:D.filter(l=>lm(l)==='car_pitched').length},
  {k:'conv',l:'Converted',c:D.filter(l=>l.calls.some(c=>c.conversion)).length,cl:'on-ok'},
 ];
 $('#fil').innerHTML=fs.map(f=>`<button class="fch ${st.fk===f.k?(f.cl||'on'):''}" data-k="${f.k}">${f.l} (${f.c})</button>`).join('');
 $('#fil').querySelectorAll('.fch').forEach(b=>b.onclick=()=>{st.fk=b.dataset.k;apply();renderFil()});
}

function apply(){
 const q=$('#q').value.trim().toLowerCase();
 st.fil=D.filter(l=>{
  if(st.fk==='conn'&&!ec(l))return false;
  if(st.fk==='never'&&ec(l))return false;
  if(st.fk==='handoff'&&!l.calls.some(c=>c.handoff))return false;
  if(st.fk==='dnd'&&!l.calls.some(c=>c.mark_dnd))return false;
  if(st.fk==='sdnd'&&!l.calls.some(c=>c.soft_dnd))return false;
  if(st.fk==='td'&&lm(l)!=='test_drive_scheduled')return false;
  if(st.fk==='pit'&&lm(l)!=='car_pitched')return false;
  if(st.fk==='conv'&&!l.calls.some(c=>c.conversion))return false;
  if(st.df&&fcd(l)!==st.df)return false;
  if(!q)return true;
  const h=[l.id,l.city,...l.calls.map(c=>[c.milestone,c.dispose,c.scenario,c.hangup].join(' '))].join(' ').toLowerCase();
  return h.includes(q);
 }).sort(SF[st.so]||SF.fca).map(l=>l.id);
 renderSide();
}

function renderSide(){
 const ls=$('#list');
 $('#sh').textContent=st.fil.length+' lead'+(st.fil.length===1?'':'s');
 const fl=st.fil.map(id=>D.find(l=>l.id===id));
 $('#sL').textContent=st.fil.length;
 $('#sC').textContent=fl.reduce((s,l)=>s+l.calls.length,0);
 $('#sCo').textContent=fl.reduce((s,l)=>s+cc(l),0);
 if(!st.fil.length){ls.innerHTML='<div class="none">No matches</div>';return}
 ls.innerHTML=st.fil.map(id=>{
  const l=D.find(x=>x.id===id);const cn=cc(l);const m=lm(l);
  const hasDnd=l.calls.some(c=>c.mark_dnd);const hasSdnd=l.calls.some(c=>c.soft_dnd);
  return`<div class="li ${id===st.act?'act':''}" data-id="${esc(id)}">
   <div class="ltop"><div class="lid">${esc(id)}</div>
    <div class="ctr">
     ${hasDnd?'<span class="ct" style="background:var(--dns);color:var(--dn)">DND</span>':''}
     ${hasSdnd?'<span class="ct" style="background:var(--ors);color:var(--or)">Soft</span>':''}
     ${cn>0?`<span class="ct cn">${cn} conn</span>`:`<span class="ct nc">0 conn</span>`}
     <span class="ct">${l.calls.length}</span>
    </div>
   </div>
   <div class="lm">${l.city?esc(l.city):''}${m?` <span class="badge ${MB[m]||'b-ne'}" style="font-size:9px;padding:1px 5px">${esc(ML[m]||m)}</span>`:''}</div>
  </div>`;
 }).join('');
 ls.querySelectorAll('.li').forEach(e=>e.onclick=()=>sel(e.dataset.id));
}

function sel(id){st.act=id;renderSide();renderDet(id)}

function prefGrid(obj,label){
 if(!obj||!Object.keys(obj).length)return'';
 const nice={'fuel_type':'Fuel','transmission':'Trans','body_type':'Body','color':'Color','rto':'RTO','make':'Make',
  'min_price':'Min Price','max_price':'Max Price','min_year':'Min Year','max_year':'Max Year',
  'min_mileage':'Min KM','max_mileage':'Max KM','no_of_owners':'Owners','city':'City'};
 let h=`<div class="slbl">${esc(label)}</div><div class="cf">`;
 for(const[k,v] of Object.entries(obj)){
  if(!v)continue;
  const lbl=nice[k]||k;
  const dv=(k.includes('price')&&!isNaN(v))?fp(+v):esc(String(v));
  h+=`<div><div class="fl">${esc(lbl)}</div><div class="fv mono">${dv}</div></div>`;
 }
 return h+'</div>';
}

function renderDet(id){
 const l=D.find(x=>x.id===id);const d=$('#det');
 if(!l){d.innerHTML='';return}
 const m=lm(l);const cn=cc(l);

 // Build call timeline
 const callsH=l.calls.map((c,i)=>{
  const cls=c.connected?'conn':'disc';
  const hl=HL[c.hangup]||c.hangup||'';
  const hb=HB[c.hangup]||'b-ne';
  const mt=c.meta||{};

  // META panel (Before Call)
  let metaH='';
  metaH+=prefGrid(mt.agent_prefs,'Agent preferences (before call)');
  metaH+=prefGrid(mt.cust_prefs,'Customer preferences (before call)');
  if(mt.last_call){
   const lc=mt.last_call;
   metaH+=`<div class="slbl">Last call context</div><div class="cf">
    ${lc.milestone?`<div><div class="fl">Milestone</div><div class="fv">${esc(lc.milestone)}</div></div>`:''}
    ${lc.disposition?`<div><div class="fl">Disposition</div><div class="fv">${esc(lc.disposition)}</div></div>`:''}
    ${lc.budget?`<div><div class="fl">Budget</div><div class="fv mono">${fp(+lc.budget)}</div></div>`:''}
    ${lc.pitched?`<div><div class="fl">Pitched</div><div class="fv mono">${esc(lc.pitched)}</div></div>`:''}
   </div>`;
  }
  if(mt.visits){
   metaH+=`<div class="slbl">Visit history</div>`;
   mt.visits.forEach(v=>{
    metaH+=`<div class="cf" style="margin-bottom:4px">
     <div><div class="fl">Time</div><div class="fv mono">${esc(ft(v.time))}</div></div>
     <div><div class="fl">Hub</div><div class="fv">${esc(v.hub)}</div></div>
     <div><div class="fl">Status</div><div class="fv">${esc(v.status)}</div></div>
     <div><div class="fl">Type</div><div class="fv">${esc(v.type)}</div></div>
     ${v.at_home?'<div><div class="fl">At Home</div><div class="fv">Yes</div></div>':''}
    </div>`;
   });
  }
  if(mt.comments){
   metaH+=`<div class="slbl">CRM Comments</div>`;
   mt.comments.forEach(cm=>{
    metaH+=`<div class="cmt"><div class="cu">${esc(cm.user)} · ${esc(cm.date)}</div>${esc(cm.text)}</div>`;
   });
  }
  if(!metaH)metaH='<div style="color:var(--tf);font-style:italic;padding:8px">No metadata available for this call</div>';

  // POST panel (After Call) — reduced fields per user request
  const scn=(c.scenario||'').replace(/^S\d+_/,'').replace(/_/g,' ');
  const pf=[
   {l:'Milestone',v:ML[c.milestone]||c.milestone},
   {l:'Disposition',v:(c.dispose||'').replace(/_/g,' ')},
   {l:'Budget',v:c.budget?fp(+c.budget):''},
   {l:'Scenario',v:scn},
   {l:'Capability',v:c.capability},
   {l:'Liked cars',v:c.liked_cars,m:1},
   {l:'TD cars',v:c.td_cars,m:1},
   {l:'Selected TD slot',v:c.selected_td_slot?ft(c.selected_td_slot):''},
   {l:'Updated city',v:c.updated_city},
   {l:'Rescheduled time',v:c.rescheduled_time?ft(c.rescheduled_time):''},
   {l:'Cancel reason',v:c.cancel_reason},
   {l:'NDOA',v:c.ndoa?ft(c.ndoa):''},
  ].filter(f=>f.v);

  const flags=[
   c.car_pitched&&'Pitched',c.interested_for_td&&'TD Interest',c.interested_buying&&'Buying',
   c.interested_sell&&'Wants Sell',c.loan_interest&&'Loan',c.conversion&&'Converted',
   c.confirmed_visit&&'Visit OK',c.cancellation&&'Cancelled',c.rescheduled&&'Rescheduled',
   c.inconclusive&&'Inconclusive',c.mark_dnd&&'DND',c.soft_dnd&&'Soft DND',
   c.handoff&&'Handoff',c.lang_switch&&'Lang Switch',
  ].filter(Boolean);

  // User prefs collected in this call
  const up={};
  if(c.user_fuel)up['Fuel']=c.user_fuel;if(c.user_trans)up['Trans']=c.user_trans;
  if(c.user_body)up['Body']=c.user_body;if(c.user_make)up['Make']=c.user_make;
  if(c.user_model)up['Model']=c.user_model;if(c.user_color)up['Color']=c.user_color;
  if(c.user_seats&&c.user_seats!=='0')up['Seats']=c.user_seats;
  if(c.user_budget_min)up['Min Budget']=fp(+c.user_budget_min);
  if(c.user_budget_max)up['Max Budget']=fp(+c.user_budget_max);

  let postH='';
  if(flags.length)postH+=`<div class="slbl">Flags</div><div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">${flags.map(f=>{
   const bc=f==='DND'?'b-dn':f==='Soft DND'?'b-or':f==='Converted'?'b-ok':f==='Cancelled'?'b-dn':f.includes('Interest')||f==='Buying'?'b-ok':f==='Handoff'?'b-wn':'b-in';
   return`<span class="badge ${bc}">${esc(f)}</span>`;
  }).join('')}</div>`;
  if(pf.length)postH+=`<div class="slbl">Post-call details</div><div class="cf">${pf.map(f=>`<div><div class="fl">${esc(f.l)}</div><div class="fv ${f.m?'mono':''}">${esc(f.v)}</div></div>`).join('')}</div>`;
  if(Object.keys(up).length)postH+=`<div class="slbl">User prefs (collected this call)</div><div class="cf">${Object.entries(up).map(([k,v])=>`<div><div class="fl">${esc(k)}</div><div class="fv mono">${esc(v)}</div></div>`).join('')}</div>`;
  if(c.rejected_reasons)postH+=`<div class="slbl">Rejection reasons</div><div class="rbox"><b>Why: </b>${esc(c.rejected_reasons)}</div>`;
  if(c.review)postH+=`<div class="slbl">Review</div><div style="background:var(--s2);padding:8px 10px;border-radius:3px;font-size:12px">${esc(c.review)}</div>`;
  if(c.handoff_reason)postH+=`<div class="slbl">Handoff reason</div><div style="background:var(--wns);padding:8px 10px;border-radius:3px;font-size:12px">${esc(c.handoff_reason)}</div>`;

  // Transcript panel — scenario + ndoa status first, then recording, then transcript
  let txH='';
  txH+=`<div class="txstatus">
   <div class="item"><div class="k">Scenario</div><div class="v">${esc(scn)||'—'}</div></div>
   <div class="item"><div class="k">NDOA</div><div class="v">${c.ndoa?esc(ft(c.ndoa)):'—'}</div></div>
  </div>`;
  if(c.recording)txH+=`<div class="rec"><audio controls preload="none" src="${esc(c.recording)}"></audio><br><a href="${esc(c.recording)}" target="_blank">Open recording ↗</a></div>`;
  txH+=c.transcript?`<div class="txbox">${esc(c.transcript)}</div>`:'<div style="color:var(--tf);font-style:italic;padding:8px">No transcript</div>';

  const cid='c'+i+'_'+id.replace(/\W/g,'');
  return`<div class="call ${cls}">
   <div class="ch" data-cid="${cid}">
    <span class="cnum">${String(i+1).padStart(2,'0')}</span>
    <span class="ctm">${esc(ft(c.time))}</span>
    ${c.duration!=null?`<span class="cdur">${esc(fd(c.duration))}</span>`:''}
    <span class="badge ${c.connected?'b-ok':'b-ne'}">${c.connected?'Conn':'NC'}</span>
    <span class="badge ${hb}">${esc(hl)}</span>
    ${c.mark_dnd?'<span class="badge b-dn">DND</span>':''}
    ${c.soft_dnd?'<span class="badge b-or">Soft DND</span>':''}
    ${c.handoff?'<span class="badge b-wn">Handoff</span>':''}
    ${c.conversion?'<span class="badge b-ok">Converted</span>':''}
    <span class="cdisp">${esc(tr((c.dispose||'').replace(/_/g,' '),100))}</span>
    <span class="caret">▶</span>
   </div>
   <div class="cb">
    <div class="ctabs">
     <div class="ctab on" data-p="tx_${cid}">Transcript</div>
     <div class="ctab" data-p="meta_${cid}">Before Call</div>
     <div class="ctab" data-p="post_${cid}">After Call</div>
    </div>
    <div class="cpanel on" id="tx_${cid}">${txH}</div>
    <div class="cpanel" id="meta_${cid}">${metaH}</div>
    <div class="cpanel" id="post_${cid}">${postH||'<div style="color:var(--tf);font-style:italic;padding:8px">No post-call data</div>'}</div>
   </div>
  </div>`;
 }).join('');

 d.innerHTML=`<div class="di">
  <div class="dh">
   <div class="dt">${esc(l.id)}</div>
   <div class="ds">
    <span>${l.calls.length} call${l.calls.length===1?'':'s'}</span>
    <span class="sep">·</span><span>${cn} connected</span>
    ${l.city?`<span class="sep">·</span><span>${esc(l.city)}</span>`:''}
    ${m?`<span class="sep">·</span><span class="badge ${MB[m]||'b-ne'}">${esc(ML[m]||m)}</span>`:''}
   </div>
  </div>
  <div class="sec-h"><div class="sec-t">Call timeline</div><div class="sec-s">${l.calls.length} attempts, ${cn} connected</div></div>
  <div class="tl">${callsH}</div>
 </div>`;

 // Wire up call expand/collapse
 d.querySelectorAll('.call .ch').forEach(h=>h.onclick=()=>h.parentElement.classList.toggle('open'));
 // Wire up inner tabs
 d.querySelectorAll('.ctabs').forEach(tabs=>{
  tabs.querySelectorAll('.ctab').forEach(tab=>{
   tab.onclick=()=>{
    tabs.querySelectorAll('.ctab').forEach(t=>t.classList.remove('on'));
    tab.classList.add('on');
    const cb=tabs.parentElement;
    cb.querySelectorAll('.cpanel').forEach(p=>p.classList.remove('on'));
    const panel=cb.querySelector('#'+tab.dataset.p);
    if(panel)panel.classList.add('on');
   };
  });
 });
 // Auto-open first connected call
 const fo=d.querySelector('.call.conn')||d.querySelector('.call');
 if(fo)fo.classList.add('open');
 d.scrollTop=0;
}

let tm;
$('#q').oninput=()=>{clearTimeout(tm);tm=setTimeout(apply,100)};
$('#df').onchange=e=>{st.df=e.target.value||null;$('#dr').style.display=st.df?'inline-block':'none';apply();renderFil()};
$('#dr').onclick=()=>{$('#df').value='';st.df=null;$('#dr').style.display='none';apply();renderFil()};
$('#so').onchange=e=>{st.so=e.target.value;apply()};
(()=>{const ds=D.map(fcd).filter(Boolean).sort();if(ds.length){$('#df').min=ds[0];$('#df').max=ds[ds.length-1]}})();
renderFil();apply();
if(D.length)sel(D[0].id);
</script>
</body>
</html>"""


def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not csv_path or not csv_path.exists():
        print("Usage: python generate_viewer_v2.py call_history.csv")
        sys.exit(1)
    out_path = Path("index.html")

    print(f"Reading {csv_path}")
    df = pd.read_csv(csv_path, low_memory=False)
    print(f"  {len(df):,} rows, {len(df.columns)} cols")

    leads = build_leads(df)
    tc = sum(len(l["calls"]) for l in leads)
    cn = sum(1 for l in leads for c in l["calls"] if c["connected"])
    print(f"  {len(leads):,} leads, {tc:,} calls ({cn:,} connected)")

    data_json = json.dumps(leads, ensure_ascii=False, separators=(",", ":"))
    html = HTML.replace("__DATA__", data_json)

    print(f"Writing {out_path}")
    out_path.write_text(html, encoding="utf-8")
    print(f"  {os.path.getsize(out_path)/1024:.0f} KB — open in browser")

if __name__ == "__main__":
    main()
