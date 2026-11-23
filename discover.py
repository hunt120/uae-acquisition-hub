#!/usr/bin/env python3
"""Conservative public UAE employer hiring/expansion signal collector.
Headlines are leads for manual verification, not confirmed employer data.
"""
import hashlib
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'data' / 'signals.json'
QUERIES = [
    '"Dubai" (company OR employer) (hiring OR recruitment OR jobs) when:14d',
    '"UAE" (company OR employer) ("hiring" OR "recruiting") when:14d',
    '"Abu Dhabi" company ("new facility" OR "new factory" OR "new warehouse") jobs when:14d',
    '"Dubai" ("new branch" OR "new hotel" OR "new warehouse") hiring when:14d',
    '"Sharjah" (factory OR logistics OR manufacturing) (hiring OR jobs OR expansion) when:14d',
    '"UAE" ("jobs created" OR "new jobs" OR "recruitment drive") when:14d',
]
UAE = re.compile(r'\b(?:UAE|United Arab Emirates|Dubai|Abu Dhabi|Sharjah|Ajman|Fujairah|Ras Al Khaimah|RAK|Umm Al Quwain|Al Ain|Jebel Ali|DIFC|DMCC)\b', re.I)
HIRING = re.compile(r'\b(?:hir(?:e|es|ed|ing)|recruit(?:s|ed|ment|ing)?|vacanc(?:y|ies)|job openings?|new jobs?|jobs created|jobs?|workforce|headcount|employees?|staffing|onboarding|career fair|walk.in interviews?)\b', re.I)
EXPANSION = re.compile(r'\b(?:open(?:s|ed|ing)?|launch(?:es|ed|ing)?|expand(?:s|ed|ing)?|expansion|new (?:branch|facility|factory|warehouse|plant|hotel|store|office)|investment)\b', re.I)
BUSINESS = re.compile(r'\b(?:company|companies|firm|group|business|employer|factory|warehouse|hotel|retailer|logistics|manufactur(?:er|ing)|facilities|operator|airline|hospital|supermarket|retail|industrial)\b', re.I)
EXCLUDE = re.compile(r'\b(?:ruler|sheikh|sheikha|royal|surgery|hospitali[sz]ed|celebrity|football|cricket|politic(?:s|al)|war|conflict|stock market|crypto|bitcoin|layoffs?|job cuts?|redundan(?:cy|cies)|fired|dismissed|US HQ|United States headquarters|visa rules?|gold prices?|weather)\b', re.I)

def qualify(title):
    """Require explicit UAE place + hiring, or a company expansion with job impact."""
    if EXCLUDE.search(title) or not UAE.search(title):
        return False
    return bool(HIRING.search(title) and (BUSINESS.search(title) or EXPANSION.search(title)))

def main():
    # Re-filter historical records so irrelevant headlines disappear on next run.
    existing=[]
    if OUT.exists():
        try:
            payload=json.loads(OUT.read_text(encoding='utf-8'))
            existing=payload.get('signals', []) if isinstance(payload, dict) else payload if isinstance(payload,list) else []
        except (OSError,ValueError):
            pass
    found={x['id']:x for x in existing if isinstance(x,dict) and x.get('id') and qualify(x.get('title',''))}
    success=0
    for query in QUERIES:
        url='https://news.google.com/rss/search?q='+urllib.parse.quote(query)+'&hl=en-AE&gl=AE&ceid=AE:en'
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; UAEAcquisitionHub/1.0)'})
            with urllib.request.urlopen(req,timeout=20) as response:
                data=response.read(1_500_000)
            root=ET.fromstring(data)
            success+=1
            for item in root.findall('.//channel/item')[:40]:
                title=(item.findtext('title') or '').strip()
                link=(item.findtext('link') or '').strip()
                if not title or not link.startswith('https://') or not qualify(title):
                    continue
                try:
                    date=parsedate_to_datetime(item.findtext('pubDate') or '').astimezone(timezone.utc)
                except (TypeError,ValueError,OverflowError):
                    continue
                if date < datetime.now(timezone.utc)-timedelta(days=21):
                    continue
                uid=hashlib.sha256(link.encode()).hexdigest()[:18]
                found[uid]={'id':uid,'title':title[:240],'url':link,'published':date.isoformat(),
                            'query':query,'type':'unverified_news_signal'}
        except (OSError,ET.ParseError,ValueError) as exc:
            print('Feed unavailable:',query,type(exc).__name__,str(exc)[:150])
    if success==0:
        raise SystemExit('No RSS feeds could be fetched; leaving existing file untouched.')
    signals=sorted(found.values(),key=lambda x:x.get('published',''),reverse=True)[:100]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),
                               'feed_successes':success,'signals':signals},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(f'Saved {len(signals)} filtered UAE hiring signals from {success} feeds')
if __name__=='__main__':
    main()
