#!/usr/bin/env python3
"""Public RSS-based employer candidates. Conservative headline extraction; no fabricated data."""
import hashlib, json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data'/'signals.json'
TARGET=40  # aspiration, never fill with invented companies
EMIRATES=['Dubai','Abu Dhabi','Sharjah','Ajman','Ras Al Khaimah','Fujairah','Umm Al Quwain']
QUERIES=[
 'Dubai company hiring recruitment employees when:14d',
 'UAE employer hiring staff jobs expansion when:14d',
 'Abu Dhabi company new factory jobs hiring when:14d',
 'Sharjah company new warehouse jobs recruitment when:14d',
 'UAE logistics company recruiting drivers workers when:14d',
 'Dubai hotel operator hiring staff new hotel when:14d',
 'UAE retail chain new stores hiring staff when:14d',
 'UAE manufacturing company factory expansion jobs when:14d',
 'Dubai facilities management hiring employees recruitment when:14d',
 'UAE healthcare company new hospital hiring when:14d',
 'Ajman Fujairah Ras Al Khaimah company hiring jobs when:14d',
 'UAE construction company hiring workforce projects when:14d',
]
UAE=re.compile(r'\b(?:UAE|United Arab Emirates|Dubai|Abu Dhabi|Sharjah|Ajman|Fujairah|Ras Al Khaimah|RAK|Umm Al Quwain|Al Ain|Jebel Ali)\b',re.I)
HIRING=re.compile(r'\b(?:hir(?:e|es|ed|ing)|recruit(?:s|ed|ment|ing)?|vacanc(?:y|ies)|job openings?|new jobs?|jobs created|workforce|employees?|staff|onboarding|walk.in interviews?)\b',re.I)
EXPAND=re.compile(r'\b(?:expands?|expansion|opens?|opening|launch(?:es|ed)?|new (?:branch|factory|warehouse|plant|hotel|store|facility))\b',re.I)
EXCLUDE=re.compile(r'\b(?:ruler|sheikh|sheikha|royal|surgery|celebrity|football|cricket|politic(?:s|al)|war|conflict|stock market|crypto|bitcoin|layoffs?|job cuts?|redundan(?:cy|cies)|fired|visa rules?|gold prices?|weather)\b',re.I)
# Only extract employer when the headline explicitly uses a company-name grammatical position.
NAME=r'([A-Z][A-Za-z0-9&.\'’\-]*(?:\s+[A-Z][A-Za-z0-9&.\'’\-]*){0,4})'
PATTERNS=[
 re.compile(r'^'+NAME+r'\s+(?:to\s+)?(?:hire|recruit|open|launch|expand|adds?|creates?|plans? to hire)\b',re.I),
 re.compile(r'^'+NAME+r'\s+(?:announces?|unveils?)\s+(?:new\s+)?(?:jobs?|hiring|recruitment|factory|warehouse|hotel|store|facility|expansion)\b',re.I),
 re.compile(r'\b(?:employer|company|operator|retailer)\s+'+NAME+r'\s+(?:to\s+)?(?:hire|recruit|expand|open)\b',re.I),
]
GENERIC={'uae','dubai','abu dhabi','sharjah','ajman','fujairah','ras al khaimah','new','jobs','company','companies','government','ministry','united arab emirates','hundreds','thousands','major','local','global','leading','top','the','a','an','employer','operator','retailer'}
def employer_from_title(title):
    headline=title.rsplit(' - ',1)[0].strip()
    for pattern in PATTERNS:
        m=pattern.search(headline)
        if not m:continue
        name=m.group(1).strip(' .,:-')
        # Prevent broad phrase matching from being interpreted as a verified employer.
        if name.lower() in GENERIC or len(name)<3 or UAE.fullmatch(name) or any(w.lower() in {'to','will','plans','announces','new','hiring','recruitment','jobs'} for w in name.split()):continue
        return name
    return None

def read_existing():
    try:
        data=json.loads(OUT.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {'signals':data if isinstance(data,list) else []}
    except (OSError,ValueError):return {'signals':[]}

def qualify(title):return bool(UAE.search(title) and HIRING.search(title) and not EXCLUDE.search(title))

def score(title):
    s=45
    if HIRING.search(title):s+=20
    if EXPAND.search(title):s+=15
    if re.search(r'\b(?:factory|logistics|warehouse|retail|hotel|manufactur|facilities|construction|supermarket)\b',title,re.I):s+=10
    if re.search(r'\bDubai\b',title,re.I):s+=5
    return min(s,95)

def main():
    now=datetime.now(timezone.utc)
    previous=read_existing()
    found={}
    # Re-qualify previous records, never reuse stale records indefinitely.
    for item in previous.get('signals',[]):
        if isinstance(item,dict) and qualify(item.get('title','')) and item.get('url'):
            try:
                if datetime.fromisoformat(item['published'].replace('Z','+00:00')) >= now-timedelta(days=21):found[item['id']]=item
            except (KeyError,TypeError,ValueError):pass
    successes=0
    for query in QUERIES:
        url='https://news.google.com/rss/search?q='+urllib.parse.quote(query)+'&hl=en-AE&gl=AE&ceid=AE:en'
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 UAEAcquisitionHub/1.0'})
            with urllib.request.urlopen(request,timeout=18) as response:raw=response.read(1_500_000)
            root=ET.fromstring(raw);successes+=1
            for item in root.findall('.//channel/item')[:70]:
                title=(item.findtext('title') or '').strip()
                link=(item.findtext('link') or '').strip()
                if not qualify(title) or not link.startswith('https://'):continue
                try:published=parsedate_to_datetime(item.findtext('pubDate') or '').astimezone(timezone.utc)
                except (ValueError,TypeError,OverflowError):continue
                if published<now-timedelta(days=21):continue
                uid=hashlib.sha256(link.encode()).hexdigest()[:18]
                found[uid]={'id':uid,'title':title[:240],'url':link,'published':published.isoformat(),'type':'unverified_news_signal'}
        except (OSError,ValueError,ET.ParseError) as exc:print('Feed unavailable:',type(exc).__name__,str(exc)[:100])
    if successes==0:raise SystemExit('No feeds accessible; existing data left unchanged')
    signals=sorted(found.values(),key=lambda x:x['published'],reverse=True)[:250]
    # Only headline-extracted employer names; article-body verification is not performed.
    grouped={}
    for item in signals:
        name=employer_from_title(item['title'])
        if not name:continue
        key=re.sub(r'[^a-z0-9]','',name.lower())
        if not key:continue
        emirate=next((e for e in EMIRATES if re.search(r'\b'+re.escape(e)+r'\b',item['title'],re.I)), 'UAE — emirate unverified')
        if key not in grouped:
            grouped[key]={'id':hashlib.sha256(key.encode()).hexdigest()[:16], 'name':name,
                'emirate':emirate,'score':score(item['title']),'confidence':'Headline extraction — verify employer',
                'evidence':[{'title':item['title'],'url':item['url'],'published':item['published']}]}
        else:
            g=grouped[key]
            if len(g['evidence'])<5:g['evidence'].append({'title':item['title'],'url':item['url'],'published':item['published']})
            g['score']=max(g['score'],score(item['title']))
    prospects=sorted(grouped.values(),key=lambda p:(-p['score'],p['name'].lower()))[:150]
    payload={'updated_at':now.isoformat(),'feed_successes':successes,'daily_target':TARGET,
        'method':'Conservative headline extraction; names, UAE operation and hiring require manual verification',
        'signals':signals,'prospects':prospects}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Saved {len(signals)} news signals and {len(prospects)} unverified employer candidates from {successes} feeds; target {TARGET} (not guaranteed)')
if __name__=='__main__':main()
