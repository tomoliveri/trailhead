#!/usr/bin/env bash
# Build Trailhead Coach for every supported watch into web/watch/<device>/TrailheadCoach.prg.
# Needs the Connect IQ SDK (https://developer.garmin.com/connect-iq/sdk/) and your own developer key:
#   openssl genrsa -out key.pem 4096 && openssl pkcs8 -topk8 -inform PEM -outform DER -in key.pem -out key.der -nocrypt
# Usage: BASE_URL=https://your.host KEY=path/to/key.der tools/build_watch.sh [device ...]
set -euo pipefail
cd "$(dirname "$0")/.."
: "${BASE_URL:?set BASE_URL to your Trailhead server, e.g. https://trailhead.example.org}"
: "${KEY:?set KEY to your Connect IQ developer key (.der)}"
SDK="${CIQ_SDK:-$(cat ~/Library/Application\ Support/Garmin/ConnectIQ/current-sdk.cfg 2>/dev/null || true)}"
[ -x "$SDK/bin/monkeyc" ] || { echo "Connect IQ SDK not found: set CIQ_SDK"; exit 1; }
DEVICES="${*:-fr165 fr165m fr170 fr170m fr255 fr255m fr255s fr255sm fr265 fr265s fr955 fr965 fr970 vivoactive5 vivoactive6 venu3 venu3s fenix7}"
B=build/watch-src
rm -rf "$B" && mkdir -p "$B" && cp -R watch/. "$B/"
sed -i.bak "s|https://example.org|$BASE_URL|g" "$B/coach/resources/settings/properties.xml" "$B/coach/source/Sync.mc"
python3 - "$B/coach/manifest.xml" $DEVICES <<'PY'
import re, sys
p, devs = sys.argv[1], sys.argv[2:]
s = open(p).read()
s = re.sub(r'<iq:products>.*?</iq:products>', '<iq:products>' + ''.join(f'<iq:product id="{d}"/>' for d in devs) + '</iq:products>', s, flags=re.S)
open(p, 'w').write(s)
PY
for d in $DEVICES; do
  mkdir -p "web/watch/$d"
  "$SDK/bin/monkeyc" -d "$d" -f "$B/coach/monkey.jungle" -o "web/watch/$d/TrailheadCoach.prg" -y "$KEY" -w 2>&1 | grep ERROR || true
  find "web/watch/$d" -mindepth 1 ! -name TrailheadCoach.prg -exec rm -rf {} +
  test -s "web/watch/$d/TrailheadCoach.prg" && echo "built $d"
done
rm -rf "$B"
