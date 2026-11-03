#!/usr/bin/env python3
"""Copy the plan engine into web/py/engine for Pyodide, plus a manifest the browser loads.

    python3 tools/bundle_engine.py
"""
import hashlib
import json
import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'engine' if (ROOT / 'engine').is_dir() else ROOT.parent / 'marathon' / 'engine'   # repo copy, else the private source
DST = ROOT / 'web' / 'py' / 'engine'
MODULES = ['__init__', 'model', 'planner', 'builder', 'extras', 'nutrition', 'physiology', 'catalog',
           'run_learning', 'device']

shutil.rmtree(DST, ignore_errors=True)
DST.mkdir(parents=True)
files = []
for m in MODULES:
    shutil.copy(SRC / f'{m}.py', DST / f'{m}.py')
    files.append(f'engine/{m}.py')
files += ['trailhead.py', 'precooked.json']
digest = hashlib.sha256(b''.join((ROOT / 'web' / 'py' / f).read_bytes() for f in files
                                 if (ROOT / 'web' / 'py' / f).exists())).hexdigest()[:12]
(ROOT / 'web' / 'py' / 'manifest.json').write_text(json.dumps({'files': files, 'version': digest}, indent=1))
print('bundled', len(files), 'files, version', digest)
