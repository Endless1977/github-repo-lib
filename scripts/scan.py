#!/usr/bin/env python3
"""Scant GitHub met de zoekopdrachten uit queries.json en voegt de resultaten
blijvend toe aan data.json. Bestaande repos worden bijgewerkt, niets wordt verwijderd.
Draait dagelijks via .github/workflows/scan.yml, of handmatig: python scripts/scan.py"""
import json, os, re, sys, time, datetime, urllib.request, urllib.parse, urllib.error
import concurrent.futures as cf
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda n: os.path.join(ROOT, n)
TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_TOKEN') or ''
TODAY = datetime.date.today()
HDR = {'Accept': 'application/vnd.github+json', 'User-Agent': 'repo-bibliotheek-scan'}
if TOKEN: HDR['Authorization'] = 'Bearer ' + TOKEN

def load(n, default):
    try:
        with open(P(n), encoding='utf8') as fh: return json.load(fh)
    except FileNotFoundError: return default

def api(url):
    for _ in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                wait = int(e.headers.get('Retry-After') or 0) or max(5, int(e.headers.get('X-RateLimit-Reset', time.time() + 30)) - int(time.time()) + 2)
                print(f'  limiet, wacht {min(wait, 70)}s', flush=True); time.sleep(min(wait, 70)); continue
            print(f'  fout {e.code}: {url}', flush=True); return None
        except Exception as e:
            print(f'  fout: {e}', flush=True); time.sleep(3)
    return None

GAME_RX = re.compile(r'\b(game|games|spel|spellen|multiplayer|shooter|rpg|racing|race|arcade|platformer|puzzle|roguelike|beat.?em.?up|adventure|avontuur|dogfight|level|levels|boss|bazen)\b', re.I)

def rec_of(r, kind):
    return dict(k=kind, n=r['name'], f=r['full_name'], d=(r['description'] or '')[:220], t=(r.get('topics') or [])[:14],
                l=r['language'], s=r['stargazers_count'], c=r['created_at'][:10], p=r['pushed_at'][:10],
                h=r['homepage'] or '', g=r['has_pages'], a=r['archived'],
                li=((r.get('license') or {}).get('spdx_id') or ''), o=r['owner']['login'])

SHOT_BAD = re.compile(r'shields\.io|badge|travis-ci|codecov|circleci|appveyor|gitter|ko-fi|buymeacoffee|patreon|paypal|liberapay|opencollective|discord|sponsor|backers|star-history|contrib\.rocks|repobeats|deepwiki|trendshift|producthunt|hits\.|visitor|komarev|img\.youtube|vercel\.com/button|deploy|/logo|logo[._-]|_logo|-logo|icon|favicon|emoji|flag|avatar|stats|\.svg(\?|$)|download-on|get-it-on|app.?store|google.?play|play.?store|flathub|f-droid|fdroid|snapcraft|microsoft-store|winget|homebrew|sourceforge|weblate|crowdin|translat|license|ubuntu|_banner|donate|qr|nodei\.co|npm-|/npm/|star_repo|star-repo|powered|built-with|made-with|button|brand', re.I)

def shots(f):
    for name in ('README.md', 'readme.md', 'Readme.md', 'README.MD', 'README.markdown', 'README'):
        try:
            with urllib.request.urlopen(f'https://raw.githubusercontent.com/{f}/HEAD/{name}', timeout=20) as r:
                txt = r.read().decode('utf8', 'ignore'); break
        except Exception: txt = ''
    if not txt: return []
    base = f'https://raw.githubusercontent.com/{f}/HEAD/'
    urls = re.findall(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)', txt) + re.findall(r'<img[^>]+src\s*=\s*["\']([^"\']+)', txt, re.I)
    refs = dict(re.findall(r'^\s*\[([^\]]+)\]:\s*(\S+)', txt, re.M))
    urls += [refs[k] for k in re.findall(r'!\[[^\]]*\]\[([^\]]+)\]', txt) if k in refs]
    out = []
    for u in urls:
        u = u.strip()
        if u.startswith('data:') or SHOT_BAD.search(u): continue
        if u.startswith('//'): u = 'https:' + u
        if not u.startswith('http'): u = urljoin(base, u[2:] if u.startswith('./') else u.lstrip('/'))
        m = re.match(r'https://github\.com/([^/]+/[^/]+)/(?:blob|raw)/([^?#]+)', u)
        if m: u = f'https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}'
        if not re.search(r'\.(png|jpe?g|gif|webp)(\?|$)|user-attachments/assets|user-images\.githubusercontent|camo\.githubusercontent|imgur', u, re.I): continue
        if u not in out: out.append(u)
        if len(out) >= 8: break
    return out

def main():
    data = load('data.json', [])
    qs = load('queries.json', {})
    ov = {k: v for k, v in load('overrides.json', {}).items() if not k.startswith('_')}
    by = {r['f']: r for r in data}
    subst = lambda q: q.replace('{30d}', str(TODAY - datetime.timedelta(days=30))).replace('{1y}', str(TODAY - datetime.timedelta(days=365)))
    added = updated = 0
    for group in ('game', 'app', 'own'):
        for q in qs.get(group, []):
            q = subst(q)
            js = api('https://api.github.com/search/repositories?' + urllib.parse.urlencode({'q': q, 'sort': 'stars', 'per_page': 100}))
            items = (js or {}).get('items', [])
            n = 0
            for r in items:
                if r.get('fork') and group != 'own': continue
                f = r['full_name']; o = ov.get(f, {})
                if o.get('skip'): continue
                kind = o.get('k') or (('game' if GAME_RX.search(' '.join([r['name'], r['description'] or ''] + (r.get('topics') or []))) else 'app') if group == 'own' else group)
                new = rec_of(r, kind)
                if group == 'own': new['m'] = 1
                if f in by:
                    old = by[f]
                    for key in ('n', 'd', 't', 'l', 's', 'p', 'h', 'g', 'a', 'li'):
                        if key == 'd' and not new['d']: continue
                        old[key] = new[key]
                    if group == 'own': old['m'] = 1
                    if o.get('k'): old['k'] = o['k']
                    updated += 1
                else:
                    new['nw'] = str(TODAY); data.append(new); by[f] = new; added += 1; n += 1
            print(f'{group:5} {q!r}: {len(items)} gevonden, {n} nieuw', flush=True)
    # overrides toepassen
    for f, o in ov.items():
        r = by.get(f)
        if not r: continue
        if o.get('k'): r['k'] = o['k']
        if o.get('d') and not r.get('d'): r['d'] = o['d']
        if o.get('t'): r['t'] = list(dict.fromkeys(r.get('t', []) + o['t']))
    data = [r for r in data if not ov.get(r['f'], {}).get('skip')]
    # screenshots: nieuwe repos, eigen repos, en elke 30 dagen opnieuw
    cutoff = str(TODAY - datetime.timedelta(days=30))
    todo = [r for r in data if r.get('m') or not r.get('ic') or r['ic'] < cutoff]
    print(f'screenshots zoeken in {len(todo)} READMEs', flush=True)
    with cf.ThreadPoolExecutor(16) as ex:
        for r, found in zip(todo, ex.map(lambda r: shots(r['f']), todo)):
            if found: r['i'] = found
            elif r.get('m'): r.pop('i', None)
            r['ic'] = str(TODAY)
    data.sort(key=lambda r: -r['s'])
    with open(P('data.json'), 'w', encoding='utf8') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    print(f'klaar: {added} nieuw, {updated} bijgewerkt, totaal {len(data)}', flush=True)

if __name__ == '__main__':
    main()
