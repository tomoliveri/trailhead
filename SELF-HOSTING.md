# Running your own Trailhead

## 1. Server

```sh
git clone https://github.com/tomoliveri/trailhead && cd trailhead
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
tools/fetch_pyodide.sh                 # browser runtime + numpy into web/vendor/pyodide
python3 tools/bundle_engine.py         # copies engine/ into web/py for the browser
PORT=3041 .venv/bin/python server.py   # http://127.0.0.1:3041
```

Put it behind HTTPS (WebUSB only works on secure pages). There's an example nginx site in `deploy/nginx.conf` and a
systemd unit in `deploy/trailhead.service`. Data goes in `data/trailhead.db` (SQLite).

## 2. Starting plans (optional, recommended)

The setup refines from the nearest precooked plan. `web/py/precooked.json` ships with a table. To rebuild it on your own
hardware (about an hour on 8 cores):

```sh
.venv/bin/python tools/precook.py --seconds 70
```

## 3. Watch app

Install the [Connect IQ SDK](https://developer.garmin.com/connect-iq/sdk/) and make a developer key:

```sh
openssl genrsa -out key.pem 4096
openssl pkcs8 -topk8 -inform PEM -outform DER -in key.pem -out key.der -nocrypt
BASE_URL=https://trailhead.example.org KEY=key.der tools/build_watch.sh
```

That builds `web/watch/<device>/TrailheadCoach.prg` for every supported watch. The server URL is baked into the app, so
each host builds its own. Keep `key.der` out of the repo.

## 4. Check it

```sh
npm install
node tools/test_e2e.mjs http://127.0.0.1:3041      # setup → plan → watch pairing → sync → upload → plan page
```

## Notes

- Watches have to be in MTP mode to install over USB (Settings › System › USB Mode on the watch). The setup page says so
  if it finds one that isn't.
- The Garmin relay uses Garmin Connect's unofficial API (via `garminconnect`). It can stop working when Garmin changes its
  sign-in.
- The plan bundle sent to the watch covers 21 days. Runners need to open their plan page at least every three weeks.
