#!/usr/bin/env python3
"""Collect public UAE hiring/expansion news signals; not verified employer leads."""
import json, re, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

QUERIES = [
 'UAE company hiring hundreds employees',
 'Dubai company recruitment expansion jobs',
 'Abu Dhabi company hiring new facility',
 'Sharjah company expansion workforce',
 'UAE logistics facilities management company recruitment',
]
OUT = Path(__file__).parent / 'data' / 'signals.json'

def main():
    existing = []
    if OUT.exists():
        try: existing = json.loads(OUT.read_text(encoding='utf-8')).get('signals', [])
        except (ValueError, OSError): pass
    found = {x['id']: x for x in existing if isinstance(x,dict) and 'id' in x}
    success = 0
    for query in QUERIES:
        url = 'https://news.google.com/rss/search?q=' + urllib.parse.quote(query + ' when:14d') + '&hl=en-AE&gl=AE&ceid=AE:en'
        try:
            req = urllib.request.Request(url,headers={'User-Agent':'UAEAcquisitionHub/0.1 (+public RSS research)'})
            with urllib.request.urlopen(req,timeout=18) as response: data=response.read(1_500_000)
            root=ET.fromstring(data)
            success += 1
            for item in root.findall('.//channel/item')[:25]:
                title=(item.findtext('title') or '').strip()
                link=(item.findtext('link') or '').strip()
                published=(item.findtext('pubDate') or '').strip()
                if not title or not link.startswith('https://'): continue
                try: date=parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
                except (TypeError,ValueError): date=''
                import hashlib
                uid=hashlib.sha256(link.encode()).hexdigest()[:18]
                found[uid]={'id':uid,'title':title[:240],'url':link,'published':date,'query':query,'type':'unverified_news_signal'}
        except (OSError, ET.ParseError, ValueError) as exc:
            print('Feed unavailable:',query,type(exc).__name__)
    if success == 0 and not existing:
        raise SystemExit('No feeds fetched; preserving existing data, workflow will retry later.')
    signals=sorted(found.values(),key=lambda x:x.get('published',''),reverse=True)[:150]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({'updated_at':datetime.now(timezone.utc).isoformat(),'feed_successes':success,'signals':signals},indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print('Saved',len(signals),'signals from',success,'feeds')
if __name__=='__main__': main()
