#!/usr/bin/env python3
"""Scant GitHub, GitLab, Codeberg en F-Droid met de instellingen uit queries.json
en voegt de resultaten blijvend toe aan data.json. Bestaande repos worden bijgewerkt, niets wordt verwijderd.
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

UA = {'User-Agent': 'repo-bibliotheek-scan'}

def fetch_json(url, headers=None, timeout=60):
    """JSON ophalen bij een andere bron dan de GitHub-API. Geeft None bij een fout."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(int(e.headers.get('Retry-After') or 30)); continue
            print(f'  fout {e.code}: {url}', flush=True); return None
        except Exception as e:
            print(f'  fout: {e} ({url})', flush=True); time.sleep(3)
    return None

URL_RX = re.compile(r'https?://[^\s)\]>"\']+')

def first_url(text):
    m = URL_RX.search(text or '')
    return m.group(0).rstrip('.,') if m else ''

def kind_of(name, desc, topics, default):
    return 'game' if GAME_RX.search(' '.join([name, desc or ''] + list(topics or []))) else default

# ---------- GitLab ----------
def scan_gitlab(cfg):
    out = []
    if not cfg: return out
    base = cfg.get('server', 'https://gitlab.com').rstrip('/')
    min_stars = cfg.get('min_stars', 10)
    since = (TODAY - datetime.timedelta(days=cfg.get('active_within_days', 730))).isoformat() + 'T00:00:00Z'
    hdr = {'PRIVATE-TOKEN': os.environ['GITLAB_TOKEN']} if os.environ.get('GITLAB_TOKEN') else {}
    seen = set()
    for group in ('game', 'app'):
        for topic in cfg.get(group, []):
            n = 0
            for page in range(1, cfg.get('pages', 5) + 1):
                items = fetch_json(f'{base}/api/v4/projects?' + urllib.parse.urlencode({
                    'topic': topic, 'visibility': 'public', 'order_by': 'last_activity_at', 'sort': 'desc',
                    'last_activity_after': since, 'per_page': 100, 'page': page}), hdr)
                if not items: break
                for p in items:
                    if p['id'] in seen or (p.get('star_count') or 0) < min_stars or p.get('forked_from_project'): continue
                    seen.add(p['id']); n += 1
                    path = p['path_with_namespace']
                    desc = (p.get('description') or '').strip()
                    out.append(dict(
                        k=group if group == 'game' else kind_of(p['name'], desc, p.get('topics'), 'app'),
                        src='gitlab', n=p['name'], f='gitlab:' + path, u=p['web_url'], b=p.get('default_branch') or 'main',
                        d=desc[:220], t=(p.get('topics') or p.get('tag_list') or [])[:14], l=None,
                        s=p.get('star_count') or 0, c=(p.get('created_at') or '')[:10], p=(p.get('last_activity_at') or '')[:10],
                        h=first_url(desc), g=False, a=bool(p.get('archived')), li='', o=path.split('/')[0], _gid=p['id']))
                if len(items) < 100: break
            print(f'gitlab {group:4} topic:{topic}: {n} met >= {min_stars} sterren', flush=True)
    return out

def gitlab_language(rec, base='https://gitlab.com'):
    js = fetch_json(f"{base}/api/v4/projects/{rec['_gid']}/languages", timeout=20)
    return max(js, key=js.get) if js else None

# ---------- Codeberg (Forgejo/Gitea) ----------
def scan_codeberg(cfg):
    out = []
    if not cfg: return out
    base = cfg.get('server', 'https://codeberg.org').rstrip('/')
    name = cfg.get('name', 'codeberg')
    min_stars = cfg.get('min_stars', 5)
    seen = set()
    for group in ('game', 'app'):
        for topic in cfg.get(group, []):
            n = 0
            for page in range(1, cfg.get('pages', 4) + 1):
                js = fetch_json(f'{base}/api/v1/repos/search?' + urllib.parse.urlencode({
                    'q': topic, 'topic': 'true', 'sort': 'stars', 'order': 'desc', 'limit': 50, 'page': page}))
                items = (js or {}).get('data') or []
                if not items: break
                stop = False
                for r in items:
                    if (r.get('stars_count') or 0) < min_stars: stop = True; continue
                    if r.get('fork') or r.get('private') or r.get('empty') or r['full_name'] in seen: continue
                    seen.add(r['full_name']); n += 1
                    desc = (r.get('description') or '').strip()
                    out.append(dict(
                        k=group if group == 'game' else kind_of(r['name'], desc, r.get('topics'), 'app'),
                        src=name, n=r['name'], f=f"{name}:{r['full_name']}", u=r['html_url'], b=r.get('default_branch') or 'main',
                        d=desc[:220], t=(r.get('topics') or [])[:14], l=r.get('language') or None,
                        s=r.get('stars_count') or 0, c=(r.get('created_at') or '')[:10], p=(r.get('updated_at') or '')[:10],
                        h=(r.get('website') or '').strip() or first_url(desc), g=False, a=bool(r.get('archived')),
                        li=((r.get('licenses') or [''])[0] or ''), o=r['owner']['login']))
                if stop or len(items) < 50: break
            print(f'{name} {group:4} topic:{topic}: {n} met >= {min_stars} sterren', flush=True)
    return out

# ---------- F-Droid ----------
FDROID_CAT = {'Games': 'game', 'Connectivity': 'network', 'Development': 'developer-tools', 'Graphics': 'graphics',
              'Internet': 'web', 'Money': 'finance', 'Multimedia': 'media', 'Navigation': 'maps', 'Phone & SMS': 'messaging',
              'Reading': 'notes', 'Science & Education': 'education', 'Security': 'security', 'Sports & Health': 'health',
              'System': 'utility', 'Theming': 'theming', 'Time': 'productivity', 'Writing': 'note-taking'}

def scan_fdroid(cfg):
    out = []
    if not cfg: return out
    repo = cfg.get('repo', 'https://f-droid.org/repo').rstrip('/')
    js = fetch_json(repo + '/index-v1.json', timeout=180)
    if not js:
        print('fdroid: index niet geladen', flush=True); return out
    cut = (TODAY - datetime.timedelta(days=cfg.get('apps_updated_within_days', 730)))
    cut_ms = int(datetime.datetime(cut.year, cut.month, cut.day).timestamp() * 1000)
    games = apps = 0
    for a in js.get('apps', []):
        pkg = a.get('packageName'); cats = a.get('categories') or []
        if not pkg: continue
        is_game = 'Games' in cats
        if not is_game and (a.get('lastUpdated') or 0) < cut_ms: continue
        loc = a.get('localized') or {}
        L = loc.get('en-US') or loc.get('en') or loc.get('en-GB') or next(iter(loc.values()), {})
        name = a.get('name') or L.get('name') or pkg
        desc = (a.get('summary') or L.get('summary') or '').strip()
        shots = [f"{repo}/{pkg}/{'en-US' if 'en-US' in loc else next(iter(loc), 'en-US')}/phoneScreenshots/{x}" for x in (L.get('phoneScreenshots') or [])[:cfg.get('max_screenshots', 4)]]
        ms = lambda v: datetime.datetime.fromtimestamp((v or 0) / 1000, datetime.timezone.utc).strftime('%Y-%m-%d') if v else ''
        anti = a.get('antiFeatures') or []
        rec = dict(k='game' if is_game else 'app', src='fdroid', n=name, f='fdroid:' + pkg, u=f'https://f-droid.org/packages/{pkg}/',
                   d=desc[:220], t=list(dict.fromkeys(['android'] + [FDROID_CAT[c] for c in cats if c in FDROID_CAT] + ([] if is_game else [c.lower() for c in cats])))[:14],
                   l=None, s=0, c=ms(a.get('added')), p=ms(a.get('lastUpdated')), h=(a.get('webSite') or '').strip(), g=False,
                   a=False, li=a.get('license') or '', o=(a.get('authorName') or '')[:60], fd=pkg,
                   sc=(a.get('sourceCode') or '').strip(), ic=str(TODAY))
        if shots: rec['i'] = shots
        if 'NonFreeNet' in anti or 'Tracking' in anti or 'Ads' in anti: rec['t'].append('anti-features')
        out.append(rec)
        games += is_game; apps += not is_game
    print(f'fdroid: {games} spellen, {apps} apps', flush=True)
    return out

def norm_src_url(u):
    """https://github.com/Owner/Repo(.git)/... -> github:owner/repo, idem voor gitlab/codeberg"""
    m = re.match(r'https?://(?:www\.)?(github\.com|gitlab\.com|codeberg\.org)/([^/#?]+)/([^/#?]+?)(?:\.git)?(?:[/#?]|$)', u or '', re.I)
    return f'{m.group(1).lower()}:{m.group(2).lower()}/{m.group(3).lower()}' if m else ''

def key_of(r):
    src = r.get('src') or 'github'
    if src == 'github': return 'github.com:' + r['f'].lower()
    if src in ('gitlab', 'codeberg'): return norm_src_url(r.get('u'))
    return ''

SHOT_BAD = re.compile(r'shields\.io|badge|travis-ci|codecov|circleci|appveyor|gitter|ko-fi|buymeacoffee|patreon|paypal|liberapay|opencollective|discord|sponsor|backers|star-history|contrib\.rocks|repobeats|deepwiki|trendshift|producthunt|hits\.|visitor|komarev|img\.youtube|vercel\.com/button|deploy|/logo|logo[._-]|_logo|-logo|icon|favicon|emoji|flag|avatar|stats|\.svg(\?|$)|download-on|get-it-on|app.?store|google.?play|play.?store|flathub|f-droid|fdroid|snapcraft|microsoft-store|winget|homebrew|sourceforge|weblate|crowdin|translat|license|ubuntu|_banner|donate|qr|nodei\.co|npm-|/npm/|star_repo|star-repo|powered|built-with|made-with|button|brand', re.I)

def readme_bases(r):
    """(lijst README-URL's, basis voor relatieve links, web-URL) per bron"""
    src = r.get('src') or 'github'
    names = ('README.md', 'readme.md', 'Readme.md', 'README.MD', 'README.markdown', 'README')
    if src == 'github':
        base = f"https://raw.githubusercontent.com/{r['f']}/HEAD/"
        return [base + n for n in names], base, f"https://github.com/{r['f']}"
    if src == 'gitlab':
        base = f"{r['u']}/-/raw/{r.get('b') or 'main'}/"
        return [base + n for n in names], base, r['u']
    if src in ('codeberg',):
        base = f"{r['u']}/raw/branch/{r.get('b') or 'main'}/"
        return [base + n for n in names], base, r['u']
    return [], '', ''

def shots(r):
    urls_try, base, web = readme_bases(r)
    txt = ''
    for url in urls_try:
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as resp:
                txt = resp.read().decode('utf8', 'ignore'); break
        except Exception: pass
    if not txt: return []
    urls = re.findall(r'!\[[^\]]*\]\(\s*<?([^)\s>]+)', txt) + re.findall(r'<img[^>]+src\s*=\s*["\']([^"\']+)', txt, re.I)
    refs = dict(re.findall(r'^\s*\[([^\]]+)\]:\s*(\S+)', txt, re.M))
    urls += [refs[k] for k in re.findall(r'!\[[^\]]*\]\[([^\]]+)\]', txt) if k in refs]
    out = []
    for u in urls:
        u = u.strip()
        if u.startswith('data:') or SHOT_BAD.search(u): continue
        if u.startswith('//'): u = 'https:' + u
        if u.startswith('/uploads/') and r.get('src') == 'gitlab': u = web + u
        elif not u.startswith('http'): u = urljoin(base, u[2:] if u.startswith('./') else u.lstrip('/'))
        m = re.match(r'https://github\.com/([^/]+/[^/]+)/(?:blob|raw)/([^?#]+)', u)
        if m: u = f'https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}'
        u = re.sub(r'(https://gitlab\.com/.+?)/-/blob/', r'\1/-/raw/', u)
        u = re.sub(r'(https://codeberg\.org/.+?)/src/branch/', r'\1/raw/branch/', u)
        if not re.search(r'\.(png|jpe?g|gif|webp)(\?|$)|user-attachments/assets|user-images\.githubusercontent|camo\.githubusercontent|imgur|/uploads/', u, re.I): continue
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
    # ---------- andere bronnen ----------
    keyed = {key_of(r): r for r in data if key_of(r)}
    def add_other(rec):
        nonlocal added, updated
        f = rec['f']
        if ov.get(f, {}).get('skip'): return
        # F-Droid-app waarvan de broncode al als repo in de bibliotheek staat: koppelen in plaats van dubbel toevoegen
        if rec.get('src') == 'fdroid':
            twin = keyed.get(norm_src_url(rec.get('sc')))
            if twin is not None:
                twin['fd'] = rec['fd']
                if 'android' not in twin.get('t', []): twin['t'] = (twin.get('t') or []) + ['android']
                if not twin.get('i') and rec.get('i'): twin['i'] = rec['i']
                if not by.get(f): return
                data.remove(by.pop(f)); return   # eerder los toegevoegd: nu samengevoegd
        if f in by:
            old = by[f]
            for key in ('n', 'd', 't', 's', 'p', 'h', 'a', 'li', 'u', 'b', 'fd', 'sc'):
                if key in rec and (rec[key] or key in ('s', 'a')): old[key] = rec[key]
            if rec.get('src') == 'fdroid' and rec.get('i'): old['i'] = rec['i']; old['ic'] = rec['ic']
            updated += 1
        else:
            rec['nw'] = str(TODAY); data.append(rec); by[f] = rec; added += 1
            k = key_of(rec)
            if k: keyed[k] = rec
    for label, fn, cfg in (('GitLab', scan_gitlab, qs.get('gitlab')), ('Codeberg', scan_codeberg, qs.get('codeberg')), ('F-Droid', scan_fdroid, qs.get('fdroid'))):
        try:
            found = fn(cfg)
        except Exception as e:
            print(f'{label}: overgeslagen door fout: {e}', flush=True); continue
        new_gl = [r for r in found if r.get('src') == 'gitlab' and r['f'] not in by]
        for r in new_gl[:300]:
            r['l'] = gitlab_language(r)
        for r in found:
            gid = r.pop('_gid', None)
            if r.get('src') == 'gitlab' and r['f'] in by and not by[r['f']].get('l'): r['l'] = by[r['f']].get('l')
            add_other(r)

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
    todo = [r for r in data if r.get('src') != 'fdroid' and (r.get('m') or not r.get('ic') or r['ic'] < cutoff)]
    print(f'screenshots zoeken in {len(todo)} READMEs', flush=True)
    with cf.ThreadPoolExecutor(16) as ex:
        for r, found in zip(todo, ex.map(shots, todo)):
            if found: r['i'] = found
            elif r.get('m'): r.pop('i', None)
            r['ic'] = str(TODAY)
    for r in data: r.pop('_gid', None)
    data.sort(key=lambda r: -r['s'])
    per = {}
    for r in data: per[r.get('src') or 'github'] = per.get(r.get('src') or 'github', 0) + 1
    print('per bron:', per, flush=True)
    with open(P('data.json'), 'w', encoding='utf8') as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(',', ':'))
    print(f'klaar: {added} nieuw, {updated} bijgewerkt, totaal {len(data)}', flush=True)

if __name__ == '__main__':
    main()
