#!/usr/bin/env bash
# Build tools for the brief (GitHub Actions): every download is retried, so a slow mirror never breaks a send.
set -u
retry() { for i in 1 2 3 4; do "$@" && return 0; echo "retry $i: $*"; sleep $((i * 10)); done; return 1; }
retry sudo apt-get update -qq
retry sudo apt-get install -y -qq poppler-utils libpango-1.0-0 libpangoft2-1.0-0 fontconfig fonts-inter fonts-ibm-plex
retry pip install -q weasyprint==70.0 matplotlib==3.11.2 numpy==2.5.3 pillow pydyf==0.12.1
mkdir -p ~/.fonts ~/.config/fontconfig
for w in Regular Medium SemiBold Bold ExtraBold; do cp /usr/share/fonts/opentype/inter/Inter-$w.otf ~/.fonts/; done
for w in Regular Medium SemiBold Bold; do cp /usr/share/fonts/truetype/ibm-plex/IBMPlexMono-$w.ttf ~/.fonts/; done
cp kit/fonts.conf ~/.config/fontconfig/fonts.conf
base64 -d kit/wordmark.b64 > kit/wordmark.png
base64 -d kit/circles.b64 > kit/circles.png
fc-cache -f
