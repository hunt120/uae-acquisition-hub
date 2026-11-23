#!/usr/bin/env python3
"""Public RSS-based employer candidates. Conservative headline extraction; no fabricated data."""
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
 'Dubai companies to hire staff expansion when:30d',
 'UAE healthcare hospitals to hire staff expand when:30d',
 'UAE supermarket retail chain hiring new stores when:30d',
 'Dubai logistics warehouse company hires workers when:30d',
 'UAE hospitality hotel group recruit employees when:30d',
 'UAE manufacturing plant factory company creates jobs when:30d',
 'Dubai facilities management company recruitment workers when:30d',
 'UAE company plans to hire employees when:30d',
 'UAE business opens new branches hiring when:30d',
]
UAE=re.compile(r'\b(?:UAE|United Arab Emirates|Dubai|Abu Dhabi|Sharjah|Ajman|Fujairah|Ras Al Khaimah|RAK|Umm Al Quwain|Al Ain|Jebel Ali)\b',re.I)
HIRING=re.compile(r'\b(?:hir(?:e|es|ed|ing)|recruit(?:s|ed|ment|ing)?|vacanc(?:y|ies)|job openings?|new jobs?|jobs created|workforce|employees?|staff|onboarding|walk.in interviews?)\b',re.I)
EXPAND=re.compile(r'\b(?:expands?|expansion|opens?|opening|launch(?:es|ed)?|new (?:branch|factory|warehouse|plant|hotel|store|facility))\b',re.I)
EXCLUDE=re.compile(r'\b(?:ruler|sheikh|sheikha|royal|surgery|celebrity|football|cricket|politic(?:s|al)|war|conflict|stock market|crypto|bitcoin|layoffs?|job cuts?|redundan(?:cy|cies)|fired|visa rules?|gold prices?|weather)\b',re.I)
# A headline is evidence of a possible employer, not proof of UAE payroll volume.
# The watchlist is used ONLY to recognize a name appearing in an actual news title.
# It does not create leads without a matching source.
KNOWN_EMPLOYERS=[
 'Aster DM Healthcare','Dubai Taxi Company','Transguard Group','Dulsco','Imdaad',
 'Farnek','Emirates Group','dnata','Lulu Group','LuLu Retail','Majid Al Futtaim',
 'Al-Futtaim','Al Futtaim','Landmark Group','NMC Healthcare','Burjeel Holdings',
 'PureHealth','GEMS Education','Azizi Developments','Emaar','DAMAC',
 'Al Ghurair','Al Naboodah','Aldar','ADNOC','DP World','Aramex',
 'Jumeirah Group','Rotana','Accor','Dubai Holding','Union Coop',
 'Spinneys','Americana Restaurants','Talabat','Careem','noon',
 'RAK Ceramics','Air Arabia','Etihad Airways','Emirates Flight Catering',
 'Al Tayer Group','Al Ansari Exchange','Sobha Realty','Khidmah',
 'Serco','Al Shirawi','Mediclinic','Thumbay Group','Khalifa University',
]
def read_existing():
    try:
        data=json.loads(OUT.read_text(encoding='utf-8'))
        return data if isinstance(data,dict) else {'signals':data if isinstance(data,list) else []}
    except (OSError,ValueError):return {'signals':[]}

def qualify(title):
    if EXCLUDE.search(title):return False
    # A company-specific story may mention a UAE employer without naming the UAE.
    # Keep the requirement for hiring/workforce OR business expansion.
    return bool((UAE.search(title) or any(re.search(r'(?<![\w])'+re.escape(n)+r'(?![\w])',title,re.I) for n in KNOWN_EMPLOYERS))
                and (HIRING.search(title) or EXPAND.search(title)))

def score(title):
    s=45
    if re.search(r'\b(?:hire|hiring|recruit|recruitment|vacancies|new jobs|jobs created)\b',title,re.I):s+=20
    elif HIRING.search(title):s+=5
    if EXPAND.search(title):s+=15
    if re.search(r'\b(?:to hire|plans? to hire|recruiting|new jobs|jobs created)\b',title,re.I):s+=10
    if re.search(r'\b(?:factory|logistics|warehouse|retail|hotel|manufactur|facilities|construction|supermarket)\b',title,re.I):s+=10
    if re.search(r'\bDubai\b',title,re.I):s+=5
    return min(s,95)

GEMINI_ROOT = 'https://generativelanguage.googleapis.com/v1beta'
MAX_AI_ITEMS = 120
BATCH_SIZE = 15
HIRING_ACTION = r'(?:hire[sd]?|hiring|recruit(?:s|ed|ing)?|seeks? to hire|creates? new jobs)'
EXPANSION_ACTION = r'(?:expand(?:s|ed|ing)?|open(?:s|ed|ing)?|builds?|launch(?:es|ed|ing)?)'
ACTION_STRONG = re.compile(rf'\b(?:{HIRING_ACTION}|{EXPANSION_ACTION})\b', re.I)
SITE = re.compile(r'\b(?:branches|branch|factories|factory|warehouse|plant|hotel|store|facility|office|hospital|clinic|campus|operations)\b', re.I)
LEADING = re.compile(r'^(?:(?:UAE|Dubai|Abu Dhabi|Sharjah) jobs:\s*|(?:UAE|Dubai|Abu Dhabi|Sharjah)[- ]based\s+)', re.I)
LEGAL_SUFFIX = re.compile(r'\b(?:L\.?L\.?C\.?|FZE|FZCO|FZ-LLC|PJSC|P\.J\.S\.C\.|Ltd\.?|Limited|Inc\.?)$', re.I)
NAME_WORDS = re.compile(r"^[\w&.'’ -]+$")
FRAGMENT_WORDS = re.compile(
    r'\b(?:job[s]?|vacancies|hiring|workers|staff|employees|employers?|signs?|agreement|'
    r'announces?|plans?|reveals?|reports?|says?|for|with|across|under|from|at|in|to|will)\b',
    re.I,
)
GENERIC_START = re.compile(
    r'^(?:(?:a|an|the|new|leading|major|local|global|UAE|Dubai|Abu Dhabi|Sharjah)\s+)*'
    r'(?:company|firm|business|group|employers?|operator|retailer|developer|chain)\b',
    re.I,
)


def headline_text(item):
    title = item.get('headline')
    # Older Google News records only stored the display title with a publisher suffix.
    return title if title is not None else item['title'].rsplit(' - ', 1)[0]


def valid_company(name, headline, event):
    if not isinstance(name, str) or not NAME_WORDS.fullmatch(name):
        return False
    if not 3 <= len(name) <= 85 or len(name.split()) > 9:
        return False

    known = any(name.casefold() == employer.casefold() for employer in KNOWN_EMPLOYERS)
    if not known:
        # For unfamiliar names, require an explicit legal suffix and reject prose fragments.
        if (not LEGAL_SUFFIX.search(name) or GENERIC_START.search(name)
                or FRAGMENT_WORDS.search(name) or ACTION_STRONG.search(name)):
            return False

    action = {'hiring': HIRING_ACTION, 'expansion': EXPANSION_ACTION}.get(event)
    if action is None:
        return False
    subject = LEADING.sub('', headline.strip(), count=1)
    match = re.match(
        rf"^{re.escape(name)}(?:['’]s)?\s+(?:(?:to|will|plans? to|is|begins?)\s+)?({action})\b",
        subject,
        re.I,
    )
    if not match:
        return False

    detail = subject[match.end():]
    if event == 'hiring':
        return not re.match(r'\s+(?:process|rules?|polic(?:y|ies)|freeze|platform|agreement)\b', detail, re.I)
    return bool(SITE.search(detail)) and not re.match(
        r'\s+(?:(?:an?|the|its|new)\s+)*(?:platform|app|campaign|partnership|agreement|program(?:me)?)\b',
        detail, re.I,
    )


class GeminiHTTPError(RuntimeError):
    def __init__(self, operation, status):
        self.status = status
        super().__init__(f'Gemini {operation} returned HTTP {status}')


class GeminiNetworkError(RuntimeError):
    pass


class Gemini:
    def __init__(self):
        self.key = os.environ.get('GEMINI_API_KEY', '').strip()
        if not self.key:
            raise RuntimeError('GEMINI_API_KEY missing from Actions step environment')
        self.models = self.list_models()
        self.model = self.models[0]

    def request(self, path, operation, body=None):
        payload = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f'{GEMINI_ROOT}/{path}', data=payload,
            headers={'Content-Type': 'application/json', 'x-goog-api-key': self.key},
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=45) as response:
                    result = json.load(response)
                if not isinstance(result, dict):
                    raise RuntimeError(f'Gemini {operation} returned an invalid response')
                return result
            except urllib.error.HTTPError as exc:
                if exc.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                    raise GeminiHTTPError(operation, exc.code) from None
            except OSError as exc:
                reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
                if (body is not None and isinstance(reason, TimeoutError)) or attempt == 2:
                    raise GeminiNetworkError(
                        f'Gemini {operation} failed with {type(reason).__name__}'
                    ) from None
            except ValueError:
                raise RuntimeError(f'Gemini {operation} returned invalid JSON') from None
            time.sleep(3 * 2**attempt)

    def list_models(self):
        names = set()
        params = {'pageSize': 100}
        seen_tokens = set()
        while True:
            result = self.request('models?' + urllib.parse.urlencode(params), 'model listing')
            for model in result.get('models', []):
                name = model.get('name', '')
                if ('generateContent' in model.get('supportedGenerationMethods', [])
                        and re.fullmatch(r'models/gemini-[a-z0-9.-]+', name)
                        and not re.search(r'-(?:image|tts|audio|live|embedding|robotics|computer-use|vision|deep-research|agent)(?:-|$)', name)):
                    names.add(name)
            token = result.get('nextPageToken')
            if not token:
                break
            if token in seen_tokens:
                raise RuntimeError('Gemini model catalog repeated a page token')
            seen_tokens.add(token)
            params['pageToken'] = token
        if not names:
            raise RuntimeError('Gemini model catalog contains no supported text generation models')

        def priority(name):
            version = re.search(r'gemini-(\d+)(?:\.(\d+))?', name)
            major, minor = (int(version[1]), int(version[2] or 0)) if version else (0, 0)
            unstable = bool(re.search(r'-(?:preview|exp|experimental|latest)(?:-|$)', name))
            return unstable, 'flash' not in name, -major, 'lite' not in name, -minor, name

        return sorted(names, key=priority)

    def generate(self, body):
        transient_failures = 0
        last_error = None
        while self.models:
            self.model = self.models[0]
            print(f'Gemini generation using {self.model}', flush=True)
            try:
                return self.request(f'{self.model}:generateContent', 'generation', body)
            except (GeminiHTTPError, GeminiNetworkError) as exc:
                if isinstance(exc, GeminiHTTPError) and exc.status not in (404, 500, 502, 503, 504):
                    raise
                last_error = exc
                self.models.pop(0)
                print(f'{exc} for {self.model}', flush=True)
                if not isinstance(exc, GeminiHTTPError) or exc.status != 404:
                    transient_failures += 1
                    if transient_failures == 3:
                        break
        if not transient_failures:
            raise RuntimeError('Gemini generation returned HTTP 404 for every compatible catalog model')
        raise RuntimeError(f'Gemini catalog model attempts failed. Last error: {last_error}') from None


def gemini_batch(client, items):
    # Return indices into the provided batch; no invented article references.
    compact=[{'index':i,'headline':headline_text(x)} for i,x in enumerate(items)]
    instructions=(
      'You extract named real-world employers from UAE business news headlines. '
      'Return only a JSON object with key "companies", array of objects with keys '
      '"index" (integer), "name" (exact company name substring in headline), '
      '"event" (one of hiring, expansion, other), "confidence" (high, medium, low). '
      'Do not extract headline fragments, industries, countries, publications, generic employers, '
      'government policy articles, or entities mentioned only as commentators. '
      'Extract the employer only when it is the subject at the beginning of the headline. '
      'Use its complete name, including any legal suffix printed in the headline. '
      'Only include an employer if the headline attributes hiring, new jobs, or a concrete '
      'new physical business site/expansion to that company. Training existing staff, '
      'partnerships without workforce expansion, salary forecasts and vague business news '
      'are NOT qualifying events. Do not infer facts beyond the headline. '
      'If none qualify, return {"companies":[]}.'
    )
    body={'system_instruction':{'parts':[{'text':instructions}]},
      'contents':[{'role':'user','parts':[{'text':json.dumps(compact,ensure_ascii=False)}]}],
      'generationConfig':{'responseMimeType':'application/json','maxOutputTokens':4096}}
    result = client.generate(body)
    try:
        candidate = result['candidates'][0]
        if candidate.get('finishReason') != 'STOP':
            raise ValueError('incomplete generation')
        parts = candidate['content']['parts']
        response_text = ''.join(part.get('text', '') for part in parts if not part.get('thought'))
        records = json.loads(response_text)['companies']
        if not isinstance(records, list) or any(
            not isinstance(record, dict)
            or type(record.get('index')) is not int
            or not 0 <= record['index'] < len(items)
            or not isinstance(record.get('name'), str)
            or record.get('event') not in ('hiring', 'expansion', 'other')
            or record.get('confidence') not in ('high', 'medium', 'low')
            for record in records
        ):
            raise ValueError('invalid companies array')
        return records
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        raise RuntimeError('Gemini extraction returned an incomplete or invalid companies response') from None


def ai_extract(signals):
    grouped = {}
    eligible = [item for item in signals if ACTION_STRONG.search(headline_text(item))]
    eligible = eligible[:MAX_AI_ITEMS]
    client = Gemini()
    batches = 0
    for pos in range(0, len(eligible), BATCH_SIZE):
        chunk = eligible[pos:pos + BATCH_SIZE]
        try:
            records = gemini_batch(client, chunk)
        except RuntimeError as exc:
            raise RuntimeError(f'AI batch {batches + 1} failed: {exc}') from None
        batches += 1
        for rec in records:
            item = chunk[rec['index']]
            name = ' '.join(rec['name'].split())
            if rec['confidence'] == 'low' or not valid_company(name, headline_text(item), rec['event']):
                continue
            key=re.sub(r'[^a-z0-9]','',name.lower())
            if not key:continue
            evidence={'title':item['title'],'url':item['url'],'published':item['published']}
            emirate=next((e for e in EMIRATES if re.search(r'\b'+re.escape(e)+r'\b',item['title'],re.I)),'UAE — emirate unverified')
            points=score(item['title']) if rec['event']=='hiring' else min(score(item['title']),75)
            if key not in grouped:
                grouped[key]={'id':hashlib.sha256(key.encode()).hexdigest()[:16],
                  'name':name,'emirate':emirate,'score':points,
                  'confidence':'AI-screened headline; employer and UAE payroll relevance require verification',
                  'extraction_method':'gemini','event':rec['event'],'evidence':[evidence]}
            else:
                old=grouped[key]
                if all(e['url']!=item['url'] for e in old['evidence']) and len(old['evidence'])<5:old['evidence'].append(evidence)
                old['score']=max(old['score'],points)
    return sorted(grouped.values(),key=lambda p:(-p['score'],p['name'].lower()))[:150], batches

def main():
    now=datetime.now(timezone.utc)
    previous=read_existing()
    found={}
    # Re-qualify previous records, never reuse stale records indefinitely.
    for item in previous.get('signals',[]):
        if isinstance(item,dict) and isinstance(item.get('title'), str) and qualify(headline_text(item)) and item.get('url'):
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
                publisher = (item.findtext('source') or '').strip()
                suffix = ' - ' + publisher
                headline = title[:-len(suffix)] if publisher and title.endswith(suffix) else title
                if not qualify(headline) or not link.startswith('https://'):continue
                try:published=parsedate_to_datetime(item.findtext('pubDate') or '').astimezone(timezone.utc)
                except (ValueError,TypeError,OverflowError):continue
                if published<now-timedelta(days=21):continue
                uid=hashlib.sha256(link.encode()).hexdigest()[:18]
                found[uid]={'id':uid,'title':title[:240],'headline':headline[:240],'url':link,'published':published.isoformat(),'type':'unverified_news_signal'}
        except (OSError,ValueError,ET.ParseError) as exc:print('Feed unavailable:',type(exc).__name__,str(exc)[:100])
    if successes==0:raise SystemExit('No feeds accessible; existing data left unchanged')
    signals=sorted(found.values(),key=lambda x:x['published'],reverse=True)[:250]
    try:
        prospects, ai_batches = ai_extract(signals)
    except RuntimeError as exc:
        raise SystemExit(f'Employer discovery failed: {exc}. Existing signals left unchanged.') from None
    payload={'updated_at':now.isoformat(),'feed_successes':successes,'daily_target':TARGET,
        'method':'Gemini headline-only extraction, exact company-name evidence check; all leads unverified',
        'ai_status':'ok' if ai_batches else 'no_eligible_signals',
        'ai_batches':ai_batches,'ai_errors':0,
        'signals':signals,'prospects':prospects}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    # Publish only after every AI batch has finished and the whole JSON is on disk.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=OUT.parent, delete=False) as output:
        temporary = Path(output.name)
        try:
            json.dump(payload, output, ensure_ascii=False, indent=2)
            output.write('\n')
            output.close()
            temporary.replace(OUT)
        finally:
            temporary.unlink(missing_ok=True)
    print(f'Saved {len(signals)} signals and {len(prospects)} AI-screened prospects across {ai_batches} AI batches')


if __name__ == '__main__':
    main()
