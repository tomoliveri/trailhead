// Garmin Connect through the stateless relay. Tokens live only in this browser (localStorage); the relay never
// stores credentials or tokens.
const KEY = 'th:garmin';

async function post(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({ error: 'Unexpected reply.' }));
  if (!r.ok) throw new Error(j.error || 'Garmin request failed.');
  return j;
}

export const garmin = {
  tokens: () => localStorage.getItem(KEY),
  connected: () => !!localStorage.getItem(KEY),
  forget: () => localStorage.removeItem(KEY),

  // -> {ok:true} or {mfa:id} when Garmin sends a code
  async login(email, password) {
    const j = await post('/api/garmin/login', { email, password });
    if (j.mfa) return { mfa: j.mfa };
    localStorage.setItem(KEY, j.tokens);
    return { ok: true };
  },

  async mfa(id, code) {
    const j = await post('/api/garmin/mfa', { mfa: id, code });
    localStorage.setItem(KEY, j.tokens);
    return { ok: true };
  },

  async call(call, args = {}) {
    const j = await post('/api/garmin/call', { call, args, tokens: this.tokens() });
    if (j.tokens) localStorage.setItem(KEY, j.tokens);   // refreshed by Garmin
    return j.data;
  },

  async recent(days = 56) {
    const end = new Date(), start = new Date(Date.now() - days * 864e5);
    const iso = (d) => d.toISOString().slice(0, 10);
    return this.call('activities', { startdate: iso(start), enddate: iso(end) });
  },
};
