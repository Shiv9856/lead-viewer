#!/usr/bin/env python3
"""
Lead Journey Viewer v3 — multi-page analytics.
Generates index.html (lead journey), analytics.html (dashboard), calls.html (date-range by new/followup).
Usage: python generate_viewer_v3.py call_history.csv
"""
import sys, os, json, ast, re
from pathlib import Path
import pandas as pd

CONNECTED_HANGUPS = {"CLIENT_INITIATED", "PARTICIPANT_REMOVED", "SESSION_TIMEOUT"}
MAX_TRANSCRIPT_CHARS = 10000

# ============================================================
# DATA EXTRACTION (same as v2 dark)
# ============================================================

def _c(v):
    if pd.isna(v): return None
    if isinstance(v, float) and v.is_integer(): return int(v)
    return v

def _s(v):
    if pd.isna(v) or v is None: return ""
    s = str(v).strip()
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
    p = {}
    for key in ("fuel_type", "transmission", "body_type", "color", "rto",
                 "make", "min_price", "max_price", "min_year", "max_year",
                 "min_mileage", "max_mileage", "no_of_owners"):
        v = _s(row.get(f"preferences.{prefix}.{key}"))
        if v: p[key] = v
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

        agent_prefs = _extract_prefs(row, "agent_filter_data")
        cust_prefs = _extract_prefs(row, "customer_filter_data")
        comments = _extract_comments(row)
        visits = _extract_visits(row)

        meta = {}
        if agent_prefs: meta["agent_prefs"] = agent_prefs
        if cust_prefs: meta["cust_prefs"] = cust_prefs
        if comments: meta["comments"] = comments
        if visits: meta["visits"] = visits

        vt = _s(row.get("visit_time"));   hub = _s(row.get("hub_name"));   vtype = _s(row.get("visit_type"))
        if vt: meta["visit_time"] = vt
        if vtype: meta["visit_type"] = vtype
        if hub: meta["hub_name"] = hub

        lcm = _s(row.get("last_call_milestone"))
        if lcm:
            meta["last_call"] = {
                "milestone": lcm,
                "disposition": _s(row.get("last_call_disposition")),
                "budget": _s(row.get("last_call_budget")),
            }

        intent = _s(row.get("preferences.customer_intent"))
        if intent: meta["intent"] = intent
        scenario = _s(row.get("added_scenario"))
        cap = _s(row.get("starting_capability"))

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
            "milestone": _s(row.get("milestone")),
            "ndoa": _s(row.get("ndoa")),
            "dispose": _s(row.get("dispose")),
            "cancel_reason": _s(row.get("cancellation_reason")),
            "rescheduled_time": _s(row.get("rescheduled_time")),
            "selected_td_slot": _s(row.get("selected_test_drive_slot")),
            "updated_city": _s(row.get("updated_city")),
            "review": _s(row.get("review")),
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

        t = call["transcript"]
        if len(t) > MAX_TRANSCRIPT_CHARS:
            call["transcript"] = t[:MAX_TRANSCRIPT_CHARS] + f"\n\n[… truncated, {len(t)-MAX_TRANSCRIPT_CHARS} more chars]"

        if lid not in leads:
            leads[lid] = {"id": lid, "city": _s(row.get("city")), "calls": []}
        leads[lid]["city"] = _s(row.get("city")) or leads[lid]["city"]
        leads[lid]["calls"].append(call)

    for lead in leads.values():
        lead["calls"].sort(key=lambda c: c.get("time") or c.get("date") or "")
    return list(leads.values())


# ============================================================
# HTML TEMPLATES — inline CSS/JS for self-contained output
# ============================================================

def load_shared():
    base = Path(__file__).parent
    css = (base / "shared.css").read_text(encoding="utf-8")
    js = (base / "shared.js").read_text(encoding="utf-8")
    return css, js

NAV_HTML = '''<header>
<div class="brand">Lead Journey</div>
<div class="nav">
 <a href="index.html" data-page="index">Leads</a>
 <a href="analytics.html" data-page="analytics">Analytics</a>
 <a href="calls.html" data-page="calls">Calls by Date</a>
</div>
__EXTRA_HEADER__
<button class="tog" id="themeTog" title="Toggle theme" aria-label="Toggle theme">
 <svg class="moon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
 <svg class="sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>
</button>
</header>'''

def page_head(title, active):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=IBM+Plex+Sans:wght@300;400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>__SHARED_CSS__
__PAGE_CSS__</style>
</head>
<body>
<div class="app">
__NAV__
__BODY__
</div>
<script>
const D=__DATA__;
__SHARED_JS__
// Mark active nav link
document.querySelectorAll('.nav a').forEach(a=>{{if(a.dataset.page==='{active}')a.classList.add('active')}});
__PAGE_JS__
wireThemeToggle();
</script>
</body>
</html>'''


# ============================================================
# PAGE 1: LEAD JOURNEY (index.html)
# ============================================================

INDEX_CSS = r"""
header .sbox{flex:1;max-width:380px;min-width:180px;position:relative}
.sbox input{width:100%;padding:8px 12px 8px 34px;border:1px solid var(--bds);background:var(--bg);color:var(--tx);border-radius:4px;font-family:inherit;font-size:13px;outline:none}
.sbox input:focus{border-color:var(--ac)}
.sbox::before{content:'';position:absolute;left:11px;top:50%;width:13px;height:13px;transform:translateY(-50%);background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%236B6458' stroke-width='2'><circle cx='11' cy='11' r='7'/><path d='m21 21-4.3-4.3'/></svg>");background-size:contain}
:root[data-theme="dark"] .sbox::before{background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%239E9688' stroke-width='2'><circle cx='11' cy='11' r='7'/><path d='m21 21-4.3-4.3'/></svg>")}
.filters{display:flex;gap:5px;flex-wrap:wrap}
.fch{padding:4px 10px;border:1px solid var(--bds);background:transparent;color:var(--tm);border-radius:18px;cursor:pointer;font-family:inherit;font-size:11px;transition:all .1s;white-space:nowrap}
.fch:hover{border-color:var(--tm);color:var(--tx)}.fch.on{background:var(--tx);color:var(--bg);border-color:var(--tx)}
.fch.on-ok{background:var(--ok);color:#fff;border-color:var(--ok)}.fch.on-wn{background:var(--wn);color:#fff;border-color:var(--wn)}
.fch.on-dn{background:var(--dn);color:#fff;border-color:var(--dn)}.fch.on-or{background:var(--or);color:#fff;border-color:var(--or)}
.hst{display:flex;gap:12px;align-items:center}
.hst>div.stat{text-align:right}.hst-v{font-family:'IBM Plex Mono',monospace;font-weight:500;font-size:14px}
.hst-l{font-size:9px;color:var(--tm);text-transform:uppercase;letter-spacing:.08em}
body{overflow:hidden}
.app{height:100vh}
main{flex:1;display:flex;overflow:hidden}
.sidebar{width:330px;min-width:330px;border-right:1px solid var(--bd);background:var(--s);overflow-y:auto;transition:background .2s,border-color .2s}
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
.detail{flex:1;overflow-y:auto;background:var(--bg);transition:background .2s}
.de{height:100%;display:flex;align-items:center;justify-content:center;color:var(--tf);font-family:'Instrument Serif',serif;font-style:italic;font-size:20px}
.di{padding:24px 36px;max-width:1020px}
.dh{margin-bottom:16px;padding-bottom:14px;border-bottom:1px solid var(--bd)}
.dt{font-family:'Instrument Serif',serif;font-size:34px;line-height:1.1}
.ds{color:var(--tm);font-size:12px;display:flex;flex-wrap:wrap;gap:5px 10px;align-items:center;margin-top:6px}
.ds .sep{color:var(--tf)}
.fg{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:10px 18px}
.fl{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf);margin-bottom:1px}
.fv{font-size:12px;word-break:break-word}.fv.mono{font-family:'IBM Plex Mono',monospace;font-size:11px}
.sec-h{display:flex;align-items:baseline;justify-content:space-between;margin:18px 0 12px}
.sec-t{font-family:'Instrument Serif',serif;font-style:italic;font-size:20px}
.sec-s{font-size:11px;color:var(--tm)}
.tl{position:relative;padding-left:22px}
.tl::before{content:'';position:absolute;left:5px;top:8px;bottom:8px;width:1px;background:var(--bds)}
.call{position:relative;background:var(--s);border:1px solid var(--bd);border-radius:4px;margin-bottom:8px;transition:background .2s,border-color .2s}
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
.ctabs{display:flex;gap:0;border-bottom:1px solid var(--bd);background:var(--s2)}
.ctab{padding:6px 12px;font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--tm);cursor:pointer;border-bottom:2px solid transparent}
.ctab:hover{color:var(--tx)}.ctab.on{color:var(--ac);border-bottom-color:var(--ac)}
.cpanel{display:none;padding:12px 16px}.cpanel.on{display:block}
.slbl{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf);margin-bottom:6px;margin-top:10px}
.slbl:first-child{margin-top:0}
.cf{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px 16px;margin-bottom:4px}
.rbox{background:var(--dns);border-left:2px solid var(--dn);padding:8px 10px;border-radius:0 3px 3px 0;font-size:12px;line-height:1.5}
.rbox b{color:var(--dn);font-weight:500}
.txbox{background:var(--s2);border-radius:3px;padding:10px 12px;font-family:'IBM Plex Mono',monospace;font-size:11px;line-height:1.8;white-space:pre-wrap;max-height:340px;overflow-y:auto;border-left:2px solid var(--ac);color:var(--tx)}
.txstatus{display:flex;gap:16px;padding:8px 12px;background:var(--s2);border-radius:3px;margin-bottom:8px;border-left:2px solid var(--in)}
.txstatus .item{display:flex;flex-direction:column;gap:2px}
.txstatus .item .k{font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf)}
.txstatus .item .v{font-size:12px;color:var(--tx);font-family:'IBM Plex Mono',monospace}
.rec{margin-bottom:8px}
.rec a{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:var(--in);text-decoration:none;margin-top:3px}
.rec a:hover{text-decoration:underline}
.rec audio{width:100%;height:36px}
:root[data-theme="dark"] .rec audio{filter:invert(0.9) hue-rotate(180deg)}
.none{padding:30px;text-align:center;color:var(--tf);font-style:italic}
.cmt{background:var(--s2);border-radius:3px;padding:8px 10px;font-size:12px;margin-bottom:4px;border-left:2px solid var(--wn)}
.cmt .cu{font-size:10px;color:var(--tm);margin-bottom:2px}
"""

INDEX_EXTRA_HEADER = '''<div class="sbox"><input id="q" type="text" placeholder="Search buylead, city, scenario…"></div>
<div class="filters" id="fil"></div>
<div class="dfl"><label>Date</label><input type="date" id="df"><button id="dr" style="display:none">×</button></div>
<div class="dfl"><label>Sort</label><select id="so">
 <option value="fca">First call ↑</option><option value="fcd">First call ↓</option>
 <option value="tc">Most calls</option><option value="cc">Most connected</option>
 <option value="ms">Milestone</option><option value="dur">Longest call</option><option value="tdur">Total talk</option>
</select></div>
<div class="hst">
 <div class="stat"><div class="hst-v" id="sL">0</div><div class="hst-l">Leads</div></div>
 <div class="stat"><div class="hst-v" id="sC">0</div><div class="hst-l">Calls</div></div>
 <div class="stat"><div class="hst-v" id="sCo">0</div><div class="hst-l">Connected</div></div>
</div>'''

INDEX_BODY = '''<main>
<aside class="sidebar"><div class="sh" id="sh">Leads</div><div id="list"></div></aside>
<section class="detail" id="det"><div class="de">Select a lead to see their journey</div></section>
</main>'''

INDEX_JS = r"""
const st={fil:D.map(l=>l.id),act:null,fk:'all',df:null,so:'fca'};
const mcd=l=>l.calls.filter(c=>c.connected&&c.duration).reduce((m,c)=>Math.max(m,c.duration),0);
const tcd=l=>l.calls.filter(c=>c.connected&&c.duration).reduce((s,c)=>s+c.duration,0);
const SF={fca:(a,b)=>firstCallTime(a)-firstCallTime(b),fcd:(a,b)=>firstCallTime(b)-firstCallTime(a),tc:(a,b)=>b.calls.length-a.calls.length,cc:(a,b)=>connectedCount(b)-connectedCount(a),ms:(a,b)=>(MO[lastMilestone(b)]||0)-(MO[lastMilestone(a)]||0),dur:(a,b)=>mcd(b)-mcd(a),tdur:(a,b)=>tcd(b)-tcd(a)};

function renderFil(){
 const fs=[
  {k:'all',l:'All',c:D.length},
  {k:'conn',l:'Connected',c:D.filter(everConnected).length,cl:'on-ok'},
  {k:'never',l:'Never conn',c:D.filter(l=>!everConnected(l)).length,cl:'on-wn'},
  {k:'handoff',l:'Handoff',c:D.filter(l=>l.calls.some(c=>c.handoff)).length},
  {k:'dnd',l:'DND',c:D.filter(l=>l.calls.some(c=>c.mark_dnd)).length,cl:'on-dn'},
  {k:'sdnd',l:'Soft DND',c:D.filter(l=>l.calls.some(c=>c.soft_dnd)).length,cl:'on-or'},
  {k:'td',l:'TD Sched',c:D.filter(l=>lastMilestone(l)==='test_drive_scheduled').length},
  {k:'pit',l:'Pitched',c:D.filter(l=>lastMilestone(l)==='car_pitched').length},
  {k:'conv',l:'Converted',c:D.filter(l=>l.calls.some(c=>c.conversion)).length,cl:'on-ok'},
 ];
 $('#fil').innerHTML=fs.map(f=>`<button class="fch ${st.fk===f.k?(f.cl||'on'):''}" data-k="${f.k}">${f.l} (${f.c})</button>`).join('');
 $('#fil').querySelectorAll('.fch').forEach(b=>b.onclick=()=>{st.fk=b.dataset.k;apply();renderFil()});
}

function apply(){
 const q=$('#q').value.trim().toLowerCase();
 st.fil=D.filter(l=>{
  if(st.fk==='conn'&&!everConnected(l))return false;
  if(st.fk==='never'&&everConnected(l))return false;
  if(st.fk==='handoff'&&!l.calls.some(c=>c.handoff))return false;
  if(st.fk==='dnd'&&!l.calls.some(c=>c.mark_dnd))return false;
  if(st.fk==='sdnd'&&!l.calls.some(c=>c.soft_dnd))return false;
  if(st.fk==='td'&&lastMilestone(l)!=='test_drive_scheduled')return false;
  if(st.fk==='pit'&&lastMilestone(l)!=='car_pitched')return false;
  if(st.fk==='conv'&&!l.calls.some(c=>c.conversion))return false;
  if(st.df&&firstCallDate(l)!==st.df)return false;
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
 $('#sCo').textContent=fl.reduce((s,l)=>s+connectedCount(l),0);
 if(!st.fil.length){ls.innerHTML='<div class="none">No matches</div>';return}
 ls.innerHTML=st.fil.map(id=>{
  const l=D.find(x=>x.id===id);const cn=connectedCount(l);const m=lastMilestone(l);
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
 const nice={'fuel_type':'Fuel','transmission':'Trans','body_type':'Body','color':'Color','rto':'RTO','make':'Make','min_price':'Min Price','max_price':'Max Price','min_year':'Min Year','max_year':'Max Year','min_mileage':'Min KM','max_mileage':'Max KM','no_of_owners':'Owners','city':'City'};
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
 const m=lastMilestone(l);const cn=connectedCount(l);

 const callsH=l.calls.map((c,i)=>{
  const cls=c.connected?'conn':'disc';
  const hl=HL[c.hangup]||c.hangup||'';
  const hb=HB[c.hangup]||'b-ne';
  const mt=c.meta||{};

  let metaH='';
  metaH+=prefGrid(mt.agent_prefs,'Agent preferences (before call)');
  metaH+=prefGrid(mt.cust_prefs,'Customer preferences (before call)');
  if(mt.last_call){
   const lc=mt.last_call;
   metaH+=`<div class="slbl">Last call context</div><div class="cf">
    ${lc.milestone?`<div><div class="fl">Milestone</div><div class="fv">${esc(lc.milestone)}</div></div>`:''}
    ${lc.disposition?`<div><div class="fl">Disposition</div><div class="fv">${esc(lc.disposition)}</div></div>`:''}
    ${lc.budget?`<div><div class="fl">Budget</div><div class="fv mono">${fp(+lc.budget)}</div></div>`:''}
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

  const scn=(c.scenario||'').replace(/^S\d+_/,'').replace(/_/g,' ');
  const pf=[
   {l:'Milestone',v:ML[c.milestone]||c.milestone},
   {l:'Disposition',v:(c.dispose||'').replace(/_/g,' ')},
   {l:'Budget',v:c.budget?fp(+c.budget):''},
   {l:'Scenario',v:scn},
   {l:'Capability',v:c.capability},
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

  let txH='';
  txH+=`<div class="txstatus"><div class="item"><div class="k">Scenario</div><div class="v">${esc(scn)||'—'}</div></div><div class="item"><div class="k">NDOA</div><div class="v">${c.ndoa?esc(ft(c.ndoa)):'—'}</div></div></div>`;
  if(c.recording)txH+=`<div class="rec"><audio controls preload="none" src="${esc(c.recording)}"></audio><br><a href="${esc(c.recording)}" target="_blank">Open recording ↗</a></div>`;
  txH+=c.transcript?`<div class="txbox">${esc(c.transcript)}</div>`:'<div style="color:var(--tf);font-style:italic;padding:8px">No transcript</div>';

  const cid='c'+i+'_'+id.replace(/\W/g,'');
  return`<div class="call ${cls}">
   <div class="ch" data-cid="${cid}">
    <span class="cnum">${String(i+1).padStart(2,'0')}</span>
    <span class="ctm">${esc(ft(c.time))}</span>
    ${c.duration!=null?`<span class="cdur">${esc(fdur(c.duration))}</span>`:''}
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
  <div class="dh"><div class="dt">${esc(l.id)}</div><div class="ds">
   <span>${l.calls.length} call${l.calls.length===1?'':'s'}</span>
   <span class="sep">·</span><span>${cn} connected</span>
   ${l.city?`<span class="sep">·</span><span>${esc(l.city)}</span>`:''}
   ${m?`<span class="sep">·</span><span class="badge ${MB[m]||'b-ne'}">${esc(ML[m]||m)}</span>`:''}
  </div></div>
  <div class="sec-h"><div class="sec-t">Call timeline</div><div class="sec-s">${l.calls.length} attempts, ${cn} connected</div></div>
  <div class="tl">${callsH}</div>
 </div>`;

 d.querySelectorAll('.call .ch').forEach(h=>h.onclick=()=>h.parentElement.classList.toggle('open'));
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
 const fo=d.querySelector('.call.conn')||d.querySelector('.call');
 if(fo)fo.classList.add('open');
 d.scrollTop=0;
}

let tm;
$('#q').oninput=()=>{clearTimeout(tm);tm=setTimeout(apply,100)};
$('#df').onchange=e=>{st.df=e.target.value||null;$('#dr').style.display=st.df?'inline-block':'none';apply();renderFil()};
$('#dr').onclick=()=>{$('#df').value='';st.df=null;$('#dr').style.display='none';apply();renderFil()};
$('#so').onchange=e=>{st.so=e.target.value;apply()};
(()=>{const ds=D.map(firstCallDate).filter(Boolean).sort();if(ds.length){$('#df').min=ds[0];$('#df').max=ds[ds.length-1]}})();


renderFil(); apply();

function initFromHash() {
  const hashId = window.location.hash.slice(1); 
  if (hashId) {
    const decoded = decodeURIComponent(hashId);
    const match = D.find(l => l.id === decoded);
    if (match) {
      
      if (!st.fil.includes(decoded)) {
        st.fk = 'all';
        apply();
        renderFil();
      }
      sel(decoded);
      // Scroll sidebar to the active item
      setTimeout(() => {
        const active = document.querySelector('.li.act');
        if (active) active.scrollIntoView({ block: 'center' });
      }, 50);
      return true;
    }
  }
  return false;
}

if (!initFromHash() && D.length) sel(D[0].id);

// Also listen for hash changes (e.g., browser back/forward)
window.addEventListener('hashchange', () => initFromHash());

"""


def build_index(shared_css, shared_js, data_json):
    nav = NAV_HTML.replace("__EXTRA_HEADER__", INDEX_EXTRA_HEADER)
    html = page_head("Leads — Lead Journey", "index")
    html = html.replace("__SHARED_CSS__", shared_css)
    html = html.replace("__PAGE_CSS__", INDEX_CSS)
    html = html.replace("__NAV__", nav)
    html = html.replace("__BODY__", INDEX_BODY)
    html = html.replace("__DATA__", data_json)
    html = html.replace("__SHARED_JS__", shared_js)
    html = html.replace("__PAGE_JS__", INDEX_JS)
    return html


# ============================================================
# PAGE 2: ANALYTICS (analytics.html)
# ============================================================

ANALYTICS_CSS = r"""
.wrap{padding:24px 36px;max-width:1280px;margin:0 auto}
.page-title{font-family:'Instrument Serif',serif;font-size:36px;line-height:1.1;margin-bottom:6px}
.page-sub{color:var(--tm);font-size:13px;margin-bottom:24px}
.range-ctl{display:flex;gap:12px;align-items:center;padding:12px 16px;background:var(--s);border:1px solid var(--bd);border-radius:6px;margin-bottom:20px;flex-wrap:wrap}
.range-ctl .grp{display:flex;align-items:center;gap:6px}
.range-ctl label{font-size:11px;color:var(--tm);text-transform:uppercase;letter-spacing:.08em}
.range-ctl input{padding:5px 9px;border:1px solid var(--bds);border-radius:4px;font-family:inherit;font-size:12px;background:var(--bg);color:var(--tx);outline:none}
.range-ctl button{padding:5px 11px;border:1px solid var(--bds);background:transparent;color:var(--tm);border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit}
.range-ctl button:hover{border-color:var(--ac);color:var(--ac)}
.range-ctl button.active{background:var(--ac);color:#fff;border-color:var(--ac)}

.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}
.kpi{background:var(--s);border:1px solid var(--bd);border-radius:6px;padding:16px 18px;transition:border-color .15s}
.kpi:hover{border-color:var(--ac)}
.kpi .k-label{font-size:10px;color:var(--tf);text-transform:uppercase;letter-spacing:.1em;margin-bottom:6px}
.kpi .k-val{font-family:'Instrument Serif',serif;font-size:32px;line-height:1;color:var(--tx)}
.kpi .k-sub{font-size:11px;color:var(--tm);margin-top:4px}
.kpi .k-trend{display:inline-block;font-size:10px;padding:1px 6px;border-radius:3px;margin-left:6px;font-family:'IBM Plex Mono',monospace}
.kpi .k-up{background:var(--oks);color:var(--ok)}
.kpi .k-dn{background:var(--dns);color:var(--dn)}

.card{background:var(--s);border:1px solid var(--bd);border-radius:6px;padding:18px 20px;margin-bottom:16px}
.card-h{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:14px}
.card-t{font-family:'Instrument Serif',serif;font-style:italic;font-size:20px}
.card-s{font-size:11px;color:var(--tm)}

.tabs{display:flex;gap:0;border-bottom:1px solid var(--bd);margin-bottom:16px}
.tab{padding:9px 18px;font-size:12px;color:var(--tm);cursor:pointer;border-bottom:2px solid transparent;transition:all .1s;font-family:inherit;background:none;border-top:none;border-left:none;border-right:none}
.tab:hover{color:var(--tx)}
.tab.on{color:var(--ac);border-bottom-color:var(--ac);font-weight:500}
.panel{display:none}.panel.on{display:block}

/* Funnel */
.funnel{display:flex;flex-direction:column;gap:2px;padding:8px 0}
.f-row{display:flex;align-items:center;gap:12px;padding:6px 0}
.f-label{width:160px;font-size:12px;color:var(--tx);font-weight:500}
.f-bar-wrap{flex:1;position:relative;height:30px;background:var(--s2);border-radius:3px;overflow:hidden}
.f-bar{height:100%;background:linear-gradient(90deg,var(--ac) 0%,var(--ac) 100%);opacity:.85;transition:width .3s ease}
.f-bar.s2{background:var(--in)}.f-bar.s3{background:var(--ok)}.f-bar.s4{background:var(--wn)}.f-bar.s5{background:var(--dn)}
.f-val{position:absolute;left:10px;top:50%;transform:translateY(-50%);font-family:'IBM Plex Mono',monospace;font-size:12px;color:#fff;font-weight:500;text-shadow:0 1px 2px rgba(0,0,0,.3)}
.f-pct{width:90px;font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--tm);text-align:right}

/* Charts */
.chart-wrap{position:relative;height:260px;margin-top:8px}
.chart-legend{display:flex;flex-wrap:wrap;gap:12px;margin-top:10px;font-size:11px;color:var(--tm)}
.chart-legend .lg-item{display:flex;align-items:center;gap:5px}
.chart-legend .lg-sw{width:10px;height:10px;border-radius:2px}

svg.chart{width:100%;height:100%;overflow:visible}
svg.chart .axis-line{stroke:var(--bds);stroke-width:1}
svg.chart .grid-line{stroke:var(--bd);stroke-width:.5;stroke-dasharray:2,3}
svg.chart .axis-label{fill:var(--tf);font-size:10px;font-family:'IBM Plex Mono',monospace}
svg.chart .axis-title{fill:var(--tm);font-size:10px;text-transform:uppercase;letter-spacing:.08em}
svg.chart .bar{transition:opacity .15s}
svg.chart .bar:hover{opacity:.75}
svg.chart .line{fill:none;stroke-width:2;stroke-linejoin:round;stroke-linecap:round}
svg.chart .dot{transition:r .15s}
svg.chart .dot:hover{r:5}
svg.chart .area{opacity:.15}

.tooltip{position:absolute;background:var(--tx);color:var(--bg);padding:6px 10px;border-radius:4px;font-size:11px;font-family:'IBM Plex Mono',monospace;pointer-events:none;opacity:0;transition:opacity .1s;white-space:nowrap;z-index:10}
.tooltip.vis{opacity:1}

.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:900px){.grid-2{grid-template-columns:1fr}}

.empty-state{text-align:center;padding:40px 20px;color:var(--tf);font-style:italic;font-family:'Instrument Serif',serif;font-size:18px}
"""

ANALYTICS_BODY = '''<div class="wrap">
<div class="page-title">Analytics</div>
<div class="page-sub">Funnels, daily trends, and engagement patterns across your lead pipeline.</div>

<div class="range-ctl">
 <div class="grp"><label>From</label><input type="date" id="rFrom"></div>
 <div class="grp"><label>To</label><input type="date" id="rTo"></div>
 <div class="grp" style="margin-left:auto">
  <button data-preset="7">Last 7 days</button>
  <button data-preset="14">Last 14 days</button>
  <button data-preset="all" class="active">All</button>
 </div>
</div>

<div class="kpi-row" id="kpis"></div>

<div class="card">
 <div class="card-h"><div class="card-t">Conversion funnel</div><div class="card-s">Flow of leads & calls through each stage</div></div>
 <div class="tabs">
  <button class="tab on" data-tab="f-stage">Lead stage</button>
  <button class="tab" data-tab="f-call">Call outcome</button>
  <button class="tab" data-tab="f-intent">Intent</button>
 </div>
 <div class="panel on" id="f-stage"></div>
 <div class="panel" id="f-call"></div>
 <div class="panel" id="f-intent"></div>
</div>

<div class="grid-2">
 <div class="card">
  <div class="card-h"><div class="card-t">Daily call volume</div><div class="card-s">Attempted vs Connected</div></div>
  <div class="chart-wrap"><svg class="chart" id="ch-volume"></svg></div>
  <div class="chart-legend">
   <div class="lg-item"><span class="lg-sw" style="background:var(--bds)"></span>Attempted</div>
   <div class="lg-item"><span class="lg-sw" style="background:var(--ok)"></span>Connected</div>
  </div>
 </div>

 <div class="card">
  <div class="card-h"><div class="card-t">Daily conversion rate</div><div class="card-s">Calls → TD booked</div></div>
  <div class="chart-wrap"><svg class="chart" id="ch-conv"></svg></div>
  <div class="chart-legend">
   <div class="lg-item"><span class="lg-sw" style="background:var(--ac)"></span>Conv rate (%)</div>
  </div>
 </div>
</div>

<div class="card">
 <div class="card-h"><div class="card-t">Milestone distribution over time</div><div class="card-s">Stacked area of which milestone calls reach each day</div></div>
 <div class="chart-wrap" style="height:300px"><svg class="chart" id="ch-ms"></svg></div>
 <div class="chart-legend" id="ch-ms-lg"></div>
</div>

<div class="card">
 <div class="card-h"><div class="card-t">Avg call duration trend</div><div class="card-s">Mean duration of connected calls per day</div></div>
 <div class="chart-wrap"><svg class="chart" id="ch-dur"></svg></div>
 <div class="chart-legend">
  <div class="lg-item"><span class="lg-sw" style="background:var(--in)"></span>Avg duration (connected)</div>
 </div>
</div>

<div class="tooltip" id="tt"></div>
</div>'''

ANALYTICS_JS = r"""
// ---- state ----
const ast={from:null,to:null,preset:'all'};
const allBuckets=buildDailyBuckets(D);
const allDates=allBuckets.map(b=>b.date);
const minD=allDates[0]||fdate(new Date());
const maxD=allDates[allDates.length-1]||fdate(new Date());

// ---- date range controls ----
$('#rFrom').min=minD;$('#rFrom').max=maxD;
$('#rTo').min=minD;$('#rTo').max=maxD;

function setPreset(p){
 ast.preset=p;
 document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.classList.toggle('active',b.dataset.preset===p));
 if(p==='all'){ast.from=minD;ast.to=maxD}
 else{
  const n=parseInt(p);
  const end=new Date(maxD);
  const start=new Date(end);start.setDate(start.getDate()-n+1);
  const startStr=fdate(start);
  ast.from=startStr<minD?minD:startStr;
  ast.to=maxD;
 }
 $('#rFrom').value=ast.from;$('#rTo').value=ast.to;
 render();
}

$('#rFrom').onchange=e=>{ast.from=e.target.value||minD;ast.preset='';document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.classList.remove('active'));render()};
$('#rTo').onchange=e=>{ast.to=e.target.value||maxD;ast.preset='';document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.classList.remove('active'));render()};
document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.onclick=()=>setPreset(b.dataset.preset));

// tabs
document.querySelectorAll('.tabs .tab').forEach(t=>{
 t.onclick=()=>{
  document.querySelectorAll('.tabs .tab').forEach(x=>x.classList.remove('on'));
  t.classList.add('on');
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('on'));
  $('#'+t.dataset.tab).classList.add('on');
 };
});

// ---- filtered buckets ----
function getFiltered(){
 return allBuckets.filter(b=>(!ast.from||b.date>=ast.from)&&(!ast.to||b.date<=ast.to));
}

// ---- FUNNEL BUILDERS ----
function buildStageFunnel(buckets){
 // Lead stage: count leads (unique) whose best milestone reaches each stage within the range
 const leadIds=new Set();
 buckets.forEach(b=>b.calls.forEach(c=>leadIds.add(c.leadId)));
 const leads=D.filter(l=>leadIds.has(l.id));
 const bestMS={};
 leads.forEach(l=>{
  let best=0,bestKey='';
  l.calls.forEach(c=>{
   const inRange=buckets.some(b=>b.calls.some(bc=>bc.leadId===l.id&&callDate(c)===b.date));
   if(!inRange)return;
   const ord=MO[c.milestone]||0;
   if(ord>best){best=ord;bestKey=c.milestone}
  });
  bestMS[l.id]={best,bestKey};
 });
 const count=ms=>Object.values(bestMS).filter(x=>(MO[x.bestKey]||0)>=(MO[ms]||0)).length;
 const conv=leads.filter(l=>l.calls.some(c=>c.conversion&&buckets.some(b=>b.date===callDate(c)))).length;
 return [
  {label:'Fresh',val:count('fresh_lead')+Object.values(bestMS).filter(x=>!x.bestKey).length},
  {label:'Minimal',val:count('minimal_engagement')},
  {label:'Prefs',val:count('preference_collected')},
  {label:'Pitched',val:count('car_pitched')},
  {label:'TD Sched',val:count('test_drive_scheduled')},
  {label:'Converted',val:conv},
 ];
}

function buildCallFunnel(buckets){
 const calls=buckets.flatMap(b=>b.calls);
 return [
  {label:'Attempted',val:calls.length},
  {label:'Connected',val:calls.filter(c=>c.connected).length},
  {label:'Engaged',val:calls.filter(c=>c.connected&&c.milestone&&c.milestone!=='fresh_lead').length},
  {label:'Pitched',val:calls.filter(c=>c.car_pitched).length},
  {label:'Converted',val:calls.filter(c=>c.conversion).length},
 ];
}

function buildIntentFunnel(buckets){
 const leadIds=new Set();
 buckets.forEach(b=>b.calls.forEach(c=>leadIds.add(c.leadId)));
 const leads=D.filter(l=>leadIds.has(l.id));
 const rCalls=l=>l.calls.filter(c=>buckets.some(b=>b.date===callDate(c)));
 return [
  {label:'All leads',val:leads.length},
  {label:'Interested',val:leads.filter(l=>rCalls(l).some(c=>c.interested_buying)).length},
  {label:'TD booked',val:leads.filter(l=>rCalls(l).some(c=>c.interested_for_td)).length},
  {label:'TD visited',val:leads.filter(l=>rCalls(l).some(c=>c.confirmed_visit)).length},
 ];
}

function renderFunnel(containerId,rows,klass){
 const max=rows.length?rows[0].val:0;
 const c=$('#'+containerId);
 if(!max){c.innerHTML='<div class="empty-state">No data in selected range</div>';return}
 c.innerHTML='<div class="funnel">'+rows.map((r,i)=>{
  const pct=max?(r.val/max*100).toFixed(0):0;
  const overall=max?(r.val/max*100).toFixed(1):0;
  return `<div class="f-row"><div class="f-label">${esc(r.label)}</div>
   <div class="f-bar-wrap"><div class="f-bar s${(i%5)+1}" style="width:${pct}%"></div><div class="f-val">${r.val}</div></div>
   <div class="f-pct">${overall}%</div></div>`;
 }).join('')+'</div>';
}

// ---- KPIs ----
function renderKPIs(buckets){
 const calls=buckets.flatMap(b=>b.calls);
 const leadIds=new Set();calls.forEach(c=>leadIds.add(c.leadId));
 const totalCalls=calls.length;
 const conn=calls.filter(c=>c.connected).length;
 const connPct=totalCalls?(conn/totalCalls*100).toFixed(1):0;
 const conv=calls.filter(c=>c.conversion).length;
 const convPct=conn?(conv/conn*100).toFixed(1):0;
 const avgDur=conn?(calls.filter(c=>c.connected&&c.duration).reduce((s,c)=>s+c.duration,0)/conn):0;
 const dnd=calls.filter(c=>c.mark_dnd).length;
 const handoff=calls.filter(c=>c.handoff).length;
 const pitched=calls.filter(c=>c.car_pitched).length;

 const kpis=[
  {k:'Leads reached',v:leadIds.size,sub:`${buckets.length} day${buckets.length===1?'':'s'}`},
  {k:'Total calls',v:totalCalls.toLocaleString(),sub:`${conn} connected · ${connPct}%`},
  {k:'Conversion rate',v:convPct+'%',sub:`${conv} of ${conn} connected`},
  {k:'Avg call duration',v:fdur(avgDur),sub:'connected calls'},
  {k:'Pitched',v:pitched,sub:totalCalls?`${(pitched/totalCalls*100).toFixed(0)}% of calls`:''},
  {k:'DND + Handoff',v:dnd+handoff,sub:`${dnd} DND · ${handoff} handoff`},
 ];
 $('#kpis').innerHTML=kpis.map(k=>`<div class="kpi"><div class="k-label">${esc(k.k)}</div><div class="k-val">${esc(String(k.v))}</div><div class="k-sub">${esc(k.sub)}</div></div>`).join('');
}

// ---- SVG chart helpers ----
function getCSSVar(name){return getComputedStyle(document.documentElement).getPropertyValue(name).trim()}

function renderBarLineChart(svgId,buckets,opts){
 const svg=$('#'+svgId);
 if(!buckets.length){svg.innerHTML=`<text x="50%" y="50%" text-anchor="middle" class="axis-label">No data in selected range</text>`;return}
 const w=svg.clientWidth||600;const h=svg.clientHeight||260;
 const M={t:12,r:14,b:32,l:38};
 const iw=w-M.l-M.r;const ih=h-M.t-M.b;
 const series=opts.series(buckets);
 // compute max y
 let maxY=0;series.forEach(s=>s.values.forEach(v=>{if(v>maxY)maxY=v}));
 if(maxY===0)maxY=1;
 const pad=Math.ceil(maxY*.1);maxY=Math.ceil((maxY+pad)/5)*5||maxY;
 const xBand=iw/buckets.length;
 const xpos=i=>M.l+xBand*i+xBand/2;
 const ypos=v=>M.t+ih-(v/maxY)*ih;
 let out='';
 // gridlines
 for(let i=0;i<=4;i++){const v=maxY*i/4;const y=ypos(v);
  out+=`<line class="grid-line" x1="${M.l}" y1="${y}" x2="${w-M.r}" y2="${y}"/>`;
  out+=`<text class="axis-label" x="${M.l-6}" y="${y+3}" text-anchor="end">${Math.round(v).toLocaleString()}${opts.yUnit||''}</text>`;
 }
 // x labels (only some)
 const step=Math.max(1,Math.ceil(buckets.length/8));
 buckets.forEach((b,i)=>{
  if(i%step===0||i===buckets.length-1){
   const x=xpos(i);const d=pd(b.date+' 00:00:00')||new Date(b.date);
   const lbl=d?d.toLocaleDateString('en-IN',{day:'2-digit',month:'short'}):b.date;
   out+=`<text class="axis-label" x="${x}" y="${h-M.b+14}" text-anchor="middle">${lbl}</text>`;
  }
 });
 // axis lines
 out+=`<line class="axis-line" x1="${M.l}" y1="${h-M.b}" x2="${w-M.r}" y2="${h-M.b}"/>`;
 // series
 const barW=Math.max(1,xBand*.7);
 series.forEach((s,si)=>{
  if(s.type==='bar'){
   s.values.forEach((v,i)=>{
    const x=xpos(i)-barW/2+(si*barW/series.filter(x=>x.type==='bar').length);
    const bw=barW/series.filter(x=>x.type==='bar').length;
    const y=ypos(v);
    out+=`<rect class="bar" x="${x}" y="${y}" width="${bw-1}" height="${h-M.b-y}" fill="${s.color}" data-tip="${esc(buckets[i].date)}: ${v}${opts.yUnit||''} (${s.label})"/>`;
   });
  }else if(s.type==='line'){
   const path=s.values.map((v,i)=>`${i===0?'M':'L'}${xpos(i)},${ypos(v)}`).join(' ');
   out+=`<path class="line" d="${path}" stroke="${s.color}"/>`;
   s.values.forEach((v,i)=>{
    out+=`<circle class="dot" cx="${xpos(i)}" cy="${ypos(v)}" r="3" fill="${s.color}" data-tip="${esc(buckets[i].date)}: ${v}${opts.yUnit||''} (${s.label})"/>`;
   });
  }
 });
 svg.innerHTML=out;
 wireTooltips(svg);
}

function renderStackedArea(svgId,buckets,opts){
 const svg=$('#'+svgId);
 if(!buckets.length){svg.innerHTML=`<text x="50%" y="50%" text-anchor="middle" class="axis-label">No data in selected range</text>`;return}
 const w=svg.clientWidth||600;const h=svg.clientHeight||300;
 const M={t:12,r:14,b:32,l:38};
 const iw=w-M.l-M.r;const ih=h-M.t-M.b;
 const keys=opts.keys;const colors=opts.colors;
 // build stacked values
 const stacks=buckets.map(b=>{
  const o={};keys.forEach(k=>o[k]=opts.getValue(b,k));return o;
 });
 const totals=stacks.map(s=>keys.reduce((a,k)=>a+s[k],0));
 let maxY=Math.max(1,...totals);
 maxY=Math.ceil(maxY/5)*5||maxY;
 const xBand=iw/buckets.length;
 const xpos=i=>M.l+xBand*i+xBand/2;
 const ypos=v=>M.t+ih-(v/maxY)*ih;
 let out='';
 for(let i=0;i<=4;i++){const v=maxY*i/4;const y=ypos(v);
  out+=`<line class="grid-line" x1="${M.l}" y1="${y}" x2="${w-M.r}" y2="${y}"/>`;
  out+=`<text class="axis-label" x="${M.l-6}" y="${y+3}" text-anchor="end">${Math.round(v).toLocaleString()}</text>`;
 }
 const step=Math.max(1,Math.ceil(buckets.length/8));
 buckets.forEach((b,i)=>{
  if(i%step===0||i===buckets.length-1){
   const x=xpos(i);const d=pd(b.date+' 00:00:00')||new Date(b.date);
   const lbl=d?d.toLocaleDateString('en-IN',{day:'2-digit',month:'short'}):b.date;
   out+=`<text class="axis-label" x="${x}" y="${h-M.b+14}" text-anchor="middle">${lbl}</text>`;
  }
 });
 out+=`<line class="axis-line" x1="${M.l}" y1="${h-M.b}" x2="${w-M.r}" y2="${h-M.b}"/>`;
 // draw stacked areas (bottom to top)
 let accum=buckets.map(()=>0);
 keys.forEach((k,ki)=>{
  const top=stacks.map((s,i)=>accum[i]+s[k]);
  const btm=accum.slice();
  let d=`M${xpos(0)},${ypos(top[0])}`;
  for(let i=1;i<buckets.length;i++)d+=` L${xpos(i)},${ypos(top[i])}`;
  for(let i=buckets.length-1;i>=0;i--)d+=` L${xpos(i)},${ypos(btm[i])}`;
  d+=' Z';
  out+=`<path d="${d}" fill="${colors[ki]}" opacity=".7"/>`;
  accum=top;
 });
 // hover hit zones
 buckets.forEach((b,i)=>{
  const parts=keys.map(k=>`${opts.labels[k]||k}: ${stacks[i][k]}`).filter((_,idx)=>stacks[i][keys[idx]]>0);
  const tip=`${b.date} — ${parts.join(', ')||'no data'}`;
  out+=`<rect x="${M.l+xBand*i}" y="${M.t}" width="${xBand}" height="${ih}" fill="transparent" data-tip="${esc(tip)}"/>`;
 });
 svg.innerHTML=out;
 wireTooltips(svg);
}

function wireTooltips(svg){
 const tt=$('#tt');
 svg.querySelectorAll('[data-tip]').forEach(el=>{
  el.addEventListener('mousemove',e=>{
   tt.textContent=el.dataset.tip;
   tt.style.left=(e.pageX+10)+'px';
   tt.style.top=(e.pageY-28)+'px';
   tt.classList.add('vis');
  });
  el.addEventListener('mouseleave',()=>tt.classList.remove('vis'));
 });
}

// ---- Chart builders ----
function renderVolume(buckets){
 renderBarLineChart('ch-volume',buckets,{
  series:bs=>[
   {type:'bar',label:'Attempted',values:bs.map(b=>b.calls.length),color:getCSSVar('--bds')},
   {type:'bar',label:'Connected',values:bs.map(b=>b.calls.filter(c=>c.connected).length),color:getCSSVar('--ok')},
  ]
 });
}

function renderConv(buckets){
 renderBarLineChart('ch-conv',buckets,{
  yUnit:'%',
  series:bs=>[
   {type:'line',label:'Conv rate',values:bs.map(b=>{const conn=b.calls.filter(c=>c.connected).length;const td=b.calls.filter(c=>c.conversion).length;return conn?+(td/conn*100).toFixed(1):0}),color:getCSSVar('--ac')},
  ]
 });
}

function renderDur(buckets){
 renderBarLineChart('ch-dur',buckets,{
  yUnit:'s',
  series:bs=>[
   {type:'line',label:'Avg duration',values:bs.map(b=>{const c=b.calls.filter(c=>c.connected&&c.duration);return c.length?Math.round(c.reduce((s,c)=>s+c.duration,0)/c.length):0}),color:getCSSVar('--in')},
  ]
 });
}

function renderMilestone(buckets){
 const keys=['fresh_lead','minimal_engagement','preference_collected','car_pitched','test_drive_scheduled'];
 const colors=[getCSSVar('--bds'),getCSSVar('--wn'),getCSSVar('--in'),getCSSVar('--or'),getCSSVar('--ok')];
 const labels={fresh_lead:'Fresh',minimal_engagement:'Minimal',preference_collected:'Prefs',car_pitched:'Pitched',test_drive_scheduled:'TD Sched'};
 renderStackedArea('ch-ms',buckets,{keys,colors,labels,getValue:(b,k)=>b.calls.filter(c=>c.milestone===k).length});
 $('#ch-ms-lg').innerHTML=keys.map((k,i)=>`<div class="lg-item"><span class="lg-sw" style="background:${colors[i]}"></span>${labels[k]}</div>`).join('');
}

// ---- MASTER RENDER ----
function render(){
 const buckets=getFiltered();
 renderKPIs(buckets);
 renderFunnel('f-stage',buildStageFunnel(buckets));
 renderFunnel('f-call',buildCallFunnel(buckets));
 renderFunnel('f-intent',buildIntentFunnel(buckets));
 // charts need next tick for width to be set
 requestAnimationFrame(()=>{
  renderVolume(buckets);
  renderConv(buckets);
  renderMilestone(buckets);
  renderDur(buckets);
 });
}

// re-render charts on resize & theme change
let rsz;window.addEventListener('resize',()=>{clearTimeout(rsz);rsz=setTimeout(render,150)});
new MutationObserver(()=>render()).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});

setPreset('all');
"""

def build_analytics(shared_css, shared_js, data_json):
    nav = NAV_HTML.replace("__EXTRA_HEADER__", "")
    html = page_head("Analytics — Lead Journey", "analytics")
    html = html.replace("__SHARED_CSS__", shared_css)
    html = html.replace("__PAGE_CSS__", ANALYTICS_CSS)
    html = html.replace("__NAV__", nav)
    html = html.replace("__BODY__", ANALYTICS_BODY)
    html = html.replace("__DATA__", data_json)
    html = html.replace("__SHARED_JS__", shared_js)
    html = html.replace("__PAGE_JS__", ANALYTICS_JS)
    return html


# ============================================================
# PAGE 3: CALLS BY DATE (calls.html)
# ============================================================

CALLS_CSS = r"""
.wrap{padding:24px 36px;max-width:1280px;margin:0 auto}
.page-title{font-family:'Instrument Serif',serif;font-size:36px;line-height:1.1;margin-bottom:6px}
.page-sub{color:var(--tm);font-size:13px;margin-bottom:20px}

.range-ctl{display:flex;gap:12px;align-items:center;padding:12px 16px;background:var(--s);border:1px solid var(--bd);border-radius:6px;margin-bottom:20px;flex-wrap:wrap}
.range-ctl .grp{display:flex;align-items:center;gap:6px}
.range-ctl label{font-size:11px;color:var(--tm);text-transform:uppercase;letter-spacing:.08em}
.range-ctl input{padding:5px 9px;border:1px solid var(--bds);border-radius:4px;font-family:inherit;font-size:12px;background:var(--bg);color:var(--tx);outline:none}
.range-ctl button{padding:5px 11px;border:1px solid var(--bds);background:transparent;color:var(--tm);border-radius:4px;cursor:pointer;font-size:11px;font-family:inherit}
.range-ctl button:hover{border-color:var(--ac);color:var(--ac)}
.range-ctl button.active{background:var(--ac);color:#fff;border-color:var(--ac)}

.day-card{background:var(--s);border:1px solid var(--bd);border-radius:6px;margin-bottom:16px;overflow:hidden}
.day-head{padding:14px 18px;display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--bd);background:var(--s2);flex-wrap:wrap}
.day-date{font-family:'Instrument Serif',serif;font-size:22px;font-weight:400}
.day-weekday{font-size:11px;color:var(--tm);text-transform:uppercase;letter-spacing:.08em;margin-left:-8px}
.day-stats{display:flex;gap:12px;margin-left:auto;font-size:11px;color:var(--tm);flex-wrap:wrap}
.day-stats .s-item{display:flex;align-items:center;gap:4px}
.day-stats .s-val{font-family:'IBM Plex Mono',monospace;color:var(--tx);font-weight:500}

.split{display:grid;grid-template-columns:1fr 1fr;gap:0}
@media (max-width:860px){.split{grid-template-columns:1fr}}
.split-col{padding:0}
.split-col:first-child{border-right:1px solid var(--bd)}
@media (max-width:860px){.split-col:first-child{border-right:none;border-bottom:1px solid var(--bd)}}
.split-h{padding:10px 18px;background:var(--s);border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:8px;position:sticky}
.split-h .tit{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--tf);font-weight:500}
.split-h .cnt{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--tm);margin-left:auto}
.split-h .icon{width:14px;height:14px;color:var(--tm);display:inline-flex}
.split-h .icon svg{width:100%;height:100%;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.new-bar{border-left:3px solid var(--ok)}
.fol-bar{border-left:3px solid var(--in)}

.call-row{padding:10px 18px;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:10px;font-size:12px;flex-wrap:wrap;cursor:pointer;transition:background .08s}
.call-row:hover{background:var(--s2)}
.call-row:last-child{border-bottom:none}
.cr-time{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--tx);min-width:42px}
.cr-lead{font-family:'IBM Plex Mono',monospace;font-size:11px;color:var(--ac);font-weight:500;min-width:78px}
.cr-lead:hover{text-decoration:underline}
.cr-city{color:var(--tm);font-size:11px;max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.cr-dur{font-family:'IBM Plex Mono',monospace;font-size:10px;color:var(--tm);padding:1px 5px;background:var(--s2);border-radius:3px;min-width:40px;text-align:center}
.cr-disp{flex:1;color:var(--tm);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:80px}

.empty-col{padding:30px 20px;text-align:center;color:var(--tf);font-style:italic;font-size:12px}
.empty-page{text-align:center;padding:60px 20px;color:var(--tf);font-style:italic;font-family:'Instrument Serif',serif;font-size:20px}

.day-summary{display:flex;gap:12px;padding:10px 18px;background:var(--s);border-bottom:1px solid var(--bd);font-size:11px;color:var(--tm);flex-wrap:wrap}
"""

CALLS_BODY = '''<div class="wrap">
<div class="page-title">Calls by Date</div>
<div class="page-sub">Every call in a date range, split by whether the lead was new to us that day or a followup from before.</div>

<div class="range-ctl">
 <div class="grp"><label>From</label><input type="date" id="cFrom"></div>
 <div class="grp"><label>To</label><input type="date" id="cTo"></div>
 <div class="grp" style="margin-left:auto">
  <button data-preset="today">Today</button>
  <button data-preset="yesterday">Yesterday</button>
  <button data-preset="7">Last 7</button>
  <button data-preset="14">Last 14</button>
  <button data-preset="all" class="active">All</button>
 </div>
</div>

<div id="days"></div>
</div>'''

CALLS_JS = r"""
const cst={from:null,to:null};
const cBuckets=buildDailyBuckets(D);
const cDates=cBuckets.map(b=>b.date);
const cMin=cDates[0]||fdate(new Date());
const cMax=cDates[cDates.length-1]||fdate(new Date());

$('#cFrom').min=cMin;$('#cFrom').max=cMax;
$('#cTo').min=cMin;$('#cTo').max=cMax;

function cSetPreset(p){
 document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.classList.toggle('active',b.dataset.preset===p));
 if(p==='all'){cst.from=cMin;cst.to=cMax}
 else if(p==='today'){cst.from=cMax;cst.to=cMax}
 else if(p==='yesterday'){
  const end=new Date(cMax);end.setDate(end.getDate()-1);
  const s=fdate(end);cst.from=s<cMin?cMin:s;cst.to=s<cMin?cMin:s;
 }
 else{
  const n=parseInt(p);
  const end=new Date(cMax);const start=new Date(end);start.setDate(start.getDate()-n+1);
  const ss=fdate(start);cst.from=ss<cMin?cMin:ss;cst.to=cMax;
 }
 $('#cFrom').value=cst.from;$('#cTo').value=cst.to;
 cRender();
}

$('#cFrom').onchange=e=>{cst.from=e.target.value||cMin;document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.classList.remove('active'));cRender()};
$('#cTo').onchange=e=>{cst.to=e.target.value||cMax;document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.classList.remove('active'));cRender()};
document.querySelectorAll('.range-ctl button[data-preset]').forEach(b=>b.onclick=()=>cSetPreset(b.dataset.preset));

function weekdayOf(d){const dt=pd(d+' 00:00:00')||new Date(d);return dt.toLocaleDateString('en-IN',{weekday:'short'})}

function callRow(c){
 const t=pd(c.time);
 const timeStr=t?t.toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit',hour12:true}):'';
 const connCls=c.connected?'b-ok':'b-ne';
 const connLbl=c.connected?'Conn':'NC';
 const hb=HB[c.hangup]||'b-ne';
 const hl=HL[c.hangup]||c.hangup||'';
 const ms=c.milestone?`<span class="badge ${MB[c.milestone]||'b-ne'}">${esc(ML[c.milestone]||c.milestone)}</span>`:'';
 const disp=c.dispose?esc(tr(c.dispose.replace(/_/g,' '),60)):'';
 return `<div class="call-row" onclick="window.location.href='index.html#${esc(c.leadId)}'">
  <span class="cr-time">${timeStr}</span>
  <a class="cr-lead">${esc(c.leadId)}</a>
  ${c.city?`<span class="cr-city">${esc(c.city)}</span>`:''}
  ${c.duration!=null?`<span class="cr-dur">${fdur(c.duration)}</span>`:''}
  <span class="badge ${connCls}">${connLbl}</span>
  <span class="badge ${hb}">${esc(hl)}</span>
  ${ms}
  ${c.mark_dnd?'<span class="badge b-dn">DND</span>':''}
  ${c.soft_dnd?'<span class="badge b-or">Soft</span>':''}
  ${c.handoff?'<span class="badge b-wn">Handoff</span>':''}
  ${c.conversion?'<span class="badge b-ok">Converted</span>':''}
  <span class="cr-disp">${disp}</span>
 </div>`;
}

function cRender(){
 const container=$('#days');
 const filtered=cBuckets.filter(b=>(!cst.from||b.date>=cst.from)&&(!cst.to||b.date<=cst.to));
 if(!filtered.length){container.innerHTML='<div class="empty-page">No calls in this date range</div>';return}
 // newest first
 const sorted=filtered.slice().sort((a,b)=>b.date.localeCompare(a.date));
 container.innerHTML=sorted.map(b=>{
  const niceDate=(pd(b.date+' 00:00:00')||new Date(b.date)).toLocaleDateString('en-IN',{day:'numeric',month:'long',year:'numeric'});
  const wd=weekdayOf(b.date);
  const newCalls=b.calls.filter(c=>c.isNewLead).sort((a,b)=>callTime(a)-callTime(b));
  const folCalls=b.calls.filter(c=>!c.isNewLead).sort((a,b)=>callTime(a)-callTime(b));
  const conn=b.calls.filter(c=>c.connected).length;
  const conv=b.calls.filter(c=>c.conversion).length;
  const dnd=b.calls.filter(c=>c.mark_dnd).length;
  const newLeads=b.newLeadIds.size;const folLeads=b.followupLeadIds.size;

  return `<div class="day-card">
   <div class="day-head">
    <div class="day-date">${esc(niceDate)}</div>
    <div class="day-weekday">${esc(wd)}</div>
    <div class="day-stats">
     <div class="s-item"><span class="s-val">${b.calls.length}</span>calls</div>
     <div class="s-item"><span class="s-val">${conn}</span>connected</div>
     <div class="s-item"><span class="s-val">${newLeads}</span>new leads</div>
     <div class="s-item"><span class="s-val">${folLeads}</span>followup leads</div>
     ${conv?`<div class="s-item"><span class="s-val" style="color:var(--ok)">${conv}</span>converted</div>`:''}
     ${dnd?`<div class="s-item"><span class="s-val" style="color:var(--dn)">${dnd}</span>DND</div>`:''}
    </div>
   </div>
   <div class="split">
    <div class="split-col">
     <div class="split-h new-bar">
      <span class="icon"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span>
      <span class="tit">New leads (first call today)</span>
      <span class="cnt">${newCalls.length} call${newCalls.length===1?'':'s'} · ${newLeads} lead${newLeads===1?'':'s'}</span>
     </div>
     ${newCalls.length?newCalls.map(callRow).join(''):'<div class="empty-col">No new-lead calls this day</div>'}
    </div>
    <div class="split-col">
     <div class="split-h fol-bar">
      <span class="icon"><svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg></span>
      <span class="tit">Followups (called earlier)</span>
      <span class="cnt">${folCalls.length} call${folCalls.length===1?'':'s'} · ${folLeads} lead${folLeads===1?'':'s'}</span>
     </div>
     ${folCalls.length?folCalls.map(callRow).join(''):'<div class="empty-col">No followup calls this day</div>'}
    </div>
   </div>
  </div>`;
 }).join('');
}

cSetPreset('all');
"""

def build_calls(shared_css, shared_js, data_json):
    nav = NAV_HTML.replace("__EXTRA_HEADER__", "")
    html = page_head("Calls by Date — Lead Journey", "calls")
    html = html.replace("__SHARED_CSS__", shared_css)
    html = html.replace("__PAGE_CSS__", CALLS_CSS)
    html = html.replace("__NAV__", nav)
    html = html.replace("__BODY__", CALLS_BODY)
    html = html.replace("__DATA__", data_json)
    html = html.replace("__SHARED_JS__", shared_js)
    html = html.replace("__PAGE_JS__", CALLS_JS)
    return html


# ============================================================
# MAIN
# ============================================================

def main():
    csv_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if not csv_path or not csv_path.exists():
        print("Usage: python generate_viewer_v3.py call_history.csv")
        sys.exit(1)

    out_dir = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {csv_path}")
    df = pd.read_csv(csv_path, low_memory=False)
    print(f"  {len(df):,} rows, {len(df.columns)} cols")

    leads = build_leads(df)
    tc = sum(len(l["calls"]) for l in leads)
    cn = sum(1 for l in leads for c in l["calls"] if c["connected"])
    print(f"  {len(leads):,} leads, {tc:,} calls ({cn:,} connected)")

    data_json = json.dumps(leads, ensure_ascii=False, separators=(",", ":"))
    shared_css, shared_js = load_shared()

    for name, builder in [
        ("index.html",     build_index),
        ("analytics.html", build_analytics),
        ("calls.html",     build_calls),
    ]:
        html = builder(shared_css, shared_js, data_json)
        p = out_dir / name
        p.write_text(html, encoding="utf-8")
        print(f"  {name}: {os.path.getsize(p)/1024:.0f} KB")

    print(f"\nOpen {out_dir.resolve()}/index.html in your browser.")

if __name__ == "__main__":
    main()