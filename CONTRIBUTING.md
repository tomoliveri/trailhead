# Contributing

Bug reports and watch requests are welcome as issues. For code:

1. `tools/fetch_pyodide.sh`, `python3 tools/bundle_engine.py`, then `PORT=3041 python3 server.py`.
2. Make the change. Keep the setup copy short and plain.
3. `npm install && node tools/test_e2e.mjs http://127.0.0.1:3041`.
4. Watch changes: build with `tools/build_watch.sh` and check the screens in the Connect IQ simulator
   (`tools/render/render.sh` captures them). Layouts have to work from 218 px to 454 px screens.

The planner in `engine/` is shared with another project, so changes to it may be adapted rather than merged as-is.
