#!/usr/bin/env bash
# Downloads the full Noto Sans SC / Noto Serif SC TTFs into ./fonts (gitignored, ~10 MB each).
set -euo pipefail
cd "$(dirname "$0")/fonts"
fetch() { # family weights tag
  curl -fsS "https://fonts.googleapis.com/css2?family=$1:wght@$2&display=swap" -A "Mozilla/5.0" > "$3.css"
  grep -oE "font-weight: [0-9]+|https://[^)]+" "$3.css" | paste - - | while read -r a b c d; do
    wt=$(echo "$a $b" | grep -oE '[0-9]+' | head -1); url=$(echo "$a $b $c $d" | grep -oE 'https://[^ ]+')
    curl -fsS -o "$3-$wt.ttf" "$url"
  done
}
fetch "Noto+Serif+SC" "500;900" serif
fetch "Noto+Sans+SC" "200;300;400;500;700" sans
