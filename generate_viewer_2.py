import csv, json, sys
from pathlib import Path
from datetime import datetime

def _s(v): return (v or "").strip()

def build_leads(rows):
    leads = {}
    for r in rows:
        lid = _s(r.get("buylead"))
        if not lid:
            continue

        if lid not in leads:
            leads[lid] = {
                "id": lid,
                "city": _s(r.get("city")),
                "calls": []
            }

        call = {
            "date": _s(r.get("Call Date")),
            "time": _s(r.get("Call Time")),
            "duration": _s(r.get("Call Duration")),
            "recording": _s(r.get("Call Recording")),
            "transcript": _s(r.get("Call Transcript")),
            "hangup": _s(r.get("Hangup Reason")),
            "scenario": _s(r.get("added_scenario")),
            "dispose": _s(r.get("dispose")),
            "ndoa": _s(r.get("ndoa")),
            "connected": _s(r.get("Hangup Reason")) in ["CLIENT_INITIATED","PARTICIPANT_REMOVED"],
            "milestone": _s(r.get("milestone")),
            "budget": _s(r.get("budget")),
            "capability": _s(r.get("capability")),
            "preferred_hub": _s(r.get("preferred_hub")),
            "updated_city": _s(r.get("updated_city")),
        }

        leads[lid]["calls"].append(call)

    return list(leads.values())


HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Lead Journey</title>

<style>
body{font-family:Arial;background:#f6f6f6;margin:0}
.container{display:flex;height:100vh}
.sidebar{width:280px;background:#fff;overflow:auto;border-right:1px solid #ddd}
.lead{padding:10px;border-bottom:1px solid #eee;cursor:pointer}
.lead:hover{background:#f0f0f0}
.main{flex:1;padding:15px;overflow:auto}
.call{background:#fff;padding:10px;margin-bottom:12px;border-radius:6px}

.badge{padding:3px 6px;border-radius:4px;font-size:11px;margin-right:5px;background:#eee}

.section{margin-top:10px}
.rec{margin:10px 0}
.tx{background:#fafafa;padding:10px;border-radius:6px;white-space:pre-wrap}
.meta{margin-bottom:8px}
</style>
</head>

<body>
<div class="container">
<div class="sidebar" id="list"></div>
<div class="main" id="main"></div>
</div>

<script>
const D = __DATA__;

function renderList(){
 const el=document.getElementById("list");
 el.innerHTML = D.map(l => `
   <div class="lead" onclick="renderDetail('${l.id}')">
     <b>${l.id}</b><br>${l.city}
   </div>
 `).join("");
}

function renderDetail(id){
 const l = D.find(x=>x.id===id);
 const el = document.getElementById("main");

 el.innerHTML = l.calls.map(c => `
   <div class="call">

     <div>
       <b>${c.date} ${c.time}</b> |
       ${c.duration} |
       ${c.connected ? "Conn" : "NC"} |
       ${c.hangup}
     </div>

     <!-- TRANSCRIPT FIRST -->
     <div class="section">

       <div class="meta">
         ${c.scenario ? `<span class="badge">${c.scenario}</span>` : ""}
         ${c.ndoa ? `<span class="badge">${c.ndoa}</span>` : ""}
       </div>

       ${c.recording ? `
         <div class="rec">
           <audio controls src="${c.recording}"></audio>
         </div>
       ` : ""}

       <div class="tx">${formatTranscript(c.transcript)}</div>
     </div>

     <!-- BEFORE CALL -->
     <div class="section">
       <b>Before Call</b>
       <div>City: ${l.city}</div>
     </div>

     <!-- AFTER CALL (CLEANED) -->
     <div class="section">
       <b>After Call</b>
       ${c.milestone ? `<div>Milestone: ${c.milestone}</div>` : ""}
       ${c.dispose ? `<div>Disposition: ${c.dispose}</div>` : ""}
       ${c.budget ? `<div>Budget: ${c.budget}</div>` : ""}
       ${c.capability ? `<div>Capability: ${c.capability}</div>` : ""}
       ${c.preferred_hub ? `<div>Hub: ${c.preferred_hub}</div>` : ""}
     </div>

   </div>
 `).join("");
}

function formatTranscript(t){
 if(!t) return "";
 return t
   .replace(/Assistant:/g,"<b>Assistant:</b>")
   .replace(/User:/g,"<b>User:</b>")
   .replace(/\\n/g,"<br>");
}

renderList();
</script>
</body>
</html>
"""

def main():
    csv_path = Path(sys.argv[1])
    rows = list(csv.DictReader(open(csv_path, encoding="utf-8")))
    leads = build_leads(rows)

    html = HTML.replace("__DATA__", json.dumps(leads))
    Path("index.html").write_text(html, encoding="utf-8")

    print("Generated index.html")

if __name__ == "__main__":
    main()