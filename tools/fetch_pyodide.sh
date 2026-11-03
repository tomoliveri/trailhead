#!/usr/bin/env bash
# Download the pinned Pyodide runtime + numpy into web/vendor/pyodide and check numpy against the lock file.
set -euo pipefail
cd "$(dirname "$0")/.."
V=314.0.7
CDN="https://cdn.jsdelivr.net/pyodide/v$V/full"
D=web/vendor/pyodide
mkdir -p "$D"
for f in pyodide.mjs pyodide.js pyodide.asm.mjs pyodide.asm.wasm python_stdlib.zip pyodide-lock.json; do
  curl -fsSL -o "$D/$f" "$CDN/$f"
done
NP=$(python3 -c "import json;print(json.load(open('$D/pyodide-lock.json'))['packages']['numpy']['file_name'])")
curl -fsSL -o "$D/$NP" "$CDN/$NP"
python3 - "$D" "$NP" <<'PY'
import hashlib, json, sys
d, f = sys.argv[1], sys.argv[2]
want = json.load(open(f'{d}/pyodide-lock.json'))['packages']['numpy']['sha256']
got = hashlib.sha256(open(f'{d}/{f}', 'rb').read()).hexdigest()
sys.exit(0 if want == got else f'numpy checksum mismatch: {got}')
PY
echo "Pyodide $V ready in $D"
