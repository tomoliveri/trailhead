import Toybox.Activity;
import Toybox.Lang;
import Toybox.Math;
import Toybox.Position;

//! Turn-for-home on out-and-back runs: when to turn so the planned session ends back where it started.
//!
//! Distance home = the shortest of: straight back to any breadcrumb dropped every 100 m (x a road detour factor)
//! plus the trail from that crumb to the start. Retracing, shortcuts and loops all fall out of the same min().
//! Distance still to cover = the rest of the whole plan: distance steps by their metres, time steps at their pace
//! target, or at the speed the runner has actually held at that intensity today (stops included) slowed by their usual
//! second-half fade (`th`, from the server) and adjusted for climbing or descending back to the start height.
class TurnHome {

    const R = 6371000.0;
    const DETOUR = 1.3;        // road distance / straight line for ground not yet covered (typical street networks)
    const CRUMB_M = 100.0;
    const MAX_CRUMBS = 600;    // 60 km

    var fade as Float;
    var lat0 as Float? = null;
    var lon0 as Float = 0.0;
    var cosLat as Float = 1.0;
    var alt0 as Float? = null;
    var cx as Array<Float> = [] as Array<Float>;
    var cy as Array<Float> = [] as Array<Float>;
    var cd as Array<Float> = [] as Array<Float>;
    var px as Float = 0.0;
    var py as Float = 0.0;
    var fixD as Float = -1.0;   // elapsed distance at the latest good fix
    var lastCrumbD as Float = -1000.0;
    var secs as Array<Float> = [0.0, 0.0, 0.0, 0.0, 0.0] as Array<Float>;
    var dist as Array<Float> = [0.0, 0.0, 0.0, 0.0, 0.0] as Array<Float>;
    var lastD as Float = -1.0;
    var lastCalcT as Number = -10000;

    var homeD as Float? = null;    // metres back to the start
    var margin as Float = 0.0;     // metres of plan left over after getting home (negative: turn now)
    var turnIn as Number? = null;  // seconds until the turn
    var late as Number = 0;        // projected arrival vs plan end, seconds (+ late)
    var state as Number = 0;       // 0 heading out, 2 told to turn

    function initialize(th as Number) {
        fade = th / 1000.0;
    }

    function onPosition(info as Position.Info, d as Float, alt as Float?) as Void {
        if (info.accuracy == null || info.accuracy < Position.QUALITY_USABLE || info.position == null) {
            return;
        }
        var ll = (info.position as Position.Location).toRadians();
        var lat = ll[0].toFloat();
        var lon = ll[1].toFloat();
        if (lat0 == null) {
            lat0 = lat;
            lon0 = lon;
            cosLat = Math.cos(lat).toFloat();
            alt0 = alt;
        }
        px = R * (lon - lon0) * cosLat;
        py = R * (lat - (lat0 as Float));
        fixD = d;
        if (d - lastCrumbD >= CRUMB_M && cx.size() < MAX_CRUMBS) {
            // the first crumb is the first fix; the trail before it (GPS still locking) is in its distance
            cx.add(px);
            cy.add(py);
            cd.add(d);
            lastCrumbD = d;
        }
    }

    //! Called every second while recording; `step` is the current step's intensity code.
    function sample(d as Float, step as Number) as Void {
        if (lastD >= 0.0 && d >= lastD && step >= 0 && step < 5) {
            secs[step] = secs[step] + 1.0;
            dist[step] = dist[step] + (d - lastD);
        }
        lastD = d;
    }

    function speedAt(i as Number) as Float? {
        if (i >= 0 && i < 5 && secs[i] >= 120.0) {
            return dist[i] / secs[i];
        }
        var s = 0.0;
        var m = 0.0;
        for (var k = 0; k < 5; k++) {
            s += secs[k];
            m += dist[k];
        }
        return s >= 120.0 && m > 0.0 ? m / s : null;
    }

    //! Minetti (2002) running cost relative to flat; softened (square root) because pace never tracks it fully.
    function terrain(g as Float) as Float {
        if (g > 0.15) { g = 0.15; }
        if (g < -0.15) { g = -0.15; }
        var c = 155.4 * Math.pow(g, 5) - 30.4 * Math.pow(g, 4) - 43.3 * Math.pow(g, 3) + 46.3 * g * g + 19.5 * g + 3.6;
        var f = Math.sqrt(3.6 / c).toFloat();
        return f < 0.85 ? 0.85 : f > 1.15 ? 1.15 : f;
    }

    //! Recompute (every 5 s). Returns 0 nothing, 2 "turn for home now".
    function update(t as Number, d as Float, alt as Float?, steps as Array, idx as Number, stepStartMs as Number, stepStartDist as Float) as Number {
        if (t - lastCalcT < 5000 || cx.size() == 0 || fixD < 0.0 || idx >= steps.size()) {
            return 0;
        }
        lastCalcT = t;
        // distance home along the best known way
        var best = d + DETOUR * Math.sqrt(px * px + py * py).toFloat();
        for (var i = 0; i < cx.size(); i++) {
            var dx = px - cx[i];
            var dy = py - cy[i];
            var c = cd[i] + DETOUR * Math.sqrt(dx * dx + dy * dy).toFloat();
            if (c < best) {
                best = c;
            }
        }
        best += d - fixD;   // metres run since the last fix
        homeD = best;
        var tf = 1.0;
        if (alt != null && alt0 != null && best > 200.0) {
            tf = terrain(((alt0 as Float) - (alt as Float)) / best);
        }
        // what the rest of the whole plan covers
        var cov = 0.0;
        var vHome = null;
        for (var j = idx; j < steps.size(); j++) {
            var s = steps[j] as Dictionary;
            var dt = s["dt"] as Number;
            var v = (s["v"] as Number).toFloat();
            if (dt == 1) {
                cov += j == idx ? v - (d - stepStartDist) : v;
                continue;
            }
            if (dt != 0) {
                continue;   // open step: no planned length
            }
            var rem = j == idx ? v - (t - stepStartMs) / 1000.0 : v;
            if (rem <= 0.0) {
                continue;
            }
            var spd = null;
            if (s["pf"] != null) {
                spd = 2000.0 / ((s["pf"] as Number) + (s["ps"] as Number));
            } else {
                var obs = speedAt(s["i"] as Number);
                if (obs != null) {
                    spd = obs * (1.0 - fade) * tf;
                    if (vHome == null) {
                        vHome = spd;
                    }
                }
            }
            if (spd == null) {
                return 0;   // too early to know the speeds
            }
            cov += rem * spd;
        }
        var vOut = speedAt((steps[idx] as Dictionary)["i"] as Number);
        if (vOut == null || vOut < 0.5) {
            return 0;
        }
        if (vHome == null) {
            vHome = vOut;
        }
        margin = cov - best;
        turnIn = margin > 0.0 ? (margin / (vOut + vHome)).toNumber() : 0;
        late = (-margin / vHome).toNumber();
        if (state == 2 && margin > 800.0) {
            state = 0;   // plan changed (skipped steps, shortcut): watch again
        }
        if (t < 180000 || best < 300.0) {
            return 0;
        }
        if (state < 2 && margin <= 0.0) {
            state = 2;
            return 2;
        }
        return 0;
    }

    //! Ticker text that fits the bottom row: "TURN IN 6:10" heading out, then "4.1k ON TIME" / "4.1k +1:20".
    function label() as String? {
        if (homeD == null || (homeD as Float) < 300.0) {
            return null;
        }
        if (state < 2 && turnIn != null && (turnIn as Number) > 0) {
            return "TURN IN " + Coach.fmtTime(turnIn as Number);
        }
        var k = ((homeD as Float) / 1000.0).format("%.1f") + "k ";
        if (late > 60) {
            return k + "+" + Coach.fmtTime(late);
        }
        if (late < -60) {
            return k + "-" + Coach.fmtTime(-late);
        }
        return k + "ON TIME";
    }
}
