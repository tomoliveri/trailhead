import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.Timer;
import Toybox.WatchUi;

//! After saving (already uploaded): celebratory SummaryView with falling sakura petals,
//! HR Zone breakdown (ZoneView), perceived effort (1-10) and "how did you feel" (1-5).
module Finish {
    const RPE = ["Very light", "Very light", "Light", "Light", "Moderate", "Moderate", "Hard", "Hard", "Very hard", "Maximum"];
    const FEEL = ["Very weak", "Weak", "Normal", "Strong", "Very strong"];

    //! Total seconds of HR data in the summary's zone histogram.
    function zoneTotal(summary as Dictionary) as Number {
        var z = summary["zone_s"];
        var n = 0;
        if (z instanceof Array) {
            for (var i = 0; i < (z as Array).size(); i++) {
                n += (z as Array)[i] as Number;
            }
        }
        return n;
    }

    //! First screen after saving: celebratory SummaryView (while the session uploads in the background),
    //! then ZoneView (when HR data exists), then RPE & Feel.
    function askEffort(summary as Dictionary) as Void {
        Idle.setRecorder(null);
        Outbox.add(summary);
        Outbox.flush();
        var view = new SummaryView(summary);
        WatchUi.switchToView(view, new SummaryDelegate(view, summary), WatchUi.SLIDE_UP);
    }

    function afterSummary(summary as Dictionary) as Void {
        if (zoneTotal(summary) >= 60) {
            WatchUi.switchToView(new ZoneView(summary), new ZoneDelegate(summary), WatchUi.SLIDE_UP);
            return;
        }
        askRpe(summary);
    }

    function askRpe(summary as Dictionary) as Void {
        var menu = new WatchUi.Menu2({ :title => "Effort (RPE)" });
        for (var i = 1; i <= 10; i++) {
            menu.addItem(new WatchUi.MenuItem(i.toString() + "  " + RPE[i - 1], null, i, null));
        }
        menu.setFocus(3);
        WatchUi.switchToView(menu, new PickDelegate(summary, "rpe"), WatchUi.SLIDE_UP);
    }

    function askFeel(summary as Dictionary) as Void {
        var menu = new WatchUi.Menu2({ :title => "How did you feel?" });
        for (var i = 1; i <= 5; i++) {
            menu.addItem(new WatchUi.MenuItem(FEEL[i - 1], null, i, null));
        }
        menu.setFocus(2);
        WatchUi.switchToView(menu, new PickDelegate(summary, "feel"), WatchUi.SLIDE_LEFT);
    }

    function upload(summary as Dictionary) as Void {
        if (summary["rpe"] != null || summary["feel"] != null) {
            Outbox.add(summary);
        }
        var view = new DoneView();
        WatchUi.switchToView(view, new DoneDelegate(), WatchUi.SLIDE_LEFT);
        Outbox.flushThen(view.method(:onUploaded));
    }
}

//! Celebratory workout summary card with falling sakura petals.
class SummaryView extends WatchUi.View {
    var summary as Dictionary;
    var t0 as Number = 0;
    var anim as Timer.Timer?;

    function initialize(s as Dictionary) {
        View.initialize();
        summary = s;
        t0 = System.getTimer();
    }

    function onShow() as Void {
        t0 = System.getTimer();
        if (anim == null) {
            anim = new Timer.Timer();
        }
        (anim as Timer.Timer).start(method(:tick), 100, true);
    }

    function onHide() as Void {
        stopAnim();
    }

    function stopAnim() as Void {
        if (anim != null) {
            (anim as Timer.Timer).stop();
            anim = null;
        }
    }

    function tick() as Void {
        if (System.getTimer() - t0 > 4500) {
            stopAnim();
        }
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var cy = h / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        RunHud.backdrop(dc, w, h, 1.0);

        // Outer neon green completion bezel ring
        dc.setPenWidth(5);
        dc.setColor(RunHud.OK, Graphics.COLOR_TRANSPARENT);
        dc.drawCircle(cx, cy, w / 2 - 4);
        dc.setPenWidth(1);

        var fX = Graphics.FONT_XTINY;
        var fhX = dc.getFontHeight(fX);
        var fM = Graphics.FONT_MEDIUM;
        var fhM = dc.getFontHeight(fM);
        var y = h * 0.13;

        RunHud.say(dc, cx, y + fhX / 2.0, "SESSION SAVED", fX, RunHud.OK, RunHud.rowWidth(dc, y + fhX / 2.0, fhX, w * 0.1));
        y += fhX * 1.25;

        var dur = summary["duration_s"] != null ? summary["duration_s"] as Number : 0;
        var distM = summary["distance_m"] != null ? (summary["distance_m"] as Numeric).toFloat() : 0.0;

        if (distM >= 50.0) {
            var kmTxt = (distM / 1000.0).format("%.2f") + " km";
            RunHud.say(dc, cx, y + fhM / 2.0, kmTxt, fM, RunHud.WHITE, w * 0.78);
            y += fhM * 1.05;
            var paceS = dur > 0 ? (dur / (distM / 1000.0)).toNumber() : 0;
            var sub = Coach.fmtTime(dur) + (paceS > 0 ? "  •  " + Coach.fmtPace(paceS) + " /km" : "");
            RunHud.say(dc, cx, y + fhX / 2.0, sub, fX, RunHud.SUB, w * 0.8);
            y += fhX * 1.3;
        } else {
            RunHud.say(dc, cx, y + fhM / 2.0, Coach.fmtTime(dur), fM, RunHud.WHITE, w * 0.78);
            y += fhM * 1.05;
            var sets = summary["completed_steps"] != null ? (summary["completed_steps"] as Number) : 0;
            var sub2 = sets > 0 ? sets.toString() + " sets completed" : "Logged to " + Cfg.brand();
            RunHud.say(dc, cx, y + fhX / 2.0, sub2, fX, RunHud.SUB, w * 0.8);
            y += fhX * 1.3;
        }

        // HR & Calories / Target %
        var ahr = summary["avg_hr"];
        var mhr = summary["max_hr"];
        if (ahr != null || mhr != null) {
            var hrLine = "HR " + (ahr != null ? ahr.toString() + " avg" : "") + (mhr != null ? "  •  " + mhr.toString() + " max" : "");
            RunHud.say(dc, cx, y + fhX / 2.0, hrLine, fX, RunHud.PINK, w * 0.82);
            y += fhX * 1.25;
        }

        var pct = summary["in_range_pct"];
        var cal = summary["calories"];
        if (pct != null) {
            var pTxt = (pct as Number).toString() + "% IN TARGET";
            var pCol = (pct as Number) >= 70 ? RunHud.OK : RunHud.GOLD;
            var pw = dc.getTextWidthInPixels(pTxt, fX) + (w * 0.09).toNumber();
            dc.setColor(pCol, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(cx - pw / 2, y, pw, fhX + 2, (fhX + 2) / 2);
            RunHud.say(dc, cx, y + (fhX + 2) / 2.0, pTxt, fX, Graphics.COLOR_BLACK, pw - 8);
        } else if (cal != null) {
            RunHud.say(dc, cx, y + fhX / 2.0, cal.toString() + " kcal", fX, RunHud.GOLD, w * 0.7);
        }

        var by = h * 0.85;
        RunHud.say(dc, cx, by, "START: log effort", fX, RunHud.SUB, Txt.chord(dc, by, w * 0.06));

        var ph = (System.getTimer() - t0) / 4500.0;
        if (ph >= 0.0 && ph <= 1.0) {
            RunHud.petals(dc, w, h, ph);
        }
    }
}

class SummaryDelegate extends WatchUi.BehaviorDelegate {
    var view as SummaryView;
    var summary as Dictionary;

    function initialize(v as SummaryView, s as Dictionary) {
        BehaviorDelegate.initialize();
        view = v;
        summary = s;
    }

    function next() as Boolean {
        view.stopAnim();
        Finish.afterSummary(summary);
        return true;
    }

    function onSelect() as Boolean {
        return next();
    }

    function onBack() as Boolean {
        return next();
    }

    function onTap(evt as WatchUi.ClickEvent) as Boolean {
        return next();
    }
}

class PickDelegate extends WatchUi.Menu2InputDelegate {
    var summary as Dictionary;
    var key as String;

    function initialize(s as Dictionary, k as String) {
        Menu2InputDelegate.initialize();
        summary = s;
        key = k;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        summary[key] = item.getId() as Number;
        if (key.equals("rpe")) {
            Finish.askFeel(summary);
        } else {
            Finish.upload(summary);
        }
    }

    function onBack() as Void {
        // skipping is fine: upload without the missing answer
        Finish.upload(summary);
    }
}

class DoneView extends WatchUi.View {
    var text as String = "";

    function initialize() {
        View.initialize();
        text = "Uploading to\n" + Cfg.brand() + "...";
    }

    function onUploaded(result as String?) as Void {
        text = result != null ? "Saved!\n" + result : "Saved on watch.\nUploads when your\nphone connects.";
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        RunHud.backdrop(dc, w, h, 1.0);
        dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle(cx, h * 0.2, h * 0.07);
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.58, Graphics.FONT_SMALL,
                    Txt.wrap(dc, text, Graphics.FONT_SMALL, w * 0.74, 4),
                    Graphics.TEXT_JUSTIFY_CENTER | Graphics.TEXT_JUSTIFY_VCENTER);
    }
}

class DoneDelegate extends WatchUi.BehaviorDelegate {
    function initialize() {
        BehaviorDelegate.initialize();
    }

    function onSelect() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        return true;
    }
}

//! Time in each HR zone for the session just saved. Any key continues to the effort question.
class ZoneView extends WatchUi.View {
    var summary as Dictionary;

    function initialize(s as Dictionary) {
        View.initialize();
        summary = s;
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        RunHud.backdrop(dc, w, h, 1.0);
        var fX = Graphics.FONT_XTINY;
        var fh = dc.getFontHeight(fX);
        var zs = summary["zone_s"] as Array;
        var total = Finish.zoneTotal(summary);
        var biggest = 1;
        for (var i = 0; i < 5; i++) {
            if ((zs[i] as Number) > biggest) {
                biggest = zs[i] as Number;
            }
        }
        var pct = summary["in_range_pct"];
        var y = h * 0.15;
        RunHud.say(dc, cx, y, pct != null ? pct.toString() + "% IN TARGET" : "TIME IN ZONE", fX,
                   pct != null && (pct as Number) >= 70 ? RunHud.OK : RunHud.GOLD, Txt.chord(dc, y - fh / 2, w * 0.03));
        var rowH = fh * 1.08;
        y = h * 0.27;
        for (var z = 5; z >= 1; z--) {
            var secs = zs[z - 1] as Number;
            var yc = y + fh / 2.0;
            var edge = Txt.chord(dc, yc + fh / 2.0 > h / 2.0 ? yc + fh / 2.0 : yc - fh / 2.0, w * 0.07);
            var xl = cx - edge / 2;
            var xr = cx + edge / 2;
            var label = "Z" + z.toString();
            var lw = dc.getTextWidthInPixels("Z5", fX);
            var pctTxt = (secs * 100 / total).toString() + "%";
            var pw = dc.getTextWidthInPixels("100%", fX);
            dc.setColor(RunHud.ZONE[z - 1], Graphics.COLOR_TRANSPARENT);
            dc.drawText(xl, yc, fX, label, Graphics.TEXT_JUSTIFY_LEFT | Graphics.TEXT_JUSTIFY_VCENTER);
            dc.setColor(RunHud.WHITE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(xr, yc, fX, pctTxt, Graphics.TEXT_JUSTIFY_RIGHT | Graphics.TEXT_JUSTIFY_VCENTER);
            var bx = xl + lw + 8;
            var maxW = xr - pw - 8 - bx;
            var bh = fh * 0.5;
            dc.setColor(RunHud.TRACK, Graphics.COLOR_TRANSPARENT);
            dc.fillRoundedRectangle(bx, yc - bh / 2, maxW, bh, bh / 2);
            if (secs > 0) {
                var bwid = (maxW * secs / biggest).toNumber();
                dc.setColor(RunHud.ZONE[z - 1], Graphics.COLOR_TRANSPARENT);
                dc.fillRoundedRectangle(bx, yc - bh / 2, bwid < bh ? bh : bwid, bh, bh / 2);
            }
            y += rowH;
        }
        var by = h * 0.86;
        RunHud.say(dc, cx, by, "START: next", fX, RunHud.SUB, Txt.chord(dc, by + fh / 2, w * 0.03));
    }
}

class ZoneDelegate extends WatchUi.BehaviorDelegate {
    var summary as Dictionary;

    function initialize(s as Dictionary) {
        BehaviorDelegate.initialize();
        summary = s;
    }

    function next() as Boolean {
        Finish.askRpe(summary);
        return true;
    }

    function onSelect() as Boolean {
        return next();
    }

    function onBack() as Boolean {
        return next();
    }

    function onTap(evt as WatchUi.ClickEvent) as Boolean {
        return next();
    }
}
