#!/usr/bin/env bash
# Rebuild the site and copy it into docs/ for GitHub Pages (branch deploy).
#
# Pages serves docs/ from main. site/ is the build output and stays gitignored;
# docs/ is the committed copy Pages actually serves. Run this after any change to
# content/, then commit docs/.
set -eu
cd "$(dirname "$(readlink -f "$0")")" || exit 1

# Clean generated directories explicitly. The shell may provide `rm`/`cp`
# builtins that do not replace directories in place, which leaves stale
# " 2" copies behind; /bin/rm and /bin/cp always overwrite.
/bin/rm -rf site/chapters site/figures
mkdir -p site/chapters site/figures

python3 diagrams.py
python3 build.py

# The Desktop tree syncs, and a sync pass can drop a byte-identical "* 2.html"
# or "* 3.svg" copy next to a file build.py just wrote, sometimes seconds after
# the write. Nothing links to those, but they break the page-count check and
# /bin/cp -a would carry them into docs/. Drop them from the build output at
# both points; no real page or figure name ends in " <digit>".
find site -name '* [0-9].*' -delete

./verify_site.sh

find site -name '* [0-9].*' -delete

/bin/rm -rf docs
mkdir -p docs
/bin/cp -a site/. docs/

echo "docs/ updated: $(find docs -name '*.html' | wc -l) pages, $(find docs/figures -name '*.svg' | wc -l) figures"
