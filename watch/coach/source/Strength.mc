import Toybox.Activity;
import Toybox.ActivityRecording;
import Toybox.Attention;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Time;
import Toybox.Timer;
import Toybox.WatchUi;

//! Guided strength / mobility session: set by set, draining rest ring with UP/DN +-15s,
//! visual set pills, biomechanical form cues, live recovery HR, and adjustable loads.
class StrengthView extends WatchUi.View {

    var title as String;
    var planned as String?;
    var items as Array<Dictionary> = [] as Array<Dictionary>;
    var idx as Number = 0;
    var session as ActivityRecording.Session?;
    var timer as Timer.Timer;
    var stepStart as Number = 0;
    var startMoment as Number;
    var done as Array<Dictionary> = [] as Array<Dictionary>;
    var paused as Boolean = false;
    var beeped as Boolean = false;
    var lastHr as Number = 0;

    function initialize(t as String, exercises as Array, kind as String?) {
        View.initialize();
        title = t;
        planned = kind;
        for (var i = 0; i < exercises.size(); i++) {
            var e = exercises[i] as Dictionary;
            var n = e["n"] as String;
            var cue = e["c"];
            if (e["s"] == null) {
                items.add({ "k" => "mob", "n" => n, "c" => cue });
                continue;
            }
            var sets = e["s"] as Number;
            var rt = e["rt"] instanceof Number ? e["rt"] as Number : restFor(n);
            for (var k = 1; k <= sets; k++) {
                items.add({ "k" => "set", "n" => n, "set" => k, "sets" => sets, "r" => e["r"], "l" => e["l"], "h" => e["h"], "c" => cue });
                if (!(k == sets && i == exercises.size() - 1)) {
                    var nextName = k == sets ? ((exercises[i + 1] as Dictionary)["n"] as String) : n;
                    var nextCue = k == sets ? (exercises[i + 1] as Dictionary)["c"] : cue;
                    items.add({ "k" => "rest", "n" => nextName, "c" => nextCue, "secs" => rt, "tot" => rt });
                }
            }
        }
        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE] as Array<Sensor.SensorType>);
        var mob = kind != null && kind.equals("mobility");
        session = ActivityRecording.createSession({
            :name => title.length() > 15 ? title.substring(0, 15) : title,
            :sport => Activity.SPORT_TRAINING,
            :subSport => mob ? Activity.SUB_SPORT_FLEXIBILITY_TRAINING : Activity.SUB_SPORT_STRENGTH_TRAINING
        });
        session.start();
        Idle.setRecorder(method(:autoSave));
        startMoment = Time.now().value();
        lastHr = startMoment;
        stepStart = System.getTimer();
        timer = new Timer.Timer();
        timer.start(method(:tick), 500, true);
        buzz(2);
    }

    function restFor(n as String) as Number {
        return (n.find("deadlift") != null || n.find("split squat") != null || n.find("Nordic") != null || n.find("Drop jump") != null) ? 90 : 60;
    }

    //! Machine busy: move the rest of this exercise behind the next one and come back to it.
    function busy() as Boolean {
        var c = cur();
        if (c == null || c["k"].equals("rest")) {
            return false;
        }
        var name = c["n"] as String;
        var mine = [] as Array<Dictionary>;
        var others = [] as Array<Dictionary>;
        for (var i = idx; i < items.size(); i++) {
            var it = items[i];
            if (it["k"].equals("rest")) {
                continue;
            }
            if ((it["n"] as String).equals(name)) {
                it["retry"] = true;
                mine.add(it);
            } else {
                others.add(it);
            }
        }
        if (others.size() == 0) {
            return false;
        }
        var nextName = others[0]["n"] as String;
        var k = 0;
        while (k < others.size() && (others[k]["n"] as String).equals(nextName)) {
            k += 1;
        }
        var seq = others.slice(0, k);
        seq.addAll(mine);
        seq.addAll(others.slice(k, null));
        var out = items.slice(0, idx);
        for (var j = 0; j < seq.size(); j++) {
            out.add(seq[j]);
            if (j + 1 < seq.size() && seq[j]["k"].equals("set")) {
                var rt = restFor(seq[j]["n"] as String);
                out.add({ "k" => "rest", "n" => seq[j + 1]["n"], "c" => seq[j + 1]["c"], "secs" => rt, "tot" => rt });
            }
        }
        items = out;
        stepStart = System.getTimer();
        beeped = false;
        if (WatchUi has :showToast) {
            WatchUi.showToast("Retry after " + nextName, null);
        }
        WatchUi.requestUpdate();
        return true;
    }

    function cur() as Dictionary? {
        return idx < items.size() ? items[idx] : null;
    }

    function buzz(n as Number) as Void {
        if (Attention has :vibrate) {
            var p = n == 2
                ? [new Attention.VibeProfile(100, 250), new Attention.VibeProfile(0, 120), new Attention.VibeProfile(100, 250)]
                : [new Attention.VibeProfile(70, 200)];
            Attention.vibrate(p as Array<Attention.VibeProfile>);
        }
        if (Attention has :playTone) {
            Attention.playTone(n == 2 ? Attention.TONE_LAP : Attention.TONE_KEY);
        }
    }

    function remaining() as Number {
        var c = cur();
        if (c == null || c["secs"] == null) {
            return 0;
        }
        return (c["secs"] as Number) - (System.getTimer() - stepStart) / 1000;
    }

    function tick() as Void {
        if (Idle.heartRate() != null) {
            lastHr = Time.now().value();
        }
        var c = cur();
        if (!paused && c != null && c["k"].equals("rest")) {
            var r = remaining();
            if (r <= 3 && !beeped) {
                beeped = true;
                buzz(1);
            }
            if (r <= 0) {
                next();
                return;
            }
        }
        WatchUi.requestUpdate();
    }

    //! START: this set is done (or skip the rest).
    function next() as Void {
        var c = cur();
        if (c == null) {
            return;
        }
        if (!c["k"].equals("rest")) {
            done.add(c);
            if (session != null) {
                session.addLap();
            }
        }
        idx += 1;
        stepStart = System.getTimer();
        beeped = false;
        buzz(2);
        if (idx >= items.size()) {
            finish();
        }
        WatchUi.requestUpdate();
    }

    function back() as Void {
        if (idx == 0) {
            return;
        }
        idx -= 1;
        if (!items[idx]["k"].equals("rest") && done.size() > 0) {
            done = done.slice(0, done.size() - 1) as Array<Dictionary>;
        }
        stepStart = System.getTimer();
        WatchUi.requestUpdate();
    }

    //! UP/DOWN: during rest, nudges rest timer by +-15s; during set, nudges load by +-1.0 or +-2.5 kg.
    function adjust(dir as Number) as Void {
        var c = cur();
        if (c == null) {
            return;
        }
        if (c["k"].equals("rest") && c["secs"] != null) {
            var ns = (c["secs"] as Number) + dir * 15;
            if (ns < 5) {
                ns = 5;
            }
            c["secs"] = ns;
            var tot = c["tot"] != null ? c["tot"] as Number : 60;
            if (ns > tot) {
                c["tot"] = ns;
            }
            if (remaining() <= 0) {
                next();
                return;
            }
            WatchUi.requestUpdate();
            return;
        }
        if (!c["k"].equals("set") || c["l"] == null) {
            return;
        }
        var curLoad = (c["l"] as Numeric).toFloat();
        var step = (curLoad < 10.0 || (curLoad == 10.0 && dir < 0)) ? 1.0 : 2.5;
        var v = curLoad + dir * step;
        if (v < 0.0) {
            v = 0.0;
        }
        for (var i = idx; i < items.size(); i++) {
            if (items[i]["k"].equals("set") && items[i]["n"].equals(c["n"])) {
                items[i]["l"] = v;
            }
        }
        WatchUi.requestUpdate();
    }

    function pause() as Void {
        paused = true;
        if (session != null && session.isRecording()) {
            session.stop();
        }
    }

    function resume() as Void {
        paused = false;
        if (session != null && !session.isRecording()) {
            session.start();
        }
    }

    function stopAll() as Void {
        timer.stop();
    }

    function summary() as Dictionary {
        var info = Activity.getActivityInfo();
        var agg = {} as Dictionary<String, Dictionary>;
        var order = [] as Array<String>;
        for (var i = 0; i < done.size(); i++) {
            var d = done[i];
            var n = d["n"] as String;
            if (!agg.hasKey(n)) {
                agg[n] = { "n" => n, "s" => 0 };
                order.add(n);
            }
            var a = agg[n] as Dictionary;
            if (d["k"].equals("set")) {
                a["s"] = (a["s"] as Number) + 1;
                a["r"] = d["r"];
                a["l"] = d["l"];
            }
        }
        var ex = [] as Array<Dictionary>;
        for (var j = 0; j < order.size(); j++) {
            ex.add(agg[order[j]] as Dictionary);
        }
        var mob = planned != null && planned.equals("mobility");
        var out = {
            "id" => "watch-" + startMoment.toString(), "start" => startMoment, "sport" => mob ? "mobility" : "strength",
            "planned" => planned, "duration_s" => Time.now().value() - startMoment, "exercises" => ex,
            "completed_steps" => done.size(), "device" => System.getDeviceSettings().partNumber
        };
        if (info != null) {
            out["avg_hr"] = info.averageHeartRate;
            out["max_hr"] = info.maxHeartRate;
            out["calories"] = info.calories;
        }
        return out;
    }

    //! Watch came off mid-session (Idle): keep the sets done, timed up to the last heart beat.
    function autoSave() as Void {
        var s = summary();
        stopAll();
        if (session != null) {
            if (session.isRecording()) {
                session.stop();
            }
            if (done.size() == 0) {
                session.discard();
                return;
            }
            session.save();
        }
        s["duration_s"] = lastHr - startMoment > 60 ? lastHr - startMoment : 60;
        Outbox.add(s);
    }

    function finish() as Void {
        var s = summary();
        stopAll();
        if (session != null) {
            if (session.isRecording()) {
                session.stop();
            }
            session.save();
        }
        Finish.askEffort(s);
    }

    function drawSetPills(dc as Dc, cx as Number, y as Numeric, curSet as Number, totalSets as Number) as Void {
        if (totalSets <= 1 || totalSets > 8) {
            return;
        }
        var gap = 14;
        var x0 = cx - ((totalSets - 1) * gap) / 2;
        for (var s = 1; s <= totalSets; s++) {
            var xi = x0 + (s - 1) * gap;
            if (s < curSet) {
                dc.setColor(GREEN, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(xi, y, 4);
            } else if (s == curSet) {
                dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
                dc.fillCircle(xi, y, 5);
                dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
                dc.drawCircle(xi, y, 6);
            } else {
                dc.setColor(DIM, Graphics.COLOR_TRANSPARENT);
                dc.drawCircle(xi, y, 4);
            }
        }
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var cy = h / 2;
        dc.setColor(Graphics.COLOR_BLACK, Graphics.COLOR_BLACK);
        dc.clear();
        var c = cur();
        if (c == null) {
            return;
        }
        var k = c["k"] as String;
        var frac = items.size() > 0 ? idx.toFloat() / items.size() : 0.0;
        RunHud.backdrop(dc, w, h, frac);

        // Outer ring: overall session completion
        var rOut = w / 2 - 4;
        dc.setPenWidth(5);
        dc.setColor(RunHud.TRACK, Graphics.COLOR_TRANSPARENT);
        dc.drawCircle(cx, cy, rOut);
        if (frac > 0.005) {
            dc.setColor(RED, Graphics.COLOR_TRANSPARENT);
            dc.drawArc(cx, cy, rOut, Graphics.ARC_CLOCKWISE, 90, 90 - (360 * frac).toNumber());
        }

        // Inner ring during rest: live draining countdown arc
        if (k.equals("rest")) {
            var rIn = w / 2 - 12;
            var rem = remaining();
            var tot = c["tot"] != null && (c["tot"] as Number) > 0 ? c["tot"] as Number : 60;
            var rf = RunHud.clamp01(rem.toFloat() / tot);
            var rCol = rem <= 5 ? RED : rem <= 12 ? AMBER : GREEN;
            dc.setPenWidth(5);
            dc.setColor(0x181622, Graphics.COLOR_TRANSPARENT);
            dc.drawCircle(cx, cy, rIn);
            if (rf > 0.01) {
                dc.setColor(rCol, Graphics.COLOR_TRANSPARENT);
                dc.drawArc(cx, cy, rIn, Graphics.ARC_CLOCKWISE, 90, 90 - (360 * rf).toNumber());
            }
        }
        dc.setPenWidth(1);

        var xt = dc.getFontHeight(Graphics.FONT_XTINY);
        var y = h * 0.115;
        var label = k.equals("set") ? "SET " + c["set"].toString() + " OF " + c["sets"].toString() : k.equals("rest") ? "REST  •  UP/DN +-15S" : "MOBILITY";
        if (c["retry"] == true && !k.equals("rest")) {
            label += " (RETRY)";
        }
        dc.setColor(k.equals("rest") ? GREEN : RED, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, y, Graphics.FONT_XTINY, label, Graphics.TEXT_JUSTIFY_CENTER);
        y += xt;

        if (k.equals("set") && c["sets"] instanceof Number) {
            drawSetPills(dc, cx, y + 4, c["set"] as Number, c["sets"] as Number);
            y += 12;
        }

        if (k.equals("rest")) {
            var rem = remaining();
            var rCol = rem <= 5 ? RED : rem <= 12 ? AMBER : GREEN;
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            y += Txt.block(dc, cx, y + 2, "Next: " + c["n"], Graphics.FONT_XTINY, 2);
            dc.setColor(rCol, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, h * 0.34, Graphics.FONT_NUMBER_HOT, Coach.fmtTime(rem), Graphics.TEXT_JUSTIFY_CENTER);
            if (c["c"] instanceof String) {
                var cyCue = h * 0.635;
                RunHud.say(dc, cx, cyCue, c["c"] as String, Graphics.FONT_XTINY, RunHud.LOW, Txt.chord(dc, cyCue, w * 0.08));
            }
        } else {
            dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
            y += Txt.block(dc, cx, y, c["n"] as String, Graphics.FONT_SMALL, 2);
            if (k.equals("set")) {
                var reps = c["r"] != null ? c["r"].toString() : "";
                var ry = y > h * 0.34 ? y : h * 0.34;
                dc.drawText(cx, ry, Graphics.FONT_NUMBER_MEDIUM, reps, Graphics.TEXT_JUSTIFY_CENTER);
                var ly = ry + dc.getFontHeight(Graphics.FONT_NUMBER_MEDIUM) * 0.86;
                var load = c["l"] != null ? (c["l"] as Numeric).format("%.1f").toString() : "";
                if (load.length() > 2 && load.substring(load.length() - 2, load.length()).equals(".0")) {
                    load = load.substring(0, load.length() - 2);
                }
                var loadTxt = c["l"] != null ? "reps  @ " + load + " kg" + (c["h"] != null ? "/hand" : "") : "reps  bodyweight";
                dc.setColor(AMBER, Graphics.COLOR_TRANSPARENT);
                dc.drawText(cx, ly, Graphics.FONT_XTINY, Txt.fit(dc, loadTxt, Graphics.FONT_XTINY, Txt.chord(dc, ly, w * 0.08)),
                            Graphics.TEXT_JUSTIFY_CENTER);
                if (c["c"] instanceof String && ly + xt * 1.1 < h * 0.70) {
                    var cyCue = ly + xt * 1.35;
                    RunHud.say(dc, cx, cyCue, c["c"] as String, Graphics.FONT_XTINY, RunHud.LOW, Txt.chord(dc, cyCue, w * 0.08));
                }
            } else {
                if (c["c"] instanceof String) {
                    dc.setColor(RunHud.LOW, Graphics.COLOR_TRANSPARENT);
                    Txt.block(dc, cx, h * 0.42, c["c"] as String, Graphics.FONT_XTINY, 2);
                } else {
                    dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
                    Txt.block(dc, cx, h * 0.45, "Follow the app guide; START when done", Graphics.FONT_XTINY, 2);
                }
            }
        }

        // Footer: Live HR + step progress + elapsed time
        var elapsed = Time.now().value() - startMoment;
        var hr = Idle.heartRate();
        var foot = (hr != null ? "HR " + hr.toString() + "  •  " : "") + (idx + 1).toString() + "/" + items.size().toString() + "  •  " + Coach.fmtTime(elapsed);
        dc.setColor(GREY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, h * 0.715, Graphics.FONT_XTINY, Txt.fit(dc, foot, Graphics.FONT_XTINY, Txt.chord(dc, h * 0.73, w * 0.06)),
                    Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(paused ? AMBER : (k.equals("rest") ? GREEN : RED), Graphics.COLOR_TRANSPARENT);
        var hint = paused ? "PAUSED - START to resume" : k.equals("rest") ? "START: skip rest" : k.equals("set") && c["l"] != null ? "START: done  •  UP/DN: kg" : "START: done";
        Txt.block(dc, cx, h * 0.79, hint, Graphics.FONT_XTINY, 2);
    }
}

class StrengthDelegate extends WatchUi.BehaviorDelegate {

    var view as StrengthView;

    function initialize(v as StrengthView) {
        BehaviorDelegate.initialize();
        view = v;
    }

    function onSelect() as Boolean {
        if (view.paused) {
            view.resume();
        } else {
            view.next();
        }
        return true;
    }

    function onBack() as Boolean {
        view.back();
        return true;
    }

    function onPreviousPage() as Boolean {
        view.adjust(1);
        return true;
    }

    function onNextPage() as Boolean {
        view.adjust(-1);
        return true;
    }

    function onMenu() as Boolean {
        view.pause();
        var menu = new WatchUi.Menu2({ :title => "Paused" });
        menu.addItem(new WatchUi.MenuItem("Resume", null, :resume, null));
        menu.addItem(new WatchUi.MenuItem("Machine busy", "Do it later", :busy, null));
        menu.addItem(new WatchUi.MenuItem("Finish & save", null, :save, null));
        menu.addItem(new WatchUi.MenuItem("Discard", null, :discard, null));
        WatchUi.pushView(menu, new StrengthPauseDelegate(view), WatchUi.SLIDE_UP);
        return true;
    }
}

class StrengthPauseDelegate extends WatchUi.Menu2InputDelegate {

    var view as StrengthView;

    function initialize(v as StrengthView) {
        Menu2InputDelegate.initialize();
        view = v;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        if (id == :resume) {
            view.resume();
            WatchUi.popView(WatchUi.SLIDE_DOWN);
        } else if (id == :busy) {
            view.resume();
            WatchUi.popView(WatchUi.SLIDE_DOWN);
            if (!view.busy() && (WatchUi has :showToast)) {
                WatchUi.showToast("Nothing to swap in", null);
            }
        } else if (id == :save) {
            WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
            view.finish();
        } else if (id == :discard) {
            Idle.setRecorder(null);
            view.stopAll();
            if (view.session != null) {
                if (view.session.isRecording()) {
                    view.session.stop();
                }
                view.session.discard();
            }
            WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
            WatchUi.popView(WatchUi.SLIDE_DOWN);
        }
    }

    function onBack() as Void {
        view.resume();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
    }
}
