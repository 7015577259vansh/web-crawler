#!/bin/sh
# Run all three crawlers against the shared companies.json.
# Usage:  ./run-all.sh            (full lists)
#         ./run-all.sh --new-only (only openings not seen on earlier runs)
cd "$(dirname "$0")" || exit 1
for who in shakshi mahi vansh; do
  echo "=== $who ==="
  python3 "crawler-$who.py" "$@"
  echo
done
echo "Open jobs-shakshi.html, jobs-mahi.html, jobs-vansh.html in a browser."
