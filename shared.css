// ============================================================
// SHARED UTILITIES — identical across all three pages
// ============================================================

// Theme: apply saved BEFORE render to avoid flash
(function(){try{const t=localStorage.getItem('ljv_theme');if(t==='dark')document.documentElement.setAttribute('data-theme','dark');}catch(e){}})();

const $=s=>document.querySelector(s);
const $$=s=>document.querySelectorAll(s);
const esc=s=>s==null?'':String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const fp=n=>!n||isNaN(n)?'':`₹${n>=1e5?(n/1e5).toFixed(1)+'L':(n/1e3).toFixed(0)+'k'}`;

// Parse DD-MM-YYYY HH:MM:SS or ISO
const pd=t=>{
 if(!t)return null;
 const m=String(t).match(/^(\d{2})-(\d{2})-(\d{4})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?/);
 if(m)return new Date(+m[3],+m[2]-1,+m[1],+(m[4]||0),+(m[5]||0),+(m[6]||0));
 const d=new Date(t);return isNaN(d)?null:d;
};
const ft=t=>{if(!t)return'';const d=pd(t);return d?d.toLocaleString('en-IN',{day:'2-digit',month:'short',year:'2-digit',hour:'2-digit',minute:'2-digit'}):String(t)};
const fdur=s=>{if(s==null||isNaN(s))return'';const t=Math.round(+s);if(t<60)return t+'s';const m=Math.floor(t/60),r=t%60;return m+':'+String(r).padStart(2,'0')};
const fdate=d=>!d?'':d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
const fdateNice=d=>!d?'':d.toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'2-digit'});
const tr=(s,n)=>!s?'':s.length>n?s.slice(0,n)+'…':s;

// Call-level helpers
const callDate=c=>{const d=pd(c.time||c.date);if(!d)return'';return fdate(d)};
const callTime=c=>{const d=pd(c.time||c.date);return d?d.getTime():0};

// Lead-level helpers
const firstCallDate=l=>{const t=l.calls[0]?.date||l.calls[0]?.time||'';const d=pd(t);return d?fdate(d):''};
const firstCallTime=l=>{const t=l.calls[0]?.time||l.calls[0]?.date||'';const d=pd(t);return d?d.getTime():0};
const lastMilestone=l=>{for(let i=l.calls.length-1;i>=0;i--)if(l.calls[i].milestone)return l.calls[i].milestone;return''};
const connectedCount=l=>l.calls.filter(c=>c.connected).length;
const everConnected=l=>l.calls.some(c=>c.connected);

const HL={'CLIENT_INITIATED':'Client hung up','PARTICIPANT_REMOVED':'Agent ended','SESSION_TIMEOUT':'Session timeout','USER_UNAVAILABLE':'Unreachable','USER_UNRESPONSIVE':'No response','USER_REJECTED':'Rejected','VOICEMAIL_DETECTED':'Voicemail','OUTSIDE_TRIGGER_WINDOW':'Outside window'};
const HB={'CLIENT_INITIATED':'b-ok','PARTICIPANT_REMOVED':'b-ok','SESSION_TIMEOUT':'b-ok','USER_UNAVAILABLE':'b-ne','USER_UNRESPONSIVE':'b-wn','USER_REJECTED':'b-dn','VOICEMAIL_DETECTED':'b-wn','OUTSIDE_TRIGGER_WINDOW':'b-ne'};
const ML={'fresh_lead':'Fresh','minimal_engagement':'Minimal','preference_collected':'Prefs','car_pitched':'Pitched','test_drive_scheduled':'TD Sched'};
const MB={'fresh_lead':'b-ne','minimal_engagement':'b-wn','preference_collected':'b-in','car_pitched':'b-in','test_drive_scheduled':'b-ok'};
const MO={test_drive_scheduled:5,car_pitched:4,preference_collected:3,minimal_engagement:2,fresh_lead:1};

// Build daily buckets for any cross-page needs
function buildDailyBuckets(data){
 const buckets={}; // yyyy-mm-dd → {calls:[], leads:Set}
 data.forEach(l=>{
  const firstDate=firstCallDate(l);
  l.calls.forEach(c=>{
   const d=callDate(c);
   if(!d)return;
   if(!buckets[d])buckets[d]={date:d,calls:[],newLeadIds:new Set(),followupLeadIds:new Set()};
   buckets[d].calls.push({...c,leadId:l.id,city:l.city,isNewLead:firstDate===d});
   if(firstDate===d)buckets[d].newLeadIds.add(l.id);
   else buckets[d].followupLeadIds.add(l.id);
  });
 });
 return Object.values(buckets).sort((a,b)=>a.date.localeCompare(b.date));
}

// Theme toggle (called after DOM ready)
function wireThemeToggle(){
 const btn=$('#themeTog');if(!btn)return;
 btn.onclick=()=>{
  const cur=document.documentElement.getAttribute('data-theme')==='dark'?'dark':'light';
  const next=cur==='dark'?'light':'dark';
  if(next==='dark')document.documentElement.setAttribute('data-theme','dark');
  else document.documentElement.removeAttribute('data-theme');
  try{localStorage.setItem('ljv_theme',next);}catch(e){}
 };
}