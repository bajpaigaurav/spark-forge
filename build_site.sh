#!/usr/bin/env bash
# Rebuild the site and copy it into docs/ for GitHub Pages (branch deploy).
#
# Pages serves docs/ from main. site/ is the build output and stays gitignored;
# docs/ is the committed copy Pages actually serves. Run this after any change to
# content/, then commit docs/.
set -eu
cd "$(dirname "$(readlink -f "$0")")" || exit 1

python3 diagrams.py
python3 build.py
./verify_site.sh

rm -rf docs
mkdir -p docs
cp -a site/. docs/

echo "docs/ updated: $(find docs -name '*.html' | wc -l) pages, $(find docs/figures -name '*.svg' | wc -l) figures"
