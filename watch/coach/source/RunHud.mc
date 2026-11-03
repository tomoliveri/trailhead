import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.UserProfile;

//! Running screen renderer. Pure drawing: WorkoutView hands it a model dictionary.
//!
//! Supports 3 live HUD pages cycled with UP / DOWN:
//!   Page 0 (Main HUD): 270-deg 5-zone HR gauge, skyline timeline, huge HR hero with coaching chevrons,
//!                            target zone pill, pace vs step-left columns, and multi-mode bottom ticker.
//!   Page 1 (Pacer & Mechanics): Live pace vs target speed bar, cadence (spm) gauge, in-zone HR %, fuel timer.
//!   Page 2 (Live Zones & Up Next): Real-time 5-zone HR distribution bars + next upcoming workout steps.
module RunHud {

    const ZONE = [0x6C7BFF, 0x22E6FF, 0x39F5A0, 0xFFC83D, 0xFF3B6B];
    const OK = 0x39F5A0;
    const HIGH = 0xFF3B6B;
    const LOW = 0x22E6FF;
    const WHITE = 0xFFFFFF;
    const SUB = 0xB4AEDA;
    const PINK = 0xFF5FA2;
    const VIOLET = 0xA78BFA;
    const GOLD = 0xFFC83D;
    const TRACK = 0x22202E;

    //! HR zone edges [z1 floor, z2 floor, ... z5 floor, max] from the watch profile (falls back to 50-100% of 184).
    var testZones as Array<Number>? = null;   // set by the layout test harness only
    var zoneCache as Array<Number>? = null;

    function zones() as Array<Number> {
        if (testZones != null) {
            return testZones as Array<Number>;
        }
        if (zoneCache != null) {
            return zoneCache as Array<Number>;
        }
        var z = null;
        if (UserProfile has :getHeartRateZones) {
            z = UserProfile.getHeartRateZones(UserProfile.HR_ZONE_SPORT_RUNNING);
        }
        zoneCache = z != null && z.size() >= 6 && z[5] > z[0] ? z as Array<Number> : [92, 110, 129, 147, 166, 184] as Array<Number>;
        return zoneCache as Array<Number>;
    }

    function dim(c as Number, pct as Number) as Number {
        var r = ((c >> 16) & 255) * pct / 100;
        var g = ((c >> 8) & 255) * pct / 100;
        var b = (c & 255) * pct / 100;
        return (r << 16) | (g << 8) | b;
    }

    function clamp01(x as Float) as Float {
        return x < 0.0 ? 0.0 : x > 1.0 ? 1.0 : x;
    }

    //! Step colour by intensity code (0 work, 1 rest, 2 warm-up, 3 cool-down, 4 recovery).
    function stepColor(i as Number) as Number {
        return i == 0 ? PINK : i == 2 ? GOLD : i == 3 ? VIOLET : LOW;
    }

    //! Filled triangle pointing up (dir -1) or down (dir 1) centred on x,y.
    function arrow(dc as Dc, x as Numeric, y as Numeric, size as Numeric, dir as Number, color as Number) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        var pts = [
            [x - size, y + dir * size * 0.6],
            [x + size, y + dir * size * 0.6],
            [x, y - dir * size * 0.9]
        ] as Array<[Numeric, Numeric]>;
        dc.fillPolygon(pts);
    }

    //! Double chevron for stronger visual coaching cue next to hero HR.
    function chevron(dc as Dc, x as Numeric, y as Numeric, size as Numeric, dir as Number, color as Number) as Void {
        arrow(dc, x, y - dir * size * 0.45, size, dir, color);
        arrow(dc, x, y + dir * size * 0.55, size * 0.78, dir, dim(color, 55));
    }

    //! Centre `text` at x,y (vertical centre) and keep it inside the round screen's chord at that row.
    function say(dc as Dc, x as Numeric, y as Numeric, text as String, font as Graphics.FontType, color as Number, maxW as Numeric) as Void {
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawText(x, y, font, Txt.fit(dc, text, font, maxW), Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    //! Usable width at the row centred on y with height fh: the narrower of its top and bottom edges.
    function rowWidth(dc as Dc, y as Numeric, fh as Numeric, margin as Numeric) as Number {
        var a = Txt.chord(dc, y - fh / 2.0, margin);
        var b = Txt.chord(dc, y + fh / 2.0, margin);
        return a < b ? a : b;
    }

    //! First font in the list whose rendering of `text` fits maxW (the last one if none do).
    function pick(dc as Dc, text as String, fonts as Array<Graphics.FontType>, maxW as Numeric) as Graphics.FontType {
        for (var i = 0; i < fonts.size(); i++) {
            if (dc.getTextWidthInPixels(text, fonts[i]) <= maxW) {
                return fonts[i];
            }
        }
        return fonts[fonts.size() - 1];
    }

    //! Page indicator dots along the left bezel curve (around 9 o'clock).
    function pageDots(dc as Dc, w as Number, h as Number, page as Number, total as Number) as Void {
        if (total <= 1) {
            return;
        }
        var cx = w / 2.0;
        var cy = h / 2.0;
        var r = w / 2.0 - 5.0;
        for (var i = 0; i < total; i++) {
            var deg = 180.0 + (i - (total - 1) / 2.0) * 8.0;
            var ang = Math.toRadians(deg);
            var px = (cx + r * Math.cos(ang)).toNumber();
            var py = (cy - r * Math.sin(ang)).toNumber();
            if (i == page) {
                dc.setColor(WHITE, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(px, py, 3);
            } else {
                dc.setColor(0x4A4660, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(px, py, 2);
            }
        }
    }

    // --- dusk backdrop: sky gradient + rising sun + subtle Mount Fuji silhouette ---

    function mix(a as Number, b as Number, f as Float) as Number {
        var r = (((a >> 16) & 255) * (1.0 - f) + ((b >> 16) & 255) * f).toNumber();
        var g = (((a >> 8) & 255) * (1.0 - f) + ((b >> 8) & 255) * f).toNumber();
        var bl = ((a & 255) * (1.0 - f) + (b & 255) * f).toNumber();
        return (r << 16) | (g << 8) | bl;
    }

    function sky(f as Float) as Number {
        if (f < 0.5) {
            return mix(0x000000, 0x0C0820, f / 0.5);
        } else if (f < 0.8) {
            return mix(0x0C0820, 0x240B2B, (f - 0.5) / 0.3);
        }
        return mix(0x240B2B, 0x3C0F30, (f - 0.8) / 0.2);
    }

    function backdrop(dc as Dc, w as Number, h as Number, prog as Float) as Void {
        var bands = 18;
        for (var i = 0; i < bands; i++) {
            var y0 = (h * i / bands).toNumber();
            var y1 = (h * (i + 1) / bands).toNumber();
            dc.setColor(sky((i + 0.5) / bands), Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(0, y0, w, y1 - y0 + 1);
        }
        // sun stays low and dim: it must never fight the HR number for contrast
        var sy = h * (1.22 - 0.42 * clamp01(prog));
        var r = w * 0.22;
        if (sy - r * 1.6 < h) {
            dc.setColor(0x2B0F30, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(w / 2, sy, r * 1.6);
            dc.setColor(0x3A1236, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(w / 2, sy, r * 1.28);
            dc.setColor(0x4E1740, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(w / 2, sy, r);
            // retro sun horizon slices
            dc.setColor(0x240B2B, Graphics.COLOR_TRANSPARENT);
            var s1 = (sy + r * 0.22).toNumber();
            var s2 = (sy + r * 0.48).toNumber();
            if (s1 < h) {
                dc.fillRectangle((w / 2 - r).toNumber(), s1, (r * 2).toNumber(), 2);
            }
            if (s2 < h) {
                dc.fillRectangle((w / 2 - r).toNumber(), s2, (r * 2).toNumber(), 3);
            }
        }
        // subtle Mount Fuji silhouette on the lower horizon
        var fy = (h * 0.96).toNumber();
        var ftop = (h * 0.855).toNumber();
        var fuji = [
            [w * 0.18, fy],
            [w * 0.39, ftop + h * 0.03],
            [w * 0.46, ftop],
            [w * 0.54, ftop],
            [w * 0.61, ftop + h * 0.03],
            [w * 0.82, fy]
        ] as Array<[Numeric, Numeric]>;
        dc.setColor(0x14091E, Graphics.COLOR_TRANSPARENT);
        dc.fillPolygon(fuji);
    }

    // --- whole-workout skyline timeline: one block per step, width = duration, height = intensity ---

    //! weights: planned seconds per step, ints: intensity codes, idx: current step, frac: progress in it (-1 unknown).
    function timeline(dc as Dc, bx as Number, by as Numeric, bw as Number, bh as Numeric, weights as Array, ints as Array, idx as Number, frac as Float) as Void {
        var n = weights.size();
        var total = 0.0;
        for (var i = 0; i < n; i++) {
            total += (weights[i] as Numeric).toFloat();
        }
        if (n == 0 || total <= 0.0) {
            return;
        }
        var gap = n > 24 ? 0 : 1;
        var usable = bw - gap * (n - 1);
        var acc = 0.0;
        var base = (by + bh).toNumber();
        for (var i = 0; i < n; i++) {
            var x0 = bx + (acc / total * usable).toNumber() + i * gap;
            acc += (weights[i] as Numeric).toFloat();
            var x1 = bx + (acc / total * usable).toNumber() + i * gap;
            var wi = x1 - x0;
            if (wi < 1) {
                wi = 1;
            }
            var code = ints[i] as Number;
            var hScale = code == 0 ? 1.0 : code == 2 ? 0.72 : code == 3 ? 0.60 : 0.48;
            var hi = (bh * hScale).toNumber();
            if (hi < 3) {
                hi = 3;
            }
            var yi = base - hi;
            var c = stepColor(code);
            if (i < idx) {
                dc.setColor(dim(c, 32), Graphics.COLOR_TRANSPARENT);
            } else if (i == idx) {
                dc.setColor(dim(c, 45), Graphics.COLOR_TRANSPARENT);
            } else {
                dc.setColor(dim(c, 82), Graphics.COLOR_TRANSPARENT);
            }
            dc.fillRectangle(x0, yi, wi, hi);
            if (i == idx && frac >= 0.0) {
                var fw = (wi * clamp01(frac)).toNumber();
                dc.setColor(c, Graphics.COLOR_TRANSPARENT);
                dc.fillRectangle(x0, yi, fw > 0 ? fw : 1, hi);
                dc.setColor(WHITE, Graphics.COLOR_TRANSPARENT);
                dc.fillRectangle(x0 + fw - 1, by - 1, 2, bh + 2);
            } else if (i == idx) {
                dc.setColor(WHITE, Graphics.COLOR_TRANSPARENT);
                dc.fillRectangle(x0, by - 1, 2, bh + 2);
            }
        }
    }

    // --- sakura petals (finish flourish; p runs 0..1) ---

    function petals(dc as Dc, w as Number, h as Number, p as Float) as Void {
        for (var i = 0; i < 14; i++) {
            var ph = p * 1.3 - i * 0.045;
            if (ph <= 0.0 || ph >= 1.0) {
                continue;
            }
            var x = w * (((i * 37) % 90) + 5) / 100.0 + Math.sin(ph * 9.4 + i) * w * 0.05;
            var y = h * (-0.05 + 1.1 * ph);
            var a = ph * 12.5 + i;
            var sz = w * (0.022 + (i % 3) * 0.008);
            var ca = Math.cos(a);
            var sa = Math.sin(a);
            var pts = [
                [x + ca * sz, y + sa * sz],
                [x - sa * sz * 0.55, y + ca * sz * 0.55],
                [x - ca * sz, y - sa * sz],
                [x + sa * sz * 0.55, y - ca * sz * 0.55]
            ] as Array<[Numeric, Numeric]>;
            dc.setColor(i % 2 == 0 ? 0xFFB7D5 : 0xFF8FC0, Graphics.COLOR_TRANSPARENT);
            dc.fillPolygon(pts);
        }
    }

    // --- outer HR gauge ---------------------------------------------------

    const A0 = 225;    // gauge start angle (bottom left), sweeping clockwise over the top
    const SWEEP = 270;

    function gaugeArc(dc as Dc, cx as Number, cy as Number, r as Number, f0 as Float, f1 as Float, pen as Number, color as Number) as Void {
        if (f1 - f0 < 0.004) {
            return;
        }
        dc.setPenWidth(pen);
        dc.setColor(color, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, A0 - (SWEEP * f0).toNumber(), A0 - (SWEEP * f1).toNumber());
    }

    function gauge(dc as Dc, cx as Number, cy as Number, m as Dictionary, statusColor as Number) as Void {
        var z = zones();
        var lo = z[0].toFloat();
        var span = z[5] - lo;
        var r = cx - 11;
        var tl = m["lo"];
        var th = m["hi"];
        for (var k = 0; k < 5; k++) {
            var f0 = clamp01((z[k] - lo) / span);
            var f1 = clamp01((z[k + 1] - lo) / span);
            gaugeArc(dc, cx, cy, r, f0 + 0.004, f1, 8, dim(ZONE[k], 32));
            if (tl != null) {
                var a = (tl as Number) > z[k] ? tl as Number : z[k];
                var b = (th as Number) < z[k + 1] ? th as Number : z[k + 1];
                if (b > a) {
                    gaugeArc(dc, cx, cy, r, clamp01((a - lo) / span), clamp01((b - lo) / span), 18, ZONE[k]);
                }
            }
        }
        if (tl != null) {
            // bright end-stops so the band reads as a window
            var f0 = clamp01(((tl as Number) - lo) / span);
            var f1 = clamp01(((th as Number) - lo) / span);
            gaugeArc(dc, cx, cy, r + 10, f0, f1, 3, WHITE);
        }
        var hr = m["hr"];
        if (hr != null) {
            var f = clamp01(((hr as Number) - lo) / span);
            var ang = Math.toRadians(A0 - SWEEP * f);
            var mx = cx + r * Math.cos(ang);
            var my = cy - r * Math.sin(ang);
            dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(mx, my, 13);
            dc.setColor(WHITE, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(mx, my, 10);
            dc.setColor(statusColor, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(mx, my, 5);
        }
        dc.setPenWidth(1);
    }

    //! Zone number (1-5) a heart rate falls in; 0 below zone 1.
    function zoneOf(bpm as Number) as Number {
        var z = zones();
        var n = 0;
        for (var k = 0; k < 5; k++) {
            if (bpm >= z[k]) {
                n = k + 1;
            }
        }
        return n;
    }

    //! Subtle outer progress ring for secondary HUD pages (Page 1 & Page 2).
    function subRing(dc as Dc, cx as Number, cy as Number, prog as Float, color as Number) as Void {
        var r = cx - 5;
        dc.setPenWidth(4);
        dc.setColor(TRACK, Graphics.COLOR_TRANSPARENT);
        dc.drawCircle(cx, cy, r);
        var f = clamp01(prog);
        if (f > 0.005) {
            dc.setColor(color, Graphics.COLOR_TRANSPARENT);
            dc.drawArc(cx, cy, r, Graphics.ARC_CLOCKWISE, 90, 90 - (360 * f).toNumber());
        }
        dc.setPenWidth(1);
    }

    //! Bottom alert / paused pill or fallback text shared across HUD pages.
    function drawBottomLine(dc as Dc, w as Number, cx as Number, y as Numeric, fhX as Number, m as Dictionary, fallback as String, fbCol as Number) as Void {
        var by = y + fhX / 2.0;
        var bwid = rowWidth(dc, by, fhX, w * 0.04);
        var msg = m["msg"];
        if (m["paused"] == true || msg != null) {
            var txt = m["paused"] == true ? "PAUSED" : msg as String;
            var col = m["paused"] == true ? GOLD : m["msgc"] != null ? m["msgc"] as Number : PINK;
            var tw = dc.getTextWidthInPixels(Txt.fit(dc, txt, Graphics.FONT_XTINY, bwid - w * 0.06), Graphics.FONT_XTINY) + w * 0.06;
            dc.setColor(col, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(cx - tw / 2, y, tw, fhX, fhX / 2);
            say(dc, cx, by, txt, Graphics.FONT_XTINY, Graphics.COLOR_BLACK, bwid - w * 0.06);
        } else {
            say(dc, cx, by, fallback, Graphics.FONT_XTINY, fbCol, bwid);
        }
    }

    // --- HUD Page 1: Live Pacer, Speed Delta Bar, Cadence & Mechanics -----

    function drawPacer(dc as Dc, w as Number, h as Number, cx as Number, cy as Number, m as Dictionary, sc as Number) as Void {
        subRing(dc, cx, cy, m["prog"] as Float, OK);
        pageDots(dc, w, h, 1, 3);

        var fX = Graphics.FONT_XTINY;
        var fhX = dc.getFontHeight(fX);
        var fM = Graphics.FONT_MEDIUM;
        var fhM = dc.getFontHeight(fM);
        var y = h * 0.11;

        say(dc, cx, y + fhX / 2.0, "PACER", fX, GOLD, rowWidth(dc, y + fhX / 2.0, fhX, w * 0.1));
        y += fhX * 1.05;

        var head = m["step"] as String;
        say(dc, cx, y + fhX / 2.0, head, fX, stepColor(m["si"] as Number), rowWidth(dc, y + fhX / 2.0, fhX, w * 0.08));
        y += fhX * 1.15;

        // Live Pace Hero + Target
        var pace = m["pace"] as String;
        var pstat = m["pstat"] as Number;
        var pcol = pstat == 0 ? OK : pstat == 1 ? GOLD : WHITE;
        var pFont = pick(dc, pace, [Graphics.FONT_NUMBER_MEDIUM, Graphics.FONT_LARGE, fM] as Array<Graphics.FontType>, w * 0.46);
        var fhP = dc.getFontHeight(pFont) * 0.82;
        say(dc, cx - w * 0.14, y + fhP / 2.0, pace, pFont, pcol, w * 0.44);

        var pdelta = m["pdelta"];
        var dTxt = pdelta != null ? ((pdelta as Number) == 0 ? "LOCKED IN" : (pdelta as Number) < 0 ? (pdelta as Number).toString() + "s FAST" : "+" + (pdelta as Number).toString() + "s SLOW") : (m["ptarget"] as String);
        var dCol = pdelta != null ? ((pdelta as Number) == 0 ? OK : (pdelta as Number) < 0 ? GOLD : LOW) : SUB;
        say(dc, cx + w * 0.19, y + fhP * 0.35, dTxt, fX, dCol, w * 0.36);
        say(dc, cx + w * 0.19, y + fhP * 0.75, m["ptarget"] as String, fX, SUB, w * 0.36);
        y += fhP + h * 0.025;

        // Visual Pacer Speed Bar (slow <- [target green band] -> fast)
        var bw = (w * 0.68).toNumber();
        var bh = (h * 0.032).toNumber();
        if (bh < 8) {
            bh = 8;
        }
        var bx = cx - bw / 2;
        dc.setColor(TRACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRoundedRectangle(bx, y, bw, bh, bh / 2);
        // center target zone highlight
        dc.setColor(dim(OK, 40), Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - bw / 6, y, bw / 3, bh);
        if (pdelta != null) {
            // clamp delta within [-30..+30] sec/km; negative delta = faster (right), positive = slower (left)
            var d = -(pdelta as Number).toFloat() / 30.0;
            if (d < -1.0) { d = -1.0; }
            if (d > 1.0) { d = 1.0; }
            var mx = (cx + d * (bw * 0.42)).toNumber();
            dc.setColor(WHITE, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(mx, y + bh / 2, bh / 2 + 3);
            dc.setColor(dCol, Graphics.COLOR_TRANSPARENT);
            dc.fillCircle(mx, y + bh / 2, bh / 2);
        }
        y += bh + h * 0.035;

        // Two columns: Cadence (spm) | In-Zone HR %
        var colW = (w * 0.38).toNumber();
        var lx = cx - colW / 2 - 6;
        var rx = cx + colW / 2 + 6;
        var cad = m["cad"];
        var cadTxt = cad != null ? (cad as Number).toString() : "--";
        var cadCol = cad != null ? ((cad as Number) >= 174 ? OK : (cad as Number) >= 164 ? GOLD : LOW) : SUB;
        var inPct = m["inPct"];
        var pctTxt = inPct != null ? (inPct as Number).toString() + "%" : "--%";
        var pctCol = inPct != null ? ((inPct as Number) >= 75 ? OK : (inPct as Number) >= 50 ? GOLD : HIGH) : SUB;

        say(dc, lx, y + fhM * 0.45, cadTxt, fM, cadCol, colW);
        say(dc, lx, y + fhM + fhX * 0.4, "CADENCE", fX, SUB, colW);
        say(dc, rx, y + fhM * 0.45, pctTxt, fM, pctCol, colW);
        say(dc, rx, y + fhM + fhX * 0.4, "IN TARGET", fX, SUB, colW);
        dc.setColor(TRACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - 1, y + 4, 2, fhM + fhX * 0.7);
        y += fhM + fhX + h * 0.03;

        // Bottom line: fuel countdown or HR + step left
        var hr = m["hr"];
        var fuelRem = m["fuelRem"];
        var fb = fuelRem != null
            ? "GEL IN " + (fuelRem as String) + "  •  " + (m["left"] as String)
            : (hr != null ? "HR " + (hr as Number).toString() + "  •  " : "") + (m["left"] as String) + " " + (m["leftCap"] as String);
        drawBottomLine(dc, w, cx, h * 0.84, fhX, m, fb, fuelRem != null ? GOLD : WHITE);
    }

    // --- HUD Page 2: Live 5-Zone HR Histogram & Upcoming Steps ------------

    function drawZonesNext(dc as Dc, w as Number, h as Number, cx as Number, cy as Number, m as Dictionary, sc as Number) as Void {
        subRing(dc, cx, cy, m["prog"] as Float, VIOLET);
        pageDots(dc, w, h, 2, 3);

        var fX = Graphics.FONT_XTINY;
        var fhX = dc.getFontHeight(fX);
        var y = h * 0.11;

        var hr = m["hr"];
        var curZ = hr != null ? zoneOf(hr as Number) : 0;
        var hdr = "HR ZONES";
        say(dc, cx, y + fhX / 2.0, hdr, fX, sc, rowWidth(dc, y + fhX / 2.0, fhX, w * 0.1));
        y += fhX * 1.15;

        var zs = m["zoneSecs"] as Array<Number>;
        var total = 0;
        var biggest = 1;
        if (zs != null) {
            for (var i = 0; i < 5; i++) {
                var s = zs[i];
                total += s;
                if (s > biggest) {
                    biggest = s;
                }
            }
        }
        var rowH = ((h * 0.40) / 5.0).toNumber();
        for (var z = 5; z >= 1; z--) {
            var secs = zs != null ? zs[z - 1] : 0;
            var yc = y + rowH / 2.0;
            var edge = rowWidth(dc, yc, rowH, w * 0.09);
            var xl = cx - edge / 2;
            var xr = cx + edge / 2;
            var isCur = curZ == z;
            dc.setColor(ZONE[z - 1], Graphics.COLOR_TRANSPARENT);
            dc.drawText(xl, yc, fX, (isCur ? ">" : " ") + "Z" + z.toString(), Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
            var pct = total > 0 ? (secs * 100 / total).toString() + "%" : "0%";
            dc.setColor(isCur ? WHITE : SUB, Graphics.COLOR_TRANSPARENT);
            dc.drawText(xr, yc, fX, pct, Graphics.TEXT_JUSTIFY_RIGHT | Graphics.TEXT_JUSTIFY_VCENTER);

            var lw = dc.getTextWidthInPixels(">Z5", fX) + 6;
            var pw = dc.getTextWidthInPixels("100%", fX) + 6;
            var bx = xl + lw;
            var maxW = xr - pw - bx;
            var bh = (rowH * 0.48).toNumber();
            if (bh < 5) { bh = 5; }
            dc.setColor(TRACK, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(bx, yc - bh / 2, maxW, bh, bh / 2);
            if (secs > 0 && maxW > 0) {
                var bwid = (maxW * secs / biggest).toNumber();
                dc.setColor(ZONE[z - 1], Graphics.COLOR_TRANSPARENT);
                dc.fillRoundedRectangle(bx, yc - bh / 2, bwid < bh ? bh : bwid, bh, bh / 2);
            }
            y += rowH;
        }

        y += h * 0.015;
        dc.setColor(TRACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - w * 0.3, y, (w * 0.6).toNumber(), 1);
        y += h * 0.015;

        // Upcoming steps queue (up to 2 lines)
        var up = m["upNext"] as Array<String>?;
        if (up != null && up.size() > 0) {
            for (var u = 0; u < up.size() && u < 2; u++) {
                var uy = y + fhX / 2.0;
                say(dc, cx, uy, (u == 0 ? "NEXT: " : "THEN: ") + up[u], fX, u == 0 ? WHITE : SUB, rowWidth(dc, uy, fhX, w * 0.08));
                y += fhX * 1.05;
            }
        } else {
            var uy = y + fhX / 2.0;
            say(dc, cx, uy, "FINAL STEP — FINISH STRONG", fX, OK, rowWidth(dc, uy, fhX, w * 0.08));
        }

        var zfb = m["home"] != null ? m["home"] as String : (m["tot"] as String) + "  •  " + (m["dist"] as String);
        drawBottomLine(dc, w, cx, h * 0.84, fhX, m, zfb, m["home"] != null ? OK : WHITE);
    }

    // --- whole screen (routes Page 0, 1, 2) -------------------------------

    function draw(dc as Dc, m as Dictionary) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var cy = h / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        backdrop(dc, w, h, m["prog"] as Float);

        var hr = m["hr"];
        var tl = m["lo"];
        var th = m["hi"];
        var status = 2;   // 0 in zone, 1 too high, -1 too low, 2 unknown
        var sc = SUB;
        if (hr != null && tl != null) {
            if ((hr as Number) > (th as Number)) {
                status = 1;
                sc = HIGH;
            } else if ((hr as Number) < (tl as Number)) {
                status = -1;
                sc = LOW;
            } else {
                status = 0;
                sc = OK;
            }
        } else if (hr != null) {
            sc = ZONE[zoneOf(hr as Number) > 0 ? zoneOf(hr as Number) - 1 : 0];
        }

        var page = m["page"] != null ? m["page"] as Number : 0;
        if (page == 1) {
            drawPacer(dc, w, h, cx, cy, m, sc);
            if ((m["petal"] as Float) >= 0.0) {
                petals(dc, w, h, m["petal"] as Float);
            }
            return;
        } else if (page == 2) {
            drawZonesNext(dc, w, h, cx, cy, m, sc);
            if ((m["petal"] as Float) >= 0.0) {
                petals(dc, w, h, m["petal"] as Float);
            }
            return;
        }

        gauge(dc, cx, cy, m, sc);
        pageDots(dc, w, h, 0, 3);

        var fX = Graphics.FONT_XTINY;
        var fhX = dc.getFontHeight(fX);
        var fMild = Graphics.FONT_MEDIUM;
        var fhM = dc.getFontHeight(fMild);

        // hero font: biggest that leaves room for the other rows
        var heroFont = Graphics.FONT_NUMBER_HOT;
        var fhH = dc.getFontHeight(heroFont);
        var barH = h * 0.032;
        var pillH = fhX * 1.0;
        var colH = fhM + fhX * 0.85;
        var top = h * 0.125;
        var bottom = h * 0.91;
        var used = fhX + barH + fhH * 0.76 + pillH + colH + fhX;
        if ((bottom - top - used) / 5.0 < h * 0.01) {
            heroFont = Graphics.FONT_NUMBER_MEDIUM;
            fhH = dc.getFontHeight(heroFont);
            used = fhX + barH + fhH * 0.76 + pillH + colH + fhX;
        }
        var gap = (bottom - top - used) / 5.0;
        if (gap < 1) {
            gap = 1;
        }
        var y = top;

        // header: step name in its colour
        var si = m["si"] as Number;
        var yc = y + fhX / 2.0;
        var hw = rowWidth(dc, yc, fhX, w * 0.1);
        var head = m["step"] as String;
        if (dc.getTextWidthInPixels(head, fX) > hw) {
            head = m["step2"] as String;
        }
        say(dc, cx, yc, head, fX, stepColor(si), hw);
        y += fhX + gap * 0.6;

        // whole-workout skyline timeline (single block + progress for free runs)
        var bw = Txt.chord(dc, y + barH, w * 0.2);
        if (bw > w * 0.52) {
            bw = (w * 0.52).toNumber();
        }
        timeline(dc, cx - bw / 2, y, bw, barH, m["tlw"] as Array, m["tli"] as Array, m["idx"] as Number, m["frac"] as Float);
        y += barH + gap * 0.9;

        // hero heart rate
        var heroH = fhH * 0.76;
        var hy = y + heroH / 2.0;
        var hrTxt = hr != null ? (hr as Number).toString() : "--";
        dc.setColor(status == 2 && hr == null ? SUB : sc, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, hy, heroFont, hrTxt, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
        if (status == 1 || status == -1) {
            var tw = dc.getTextWidthInPixels(hrTxt, heroFont);
            var ax = tw / 2 + w * 0.085;
            var asz = w * 0.038;
            if (cx - ax - asz > w * 0.12) {
                chevron(dc, cx - ax, hy, asz, status == 1 ? 1 : -1, sc);
                chevron(dc, cx + ax, hy, asz, status == 1 ? 1 : -1, sc);
            }
        }
        y += heroH + gap;

        // zone pill
        var pc = y + pillH / 2.0;
        if (tl != null) {
            var zn = zoneOf(((tl as Number) + (th as Number)) / 2);
            var txt = (zn > 0 ? "Z" + zn.toString() + " " : "") + (tl as Number).toString() + "-" + (th as Number).toString();
            var pw = dc.getTextWidthInPixels(txt, fX) + w * 0.09;
            var maxPw = rowWidth(dc, pc, pillH, w * 0.085);
            if (pw > maxPw) {
                pw = maxPw;
            }
            dc.setColor(sc, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(cx - pw / 2, y, pw, pillH, pillH / 2);
            say(dc, cx, pc, txt, fX, Graphics.COLOR_BLACK, pw - w * 0.04);
        } else if (hr != null) {
            var zn = zoneOf(hr as Number);
            say(dc, cx, pc, zn > 0 ? "ZONE " + zn.toString() : "WARMING UP", fX, sc, rowWidth(dc, pc, pillH, w * 0.085));
        } else {
            say(dc, cx, pc, "FINDING HR", fX, SUB, rowWidth(dc, pc, pillH, w * 0.085));
        }
        y += pillH + gap;

        // two columns: pace | step left
        var vy = y + fhM / 2.0;
        var cy2 = y + fhM + fhX * 0.42;
        var colRowW = rowWidth(dc, y + colH / 2.0, colH, w * 0.07);
        var colW = (colRowW / 2 - 5).toNumber();
        if (colW > w * 0.4) {
            colW = (w * 0.4).toNumber();
        }
        var lx = cx - colW / 2 - 4;
        var rx = cx + colW / 2 + 4;
        var paceColor = m["pstat"] == 0 ? OK : m["pstat"] == 1 ? GOLD : WHITE;
        var numFonts = [Graphics.FONT_MEDIUM, Graphics.FONT_SMALL, Graphics.FONT_TINY, Graphics.FONT_XTINY] as Array<Graphics.FontType>;
        var pace = m["pace"] as String;
        var left = m["left"] as String;
        say(dc, lx, vy, pace, pick(dc, pace, numFonts, colW), paceColor, colW);
        say(dc, lx, cy2, m["ptarget"] as String, fX, SUB, colW);
        say(dc, rx, vy, left, pick(dc, left, numFonts, colW), WHITE, colW);
        say(dc, rx, cy2, m["leftCap"] as String, fX, SUB, colW);
        dc.setColor(TRACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - 1, y + fhM * 0.12, 2, colH - fhM * 0.12);
        y += colH + gap;

        // bottom line: alert / paused pill, else multi-mode ticker (totals / next / cadence / fuel)
        var by = y + fhX / 2.0;
        var bwid = rowWidth(dc, by, fhX, w * 0.02);
        var msg = m["msg"];
        if (m["paused"] == true || msg != null) {
            var txt = m["paused"] == true ? "PAUSED" : msg as String;
            var col = m["paused"] == true ? GOLD : m["msgc"] != null ? m["msgc"] as Number : PINK;
            var tw = dc.getTextWidthInPixels(Txt.fit(dc, txt, fX, bwid - w * 0.06), fX) + w * 0.06;
            dc.setColor(col, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(cx - tw / 2, y, tw, fhX, fhX / 2);
            say(dc, cx, by, txt, fX, Graphics.COLOR_BLACK, bwid - w * 0.06);
        } else {
            var slot = (m["tick"] as Number) % (m["home"] != null ? 5 : 4);
            if (slot == 4) {
                say(dc, cx, by, m["home"] as String, fX, OK, bwid);
            } else if (slot == 1 && m["next"] != null) {
                say(dc, cx, by, "NEXT " + (m["next"] as String), fX, SUB, bwid);
            } else if (slot == 2 && m["cad"] != null) {
                var cstr = (m["cad"] as Number).toString() + " spm";
                if (m["inPct"] != null) {
                    cstr += "  " + (m["inPct"] as Number).toString() + "% Z";
                }
                say(dc, cx, by, cstr, fX, SUB, bwid);
            } else if (slot == 3 && m["fuelRem"] != null) {
                say(dc, cx, by, "GEL IN " + (m["fuelRem"] as String), fX, GOLD, bwid);
            } else {
                say(dc, cx, by, (m["tot"] as String) + "  " + (m["dist"] as String), fX, WHITE, bwid);
            }
        }
        if ((m["petal"] as Float) >= 0.0) {
            petals(dc, w, h, m["petal"] as Float);
        }
    }
}
