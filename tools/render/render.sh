#!/usr/bin/env bash
# Screenshots of the real watch app (demo build) in the Connect IQ simulator, per device and screen.
# Opens the simulator window while it runs. Output: build/renders/<device>/<shot>.png (raw window captures).
set -euo pipefail
cd "$(dirname "$0")/../.."
SDK="$(cat ~/Library/Application\ Support/Garmin/ConnectIQ/current-sdk.cfg)"
KEY="${KEY:?set KEY to your Connect IQ developer key (.der)}"
export JAVA_HOME=/opt/homebrew/opt/openjdk PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
DEVICES="${@:-fr265 fr165 fr255 vivoactive5}"
B=build/render-src; C=$B/coach; OUT=build/renders
rm -rf "$B" && mkdir -p "$B" "$OUT" && cp -R watch/. "$B/"
python3 tools/render/gen_demo.py "$C/source/DemoData.mc"
cp tools/render/Demo.mc "$C/source/Demo.mc"
python3 - "$C" $DEVICES <<'PY'
import re, sys
c, devs = sys.argv[1], sys.argv[2:]
m = open(f'{c}/manifest.xml').read()
m = re.sub(r'<iq:products>.*?</iq:products>', '<iq:products>' + ''.join(f'<iq:product id="{d}"/>' for d in devs) + '</iq:products>', m, flags=re.S)
open(f'{c}/manifest.xml', 'w').write(m)
a = open(f'{c}/source/CoachApp.mc').read()
a = a.replace('        ensurePairCode();\n', '        ensurePairCode();\n        if (Application.Properties.getValue("demo") == true) {\n            return [new DemoView()];\n        }\n', 1)
open(f'{c}/source/CoachApp.mc', 'w').write(a)
open(f'{c}/resources/settings/properties.xml', 'w').write('''<properties>
    <property id="token" type="string">K7QM3XRP</property>
    <property id="baseUrl" type="string">https://garmin.ttnt.cloud</property>
    <property id="pair" type="boolean">true</property>
    <property id="brand" type="string">Trailhead</property>
    <property id="demo" type="boolean">true</property>
    <property id="demoShot" type="number">0</property>
</properties>''')
s = open(f'{c}/resources/strings/strings.xml').read()
open(f'{c}/resources/strings/strings.xml', 'w').write(s)
PY
pgrep -f "ConnectIQ.app" >/dev/null || { ("$SDK/bin/connectiq" >/dev/null 2>&1 &); sleep 8; }
for d in $DEVICES; do
  mkdir -p "$OUT/$d"
  "$SDK/bin/monkeyc" -d "$d" -f "$C/monkey.jungle" -o "$B/$d.prg" -y "$KEY" -w 2>&1 | grep -E "ERROR" && continue
  rm -f "$OUT/$d"/t*.png
  ("$SDK/bin/monkeydo" "$B/$d.prg" "$d" >/dev/null 2>&1 &)
  sleep 12
  for k in $(seq 0 21); do
    read -r ID X Y W H < <(build/winid) || true
    [ -n "${ID:-}" ] && screencapture -o -x -l "$ID" "$OUT/$d/t$(printf %02d $k).png"
    sleep 1.25
  done
  echo "captured $d"
done
python3 tools/render/crop.py $DEVICES
