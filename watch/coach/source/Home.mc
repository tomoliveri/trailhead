import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Math;
import Toybox.WatchUi;

const RED = 0xFF4F2E;
const ORANGE = 0xFF4F2E;
const GREY = 0x9A9AAA;
const DIM = 0x55555F;
const GREEN = 0x4ADE80;
const AMBER = 0xFBBF24;

//! Home Command Deck: 3 pages cycled with UP / DOWN:
//!   Page 0: Today Command (countdown, readiness pill, task cards, tomorrow preview, START action pill)
//!   Page 1: Session Blueprint (workout skyline chart, HR/pace/fuel/mind cues, or strength exercise list)
//!   Page 2: Week & Race Radar (Mon-Sun 7-day status strip, weekly km bar, VDOT + Marathon prediction, next checkpoint)
class HomeView extends WatchUi.View {

    var page as Number = 0;

    function initialize() {
        View.initialize();
    }

    function onShow() as Void {
        Coach.refresh();
    }

    function cyclePage(dir as Number) as Void {
        page = (page + dir + 3) % 3;
        WatchUi.requestUpdate();
    }

    function setPage(p as Number) as Void {
        page = p % 3;
        WatchUi.requestUpdate();
    }

    function drawHeaderSun(dc as Dc, w as Number, h as Number, cx as Number) as Void {
        var sy = (h * 0.085).toNumber();
        var sr = (h * 0.036).toNumber();
        // outer warm glow
        dc.setColor(0x3D1428, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle(cx, sy, sr + 4);
        // rising sun disc
        dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle(cx, sy, sr);
        // horizon slice
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - sr - 2, sy + (sr * 0.35).toNumber(), (sr + 2) * 2, 2);
    }

    function drawBezelRing(dc as Dc, w as Number, h as Number, cx as Number, s as Dictionary) as Void {
        var r = w / 2 - 4;
        dc.setPenWidth(4);
        dc.setColor(0x1E1C2A, Graphics.COLOR_TRANSPARENT);
        dc.drawCircle(cx, h / 2, r);
        var cd = s["cd"] != null ? s["cd"] as Number : 150;
        var tot = s["tot"] != null && (s["tot"] as Number) > 0 ? s["tot"] as Number : 158;
        var frac = (tot - cd).toFloat() / tot;
        if (frac < 0.01) {
            frac = 0.01;
        }
        if (frac > 1.0) {
            frac = 1.0;
        }
        var rd = s["rd"];
        var ringCol = RED;
        if (rd instanceof Number) {
            var rv = rd as Number;
            ringCol = rv >= 70 ? GREEN : rv >= 45 ? AMBER : RED;
        }
        dc.setColor(ringCol, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, h / 2, r, Graphics.ARC_CLOCKWISE, 90, 90 - (360 * frac).toNumber());
        dc.setPenWidth(1);
    }

    function drawActionPill(dc as Dc, w as Number, h as Number, cx as Number, text as String, bgCol as Number, fgCol as Number) as Void {
        var fX = Graphics.FONT_XTINY;
        var fh = dc.getFontHeight(fX);
        var py = (h * 0.825).toNumber();
        var maxW = Txt.chord(dc, py + fh / 2, w * 0.08);
        var fitTxt = Txt.fit(dc, text, fX, maxW - w * 0.08);
        var pw = dc.getTextWidthInPixels(fitTxt, fX) + (w * 0.09).toNumber();
        if (pw > maxW) {
            pw = maxW;
        }
        dc.setColor(bgCol, Graphics.COLOR_TRANSPARENT);
        dc.fillRoundedRectangle(cx - pw / 2, py, pw, fh + 2, (fh + 2) / 2);
        dc.setColor(fgCol, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, py + (fh + 2) / 2, fX, fitTxt, Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }

    function drawToday(dc as Dc, w as Number, h as Number, cx as Number, s as Dictionary) as Void {
        var xt = dc.getFontHeight(Graphics.FONT_XTINY);
        var y = h * 0.135;
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, y, Graphics.FONT_XTINY, s["cd"].toString() + " DAYS TO " + (s["race"] instanceof String ? (s["race"] as String).toUpper() : "RACE"), Graphics.TEXT_JUSTIFY_CENTER);
        y += xt * 1.02;

        var rd = s["rd"];
        var vdot = s["vdot"];
        var subLine = "";
        var subCol = GREY;
        if (rd instanceof Number) {
            var r = rd as Number;
            subCol = r >= 70 ? GREEN : r >= 45 ? AMBER : RED;
            subLine = "READY " + r.toString() + "%";
        }
        if (vdot != null) {
            subLine += (subLine.length() > 0 ? " · " : "") + "VDOT " + (vdot instanceof Float || vdot instanceof Double
                ? (vdot as Float).format("%.1f") : vdot.toString());
        }
        if (subLine.length() > 0) {
            dc.setColor(subCol, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, y, Graphics.FONT_XTINY, subLine, Graphics.TEXT_JUSTIFY_CENTER);
        }
        y += xt * 1.25;

        var tasks = Coach.tasks();
        var next = Coach.nextTask();
        var nextIdx = -1;
        for (var q = 0; q < tasks.size(); q++) {
            if ((tasks[q] as Dictionary)["d"] != true) {
                nextIdx = q;
                break;
            }
        }
        var td = s["today"] instanceof Dictionary ? s["today"] as Dictionary : null;
        if (tasks.size() == 0) {
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            y += Txt.block(dc, cx, y, "Rest day", Graphics.FONT_MEDIUM, 1);
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            var rnote = td != null && td["note"] instanceof String ? td["note"] as String : "Recovery is where adaptation happens.";
            Txt.block(dc, cx, y, rnote, Graphics.FONT_XTINY, 2);
        }
        var lineH = dc.getFontHeight(Graphics.FONT_SMALL);
        for (var i = 0; i < tasks.size(); i++) {
            var t = tasks[i] as Dictionary;
            var done = t["d"] == true;
            var isNext = i == nextIdx;
            var left = (w * 0.16).toNumber();
            var chordW = Txt.chord(dc, y + lineH / 2, w * 0.05);
            var avail = chordW - (left - (w - chordW) / 2) - (w * 0.04).toNumber();
            var cy = (y + lineH / 2).toNumber();
            if (done) {
                dc.setColor(GREEN, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(left, cy, 9);
                dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
                dc.setPenWidth(3);
                dc.drawLine(left - 4, cy, left - 1, cy + 3);
                dc.drawLine(left - 1, cy + 3, left + 5, cy - 4);
            } else if (isNext) {
                dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
                dc.setPenWidth(2);
                dc.drawCircle(left, cy, 9);
                dc.fillCircle(left, cy, 4);
            } else {
                dc.setColor(DIM, Graphics.COLOR_TRANSPARENT);
                dc.setPenWidth(2);
                dc.drawCircle(left, cy, 8);
            }
            dc.setPenWidth(1);
            dc.setColor(done ? DIM : Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            var titleTxt = Txt.wrap(dc, t["t"] as String, Graphics.FONT_SMALL, avail, 2);
            dc.drawText(left + 16, y, Graphics.FONT_SMALL, titleTxt, Graphics.TEXT_JUSTIFY_LEFT);
            y += lineH * (titleTxt.find("\n") != null ? 2 : 1);

            var meta = done ? "Done" : (isNext ? "NEXT " : "") + (t["at"] != null ? t["at"].toString() : "");
            if (!done && td != null && t["p"].equals("run")) {
                if (td["m"] != null && (td["m"] as Number) > 0) {
                    meta += " · " + td["m"].toString() + "m";
                }
                if (td["hr"] instanceof Array) {
                    var hr = td["hr"] as Array;
                    meta += " · " + hr[0].toString() + "-" + hr[1].toString();
                }
            }
            dc.setColor(isNext ? RED : GREY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(left + 16, y - 2, Graphics.FONT_XTINY, Txt.fit(dc, meta, Graphics.FONT_XTINY, avail), Graphics.TEXT_JUSTIFY_LEFT);
            y += xt * 1.1;
        }

        var tmr = s["tmr"];
        if (tmr instanceof Dictionary && y < h * 0.72) {
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            var m = tmr["m"] != null && (tmr["m"] as Number) > 0 ? " " + tmr["m"].toString() + "m" : "";
            dc.drawText(cx, h * 0.725, Graphics.FONT_XTINY,
                        Txt.fit(dc, "Tmrw: " + tmr["t"] + m, Graphics.FONT_XTINY, Txt.chord(dc, h * 0.75, w * 0.06)),
                        Graphics.TEXT_JUSTIFY_CENTER);
        }
        var hint = next != null ? "START: GO" : (tasks.size() > 0 ? "ALL DONE TODAY" : "MENU: WORKOUTS");
        if (Outbox.pending() > 0) {
            hint = Outbox.pending().toString() + " TO UPLOAD";
        }
        drawActionPill(dc, w, h, cx, hint, next != null ? RED : RunHud.TRACK, next != null ? Graphics.COLOR_BLACK : GREEN);
    }

    function drawBlueprint(dc as Dc, w as Number, h as Number, cx as Number, s as Dictionary) as Void {
        var fX = Graphics.FONT_XTINY;
        var fhX = dc.getFontHeight(fX);
        var y = h * 0.135;

        RunHud.say(dc, cx, y + fhX / 2.0, "TODAY", fX, AMBER, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.1));
        y += fhX * 1.1;

        var td = s["today"] instanceof Dictionary ? s["today"] as Dictionary : null;
        if (td == null) {
            RunHud.say(dc, cx, h * 0.48, "No plan loaded", Graphics.FONT_SMALL, GREY, w * 0.7);
            return;
        }

        var next = Coach.nextTask();
        var showSec = next != null && next["p"].equals("sec") && td["x"] instanceof Array && (td["x"] as Array).size() > 0;
        var steps = td["s"] instanceof Array ? td["s"] as Array : [] as Array;

        if (!showSec && steps.size() > 0) {
            var title = td["t"] as String;
            RunHud.say(dc, cx, y + fhX / 2.0, title, fX, Graphics.COLOR_WHITE, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.08));
            y += fhX * 1.15;

            // Build skyline weights & intensities
            var n = steps.size();
            var wts = new [n];
            var ints = new [n];
            for (var i = 0; i < n; i++) {
                var st = steps[i] as Dictionary;
                var dt = st["dt"] as Number;
                var v = st["v"] as Number;
                var sec = dt == 0 ? v.toFloat() : dt == 1 ? (v / 1000.0 * 330.0) : 600.0;
                if (sec < 20.0) { sec = 20.0; }
                wts[i] = sec;
                ints[i] = st["i"] != null ? st["i"] : 0;
            }
            var barH = (h * 0.075).toNumber();
            var bw = (w * 0.68).toNumber();
            RunHud.timeline(dc, cx - bw / 2, y, bw, barH, wts, ints, 0, -1.0);
            y += barH + h * 0.025;

            // Stats line: duration, km, HR band
            var stats = "";
            if (td["m"] != null && (td["m"] as Number) > 0) {
                stats += td["m"].toString() + " min";
            }
            if (td["km"] != null && (td["km"] as Numeric).toFloat() > 0) {
                stats += (stats.length() > 0 ? "  •  " : "") + (td["km"] as Numeric).format("%.1f") + " km";
            }
            if (td["hr"] instanceof Array) {
                var hr = td["hr"] as Array;
                stats += (stats.length() > 0 ? "  •  " : "") + hr[0].toString() + "-" + hr[1].toString();
            }
            RunHud.say(dc, cx, y + fhX / 2.0, stats, fX, RunHud.OK, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.06));
            y += fhX * 1.15;

            // Key step targets + fuel/mind/note cues
            var shown = 0;
            for (var j = 0; j < n && shown < 2; j++) {
                var st = steps[j] as Dictionary;
                if ((st["i"] as Number) == 0 || n <= 2) {
                    var desc = (st["n"] as String);
                    if (st["r"] != null) { desc += " " + st["r"]; }
                    if (st["pf"] != null) {
                        desc += ": " + Coach.fmtPace(st["pf"] as Number) + "-" + Coach.fmtPace(st["ps"] as Number) + "/k";
                    } else if (st["hl"] != null) {
                        desc += ": HR " + st["hl"].toString() + "-" + st["hh"].toString();
                    }
                    RunHud.say(dc, cx, y + fhX / 2.0, desc, fX, RunHud.PINK, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.07));
                    y += fhX * 1.05;
                    shown += 1;
                }
            }
            var extra = null;
            if (td["fu"] instanceof Array) {
                var fu = td["fu"] as Array;
                extra = "Fuel: 1st gel @" + ((fu[0] as Number) / 60).toString() + "m, then q" + ((fu[1] as Number) / 60).toString() + "m";
            } else if (td["note"] instanceof String) {
                extra = td["note"] as String;
            }
            if (extra != null && y + fhX < h * 0.80) {
                RunHud.say(dc, cx, y + fhX / 2.0, extra, fX, GREY, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.08));
            }
        } else if (td["x"] instanceof Array && (td["x"] as Array).size() > 0) {
            var secTitle = td["sec"] instanceof String ? td["sec"] as String : "Strength & Mobility";
            RunHud.say(dc, cx, y + fhX / 2.0, secTitle, fX, Graphics.COLOR_WHITE, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.08));
            y += fhX * 1.15;
            var ex = td["x"] as Array;
            for (var k = 0; k < ex.size() && k < 4; k++) {
                var e = ex[k] as Dictionary;
                var line = e["n"] as String;
                if (e["s"] != null) {
                    line += "  " + e["s"].toString() + "x" + (e["r"] != null ? e["r"].toString() : "");
                    if (e["l"] != null) {
                        line += " @" + (e["l"] as Numeric).toNumber().toString() + "kg";
                    }
                }
                RunHud.say(dc, cx, y + fhX / 2.0, line, fX, k == 0 ? RunHud.OK : GREY, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.07));
                y += fhX * 1.05;
            }
            if (ex.size() > 4 && y + fhX < h * 0.80) {
                RunHud.say(dc, cx, y + fhX / 2.0, "+" + (ex.size() - 4).toString() + " more exercises", fX, DIM, w * 0.6);
            }
        } else {
            RunHud.say(dc, cx, h * 0.40, "Active Recovery / Rest", Graphics.FONT_SMALL, GREEN, w * 0.74);
            var note = td["note"] instanceof String ? td["note"] as String : "Sleep 8h+, hydrate, light walk.";
            Txt.block(dc, cx, h * 0.52, note, fX, 2);
        }
        drawActionPill(dc, w, h, cx, "START", RunHud.TRACK, AMBER);
    }

    function drawWeek(dc as Dc, w as Number, h as Number, cx as Number, s as Dictionary) as Void {
        var fX = Graphics.FONT_XTINY;
        var fhX = dc.getFontHeight(fX);
        var y = h * 0.135;

        RunHud.say(dc, cx, y + fhX / 2.0, "THIS WEEK", fX, RunHud.LOW, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.1));
        y += fhX * 1.2;

        // 7-day Mon-Sun visual strip
        var days = ["M", "T", "W", "T", "F", "S", "S"] as Array<String>;
        var wk = s["wk"] instanceof Array ? s["wk"] as Array : null;
        var stripW = (w * 0.72).toNumber();
        var stepX = stripW / 7;
        var x0 = cx - stripW / 2 + stepX / 2;
        var cy = (y + fhX + 11).toNumber();

        for (var i = 0; i < 7; i++) {
            var xi = x0 + i * stepX;
            var st = 0;
            if (wk != null && i < wk.size() && wk[i] instanceof Dictionary) {
                var d = (wk[i] as Dictionary)["d"];
                if (d instanceof Number) {
                    st = d as Number;
                }
            }
            dc.setColor(st == 2 ? Graphics.COLOR_WHITE : GREY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(xi, y, fX, days[i], Graphics.TEXT_JUSTIFY_CENTER);
            if (st == 1) {
                // Done: neon green circle + dark tick
                dc.setColor(GREEN, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(xi, cy, 8);
                dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_TRANSPARENT);
                dc.setPenWidth(2);
                dc.drawLine(xi - 3, cy, xi - 1, cy + 3);
                dc.drawLine(xi - 1, cy + 3, xi + 4, cy - 3);
                dc.setPenWidth(1);
            } else if (st == 2) {
                // Today: glowing double coral ring
                dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
                dc.setPenWidth(2);
                dc.drawCircle(xi, cy, 9);
                dc.fillCircle(xi, cy, 4);
                dc.setPenWidth(1);
            } else if (st == -1) {
                // Rest: dim dot
                dc.setColor(DIM, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(xi, cy, 3);
            } else {
                // Upcoming planned session: hollow ring
                dc.setColor( RunHud.SUB, Graphics.COLOR_TRANSPARENT);
                dc.setPenWidth(2);
                dc.drawCircle(xi, cy, 7);
                dc.setPenWidth(1);
            }
        }
        y = cy + 14;

        // Weekly volume progress bar
        var kmd = s["km_d"] != null ? (s["km_d"] as Numeric).toFloat() : 0.0;
        var kmp = s["km_p"] != null ? (s["km_p"] as Numeric).toFloat() : 0.0;
        var wkTxt = "WEEK  " + kmd.format("%.1f") + " / " + kmp.format("%.1f") + " KM";
        RunHud.say(dc, cx, y + fhX / 2.0, wkTxt, fX, Graphics.COLOR_WHITE, w * 0.78);
        y += fhX + 3;

        var bw = (w * 0.64).toNumber();
        var bh = 7;
        dc.setColor(RunHud.TRACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRoundedRectangle(cx - bw / 2, y, bw, bh, bh / 2);
        if (kmp > 0.0 && kmd > 0.0) {
            var kf = RunHud.clamp01(kmd / kmp);
            var fw = (bw * kf).toNumber();
            dc.setColor(GREEN, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(cx - bw / 2, y, fw < bh ? bh : fw, bh, bh / 2);
        }
        y += bh + h * 0.03;

        // VDOT + Marathon Prediction columns
        var vdot = s["vdot"] instanceof Float || s["vdot"] instanceof Double ? (s["vdot"] as Float).format("%.1f")
            : s["vdot"] != null ? s["vdot"].toString() : "--";
        var pred = s["pred"] instanceof String ? s["pred"] as String : "--";
        var fS = Graphics.FONT_SMALL;
        var fhS = dc.getFontHeight(fS);
        var colW = (w * 0.36).toNumber();
        RunHud.say(dc, cx - colW / 2 - 4, y + fhS * 0.45, vdot, fS, RunHud.OK, colW);
        RunHud.say(dc, cx - colW / 2 - 4, y + fhS + fhX * 0.35, "VDOT", fX, GREY, colW);
        RunHud.say(dc, cx + colW / 2 + 4, y + fhS * 0.45, pred, fS, Graphics.COLOR_WHITE, colW);
        RunHud.say(dc, cx + colW / 2 + 4, y + fhS + fhX * 0.35, "RACE EST", fX, GREY, colW);
        dc.setColor(RunHud.TRACK, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(cx - 1, y + 2, 2, fhS + fhX * 0.65);
        y += fhS + fhX * 0.85;

        // Next Checkpoint
        var cp = s["cp"];
        if (cp instanceof Dictionary && y + fhX < h * 0.82) {
            var cpTxt = "CP " + cp["e"] + " (" + cp["d"] + ") -> " + cp["g"];
            RunHud.say(dc, cx, y + fhX / 2.0, cpTxt, fX, AMBER, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.08));
        }
        drawActionPill(dc, w, h, cx, "MENU", RunHud.TRACK, RunHud.LOW);
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        RunHud.backdrop(dc, w, h, 0.35);
        drawHeaderSun(dc, w, h, cx);

        var s = Coach.sync();
        if (s == null && Cfg.pairing()) {
            var y = h * 0.22;
            dc.setColor(AMBER, Graphics.COLOR_TRANSPARENT);
            y += Txt.block(dc, cx, y, "PAIR WATCH", Graphics.FONT_SMALL, 1);
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            y += Txt.block(dc, cx, y + 4, "Enter this code at " + Cfg.host(), Graphics.FONT_XTINY, 2);
            dc.drawText(cx, y + h * 0.04, Graphics.FONT_MEDIUM, Cfg.pairCode(), Graphics.TEXT_JUSTIFY_CENTER);
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.80, Graphics.FONT_XTINY, "then MENU > Sync now", Graphics.TEXT_JUSTIFY_CENTER);
            return;
        }
        if (s == null) {
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            Txt.block(dc, cx, h * 0.42, "Syncing with your phone...", Graphics.FONT_SMALL, 2);
            return;
        }
        if (Cfg.stale(s)) {
            // never show an old day as today
            var y = h * 0.24;
            dc.setColor(AMBER, Graphics.COLOR_TRANSPARENT);
            y += Txt.block(dc, cx, y, "PLAN OUT OF DATE", Graphics.FONT_SMALL, 1);
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            Txt.block(dc, cx, h * 0.24 + dc.getFontHeight(Graphics.FONT_SMALL) * 1.3,
                      "Last synced " + Cfg.planDay(s) + ". Can't reach your phone: open Garmin Connect, then MENU > Sync now",
                      Graphics.FONT_XTINY, 4);
            dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.83, Graphics.FONT_XTINY, "MENU: sync / free run", Graphics.TEXT_JUSTIFY_CENTER);
            return;
        }

        drawBezelRing(dc, w, h, cx, s);
        RunHud.pageDots(dc, w, h, page, 3);

        if (page == 1) {
            drawBlueprint(dc, w, h, cx, s);
        } else if (page == 2) {
            drawWeek(dc, w, h, cx, s);
        } else {
            drawToday(dc, w, h, cx, s);
        }
    }
}

class HomeDelegate extends WatchUi.BehaviorDelegate {

    var view as HomeView;

    function initialize(v as HomeView) {
        BehaviorDelegate.initialize();
        view = v;
    }

    function onSelect() as Boolean {
        Coach.startNext();
        return true;
    }

    function onPreviousPage() as Boolean {
        view.cyclePage(-1);
        return true;
    }

    function onNextPage() as Boolean {
        view.cyclePage(1);
        return true;
    }

    function onMenu() as Boolean {
        var menu = new WatchUi.Menu2({ :title => WatchUi.loadResource(Rez.Strings.AppName) as String });
        menu.addItem(new WatchUi.MenuItem("Today's run", null, :planned, null));
        menu.addItem(new WatchUi.MenuItem("Today's strength", null, :strength, null));
        menu.addItem(new WatchUi.MenuItem("Session blueprint", "Steps & cues", :blueprint, null));
        menu.addItem(new WatchUi.MenuItem("Week & race radar", "Volume & VDOT", :radar, null));
        menu.addItem(new WatchUi.MenuItem("Free run", null, :run, null));
        menu.addItem(new WatchUi.MenuItem("Free bike", null, :bike, null));
        menu.addItem(new WatchUi.MenuItem("Free walk", null, :walk, null));
        menu.addItem(new WatchUi.MenuItem("Log rest day", null, :rest, null));
        menu.addItem(new WatchUi.MenuItem("Sync now", null, :sync, null));
        WatchUi.pushView(menu, new HomeMenuDelegate(view), WatchUi.SLIDE_UP);
        return true;
    }
}

class HomeMenuDelegate extends WatchUi.Menu2InputDelegate {

    var view as HomeView;

    function initialize(v as HomeView) {
        Menu2InputDelegate.initialize();
        view = v;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        if (id == :planned) {
            Coach.startPlanned();
        } else if (id == :strength) {
            Coach.startStrength();
        } else if (id == :blueprint) {
            view.setPage(1);
        } else if (id == :radar) {
            view.setPage(2);
        } else if (id == :rest) {
            Coach.logRestDay();
        } else if (id == :sync) {
            Coach.syncNow();
        } else {
            Coach.startFree(id == :run ? "run" : id == :bike ? "bike" : "walk");
        }
    }
}
