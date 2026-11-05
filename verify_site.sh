#!/usr/bin/env bash
# Full site rebuild + verification. Run by the cron tick after every chapter.
# Fails loudly rather than shipping a broken page.
set -u
# cd to this script's own directory so the check runs against whatever tree it
# lives in -- the cron checkout, a CI clone, or a scratch copy.
cd "$(dirname "$(readlink -f "$0")")" || exit 1

python3 live_figures.py >/dev/null 2>&1
python3 build.py || { echo "BUILD FAILED"; exit 1; }

fail=0

# the front page must list every part
n_parts=$(python3 -c "import json;q=json.load(open('state/queue.json'));print(len(q.get('parts',[])))")
n_part_html=$(grep -c 'class="part-title"' site/index.html 2>/dev/null || echo 0)
[ "$n_parts" -eq "$n_part_html" ] || { echo "PART MISMATCH: $n_parts parts vs $n_part_html headings"; fail=1; }

# every published chapter has a page
n_pub=$(python3 -c "import json;q=json.load(open('state/queue.json'));print(sum(1 for c in q['chapters'] if c['status']=='published'))")
n_html=$(ls site/chapters/*.html 2>/dev/null | wc -l)
[ "$n_pub" -eq "$n_html" ] || { echo "MISMATCH: $n_pub published vs $n_html pages"; fail=1; }

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
[ -f site/about.html ] || { echo "about page missing"; fail=1; }
grep -q 'src="site.js"' site/about.html || { echo "BAD SCRIPT PATH in about"; fail=1; }

# interactives are wired to ids the JS actually looks for
for pair in "01-tokens:bpe-host" "05-scaled-dot-product:attn-host" "10-kv-cache:kv-host"; do
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
done

if [ "$fail" -eq 0 ]; then
  echo "OK: $n_html pages, gates clean"
else
  echo "SITE CHECKS FAILED"
fi
exit "$fail"
