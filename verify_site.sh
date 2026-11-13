#!/usr/bin/env bash
# Full site rebuild + verification. Run by the cron tick after every chapter.
# Fails loudly rather than shipping a broken page.
set -u
# cd to this script's own directory so the check runs against whatever tree it
# lives in -- the cron checkout, a CI clone, or a scratch copy.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

python3 diagrams.py || { echo "DIAGRAMS FAILED"; exit 1; }
python3 build.py || { echo "BUILD FAILED"; exit 1; }

fail=0

# the front page must list every part
n_parts=$(python3 -c "import json;q=json.load(open('state/queue.json'));print(len(q.get('parts',[])))")
n_part_html=$(grep -c 'class="part-head"' site/index.html 2>/dev/null || echo 0)
[ "$n_parts" -eq "$n_part_html" ] || { echo "PART MISMATCH: $n_parts parts vs $n_part_html headings"; fail=1; }

# every published chapter has a page
n_pub=$(python3 -c "import json;q=json.load(open('state/queue.json'));print(sum(1 for c in q['chapters'] if c['status']=='published'))")
n_html=$(ls site/chapters/*.html 2>/dev/null | wc -l)
[ "$n_pub" -eq "$n_html" ] || { echo "MISMATCH: $n_pub published vs $n_html pages"; fail=1; }

# total page count: index, about, glossary and paths at the top level,
# plus one page per published chapter under chapters/
n_all=$(find site -maxdepth 1 -name '*.html' | wc -l)
[ "$((n_pub + 4))" -eq "$((n_all + n_html))" ] || { echo "PAGE COUNT: $((n_all + n_html)) pages, expected $((n_pub + 4)) ($n_pub chapters + index/about/glossary/paths)"; fail=1; }
n_all=$((n_all + n_html))

# no page repeats its own title as a heading
for f in site/chapters/*.html; do
  t=$(grep -o '<h1>[^<]*</h1>' "$f" | head -1 | sed 's/<[^>]*>//g')
  c=$(grep -o "<h3>$t</h3>" "$f" | wc -l)
  [ "$c" -eq 0 ] || { echo "DUP HEADING in $f: $t"; fail=1; }
done

# script path resolves from wherever the page lives
for f in site/chapters/*.html; do
  grep -q 'src="../site.js"' "$f" || { echo "BAD SCRIPT PATH in $f"; fail=1; }
done
grep -q 'src="site.js"' site/index.html || { echo "BAD SCRIPT PATH in index"; fail=1; }
[ -f site/figures.js ] || { echo "figures.js missing"; fail=1; }
grep -q 'src="figures.js"' site/index.html || { echo "BAD FIGURES SCRIPT in index"; fail=1; }
for f in site/chapters/*.html; do
  grep -q 'src="../figures.js"' "$f" || { echo "BAD FIGURES SCRIPT in $f"; fail=1; }
done
python3 - <<'EOF' || fail=1
import glob, os, sys
import review
bad = 0
for cid in review.published_ids():
    spec = review.load_diagram(cid)
    if not spec or not spec.get("needed"):
        continue
    page = open(f'site/chapters/{cid}.html', encoding='utf-8').read()
    if 'class="chapter-figure"' not in page:
        print('FIGURE: no figure in', cid)
        bad = 1
    figs = spec.get("figures")
    if figs:
        for fig in figs:
            fid = fig.get("id")
            if not fid:
                print('FIGURE: missing id in', cid)
                bad = 1
                continue
            p = f'site/figures/{cid}-{fid}.svg'
            if not os.path.exists(p):
                print('FIGURE: missing svg', p)
                bad = 1
            if f'data-fig-id="{fid}"' not in page:
                print('FIGURE: not placed', cid, fid)
                bad = 1
            anchor = fig.get("anchor")
            if anchor and f'id="{anchor}"' not in page:
                print('FIGURE: bad anchor', cid, fid, anchor)
                bad = 1
    else:
        p = f'site/figures/{cid}.svg'
        if not os.path.exists(p):
            print('FIGURE: missing svg', p)
            bad = 1
        if f'data-fig-id="{cid}"' not in page:
            print('FIGURE: not placed', cid)
            bad = 1
for p in glob.glob('site/figures/*.svg'):
    svg = open(p, encoding='utf-8').read()
    if '<title' not in svg or '<desc' not in svg:
        print('FIGURE: missing title/desc', p)
        bad = 1
sys.exit(bad)
EOF
[ -f site/about.html ] || { echo "about page missing"; fail=1; }
grep -q 'src="site.js"' site/about.html || { echo "BAD SCRIPT PATH in about"; fail=1; }

# the paths page is built, linked from index and about, and every chapter id in
# every path resolves to a published chapter
[ -f site/paths.html ] || { echo "paths page missing"; fail=1; }
grep -q 'src="site.js"' site/paths.html || { echo "BAD SCRIPT PATH in paths"; fail=1; }
grep -q 'href="paths.html"' site/index.html || { echo "paths not linked from index"; fail=1; }
grep -q 'href="paths.html"' site/about.html || { echo "paths not linked from about"; fail=1; }
if [ -f content/paths.json ]; then
  python3 - <<'EOF' || fail=1
import json, os, re, sys
paths = json.load(open('content/paths.json', encoding='utf-8'))
q = json.load(open('state/queue.json', encoding='utf-8'))
published = {c['id'] for c in q['chapters'] if c['status'] == 'published'}
if not paths:
    print('PATHS: content/paths.json is empty')
    sys.exit(1)
bad = 0
for p in paths:
    chs = p['chapters']
    if not chs:
        print('PATHS: empty chapter list in', p['id'])
        bad = 1
    if len(chs) != len(set(chs)):
        dup = sorted({c for c in chs if chs.count(c) > 1})
        print('PATHS: duplicate chapters in', p['id'], dup)
        bad = 1
    unknown = [c for c in chs if c not in published]
    if unknown:
        print('PATHS: not published in', p['id'], ', '.join(unknown))
        bad = 1
    for field in ('id', 'title', 'who', 'why'):
        if not p.get(field):
            print('PATHS: missing', field, 'in', p.get('id'))
            bad = 1
ids = [p['id'] for p in paths]
if len(ids) != len(set(ids)):
    print('PATHS: duplicate path id')
    bad = 1
html = open('site/paths.html', encoding='utf-8').read()
for p in paths:
    if f'id="{p["id"]}"' not in html:
        print('PATHS: path missing from page:', p['id'])
        bad = 1
    for c in p['chapters']:
        if f'href="chapters/{c}.html"' not in html:
            print('PATHS: chapter link missing on page:', c)
            bad = 1
# the index strip must carry one link per path, each with a time estimate
idx = open('site/index.html', encoding='utf-8').read()
strip = re.search(r'<nav class="paths-strip".*?</nav>', idx, re.S)
if not strip:
    print('PATHS: no strip on the front page')
    bad = 1
else:
    n = len(re.findall(r'href="paths\.html#', strip.group(0)))
    if n != len(paths):
        print('PATHS: strip has', n, 'links for', len(paths), 'paths')
        bad = 1
    if len(re.findall(r'class="p-when">about ', strip.group(0))) != len(paths):
        print('PATHS: strip is missing time estimates')
        bad = 1
sys.exit(bad)
EOF
fi

# the glossary is built and every chapter pointer on it resolves
[ -f site/glossary.html ] || { echo "glossary page missing"; fail=1; }
grep -q 'src="site.js"' site/glossary.html || { echo "BAD SCRIPT PATH in glossary"; fail=1; }
grep -q 'href="glossary.html"' site/index.html || { echo "glossary not linked from index"; fail=1; }
grep -q 'href="glossary.html"' site/about.html || { echo "glossary not linked from about"; fail=1; }
if [ -f content/glossary.json ]; then
  python3 - <<'EOF' || fail=1
import glob, json, os, re, sys
entries = json.load(open('content/glossary.json', encoding='utf-8'))
ids = {os.path.basename(p)[:-3] for p in glob.glob('content/chapters/*.md')}
bad = [e['term'] for e in entries if e['chapter'] not in ids]
if bad:
    print('GLOSSARY: unknown chapter for', ', '.join(bad))
    sys.exit(1)
slugs = [re.sub(r'[^a-z0-9]+', '-', e['term'].lower()).strip('-') for e in entries]
if len(slugs) != len(set(slugs)):
    print('GLOSSARY: duplicate anchor slug')
    sys.exit(1)
html = open('site/glossary.html', encoding='utf-8').read()
missing = [s for s in slugs if f'id="{s}"' not in html]
if missing:
    print('GLOSSARY: anchors missing from page:', ', '.join(missing))
    sys.exit(1)
# no chapter may exceed the chip cap
for f in glob.glob('site/chapters/*.html'):
    page = open(f, encoding='utf-8').read()
    m = re.search(r'<p class="terms">(.*?)</p>', page, re.S)
    n = len(re.findall(r'glossary\.html#', m.group(1))) if m else 0
    if n > 8:
        print('TERM CHIPS over cap in', f, n)
        sys.exit(1)
EOF
fi

# interactives are wired to ids the JS actually looks for
for pair in "01-tokens:token-forest-host" "05-scaled-dot-product:attn-host" "10-kv-cache:kv-host"; do
  ch="${pair%%:*}"; wid="${pair##*:}"
  [ -f "site/chapters/$ch.html" ] || continue
  grep -q "id=\"$wid\"" "site/chapters/$ch.html" || { echo "widget $wid missing in $ch"; fail=1; }
done

# every published chapter still passes both gates
for f in content/chapters/*.md; do
  id=$(basename "$f" .md)
  st=$(python3 -c "import json,sys;q=json.load(open('state/queue.json'));print(next((c['status'] for c in q['chapters'] if c['id']=='$id'),'?'))")
  [ "$st" = "published" ] || continue
  python3 skills/slop_gate.py "$f" >/dev/null 2>&1 || { echo "SLOP GATE FAIL: $f"; fail=1; }
  python3 skills/fact_gate.py "$f" content/sources.json >/dev/null 2>&1 || { echo "FACT GATE FAIL: $f"; fail=1; }
  python3 skills/consistency_gate.py "$f" >/dev/null 2>&1 || { echo "CONSISTENCY GATE FAIL: $f"; fail=1; }
done

if [ "$fail" -eq 0 ]; then
  echo "OK: $n_all pages, gates clean"
else
  echo "SITE CHECKS FAILED"
fi
exit "$fail"
