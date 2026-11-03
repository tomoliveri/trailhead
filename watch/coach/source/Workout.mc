import Toybox.Activity;
import Toybox.ActivityRecording;
import Toybox.Attention;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Position;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Time;
import Toybox.Timer;
import Toybox.WatchUi;

//! Guided workout: steps from the plan, pace + HR targets, vibration when HR leaves the range.
class WorkoutView extends WatchUi.View {

    var title as String;
    var sport as String;
    var planned as String?;
    var steps as Array;
    var idx as Number = 0;
    var paused as Boolean = false;
    var session as ActivityRecording.Session?;
    var stepStartMs as Number = 0;
    var stepStartDist as Float = 0.0;
    var highSince as Number? = null;
    var lowSince as Number? = null;
    var lastAlert as Number = -120000;
    var inRange as Number = 0;
    var withHr as Number = 0;
    var msg as String? = null;
    var msgUntil as Number = 0;
    var timer as Timer.Timer;
    var lastInfo as Activity.Info? = null;
    var msgColor as Number? = null;
    var weights as Array = [] as Array;
    var ints as Array = [] as Array;
    var totalW as Float = 0.0;
    var zoneSecs as Array<Number> = [0, 0, 0, 0, 0] as Array<Number>;
    var lastCd as Number = -1;
    var fuelEvery as Number = 0;
    var nextFuelS as Number = 0;
    var fuelCount as Number = 0;
    var mindAtS as Number = 0;
    var mindText as String? = null;
    var petalT0 as Number = 0;
    var animTimer as Timer.Timer? = null;
    var lastHrT as Number = -1;
    var turn as TurnHome? = null;

    function initialize(t as String, sp as String, st as Array, kind as String?, fu as Array?, mc as Array?) {
        View.initialize();
        title = t;
        sport = sp;
        steps = st;
        planned = kind;
        if (fu != null && fu.size() >= 2 && fu[0] instanceof Number && fu[1] instanceof Number && (fu[1] as Number) > 0) {
            nextFuelS = fu[0] as Number;
            fuelEvery = fu[1] as Number;
        }
        // mental-skills prompt (e.g. "MIND: SELF-TALK" for the last 25 min of a long run)
        if (mc != null && mc.size() >= 2 && mc[0] instanceof Number && mc[1] instanceof String) {
            mindAtS = mc[0] as Number;
            mindText = mc[1] as String;
        }
        weigh();
        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE] as Array<Sensor.SensorType>);
        if (!sp.equals("bike")) {
            Position.enableLocationEvents(Position.LOCATION_CONTINUOUS, method(:onPosition));
        }
        var sportId = Activity.SPORT_RUNNING;
        if (sp.equals("bike")) {
            sportId = Activity.SPORT_CYCLING;
        } else if (sp.equals("walk")) {
            sportId = Activity.SPORT_WALKING;
        }
        session = ActivityRecording.createSession({ :name => t.length() > 15 ? t.substring(0, 15) : t, :sport => sportId });
        session.start();
        Idle.setRecorder(method(:autoSave));
        timer = new Timer.Timer();
        timer.start(method(:tick), 1000, true);
        flash(stepName(), 4, stepColor());
        buzz(2);
    }

    function onPosition(info as Position.Info) as Void {
        if (turn != null && !paused) {
            var a = Activity.getActivityInfo();
            var d = a != null && a.elapsedDistance != null ? a.elapsedDistance as Float : 0.0;
            var alt = a != null && a.altitude != null ? a.altitude as Float : null;
            (turn as TurnHome).onPosition(info, d, alt);
        }
    }

    //! Out-and-back guidance for planned runs (`th` = the runner's usual second-half slowdown, per mille).
    function enableTurnHome(th as Number) as Void {
        if (!sport.equals("bike") && totalW >= 1200.0 && !(steps.size() == 1 && ((steps[0] as Dictionary)["dt"] as Number) == 2)) {
            turn = new TurnHome(th);
        }
    }

    function cur() as Dictionary {
        return steps[idx < steps.size() ? idx : steps.size() - 1] as Dictionary;
    }

    function stepName() as String {
        var s = cur();
        var n = s["n"] as String;
        if (s["r"] != null) {
            n = n + " " + s["r"];
        }
        return n;
    }

    function flash(text as String, seconds as Number, color as Number) as Void {
        msg = text;
        msgColor = color;
        msgUntil = System.getTimer() + seconds * 1000;
    }

    function stepColor() as Number {
        return idx < steps.size() ? RunHud.stepColor(cur()["i"] as Number) : RunHud.PINK;
    }

    //! Planned seconds per step (distance steps estimated from their pace target), for the timeline and the sun.
    function weigh() as Void {
        var n = steps.size();
        weights = new [n];
        ints = new [n];
        totalW = 0.0;
        for (var i = 0; i < n; i++) {
            var s = steps[i] as Dictionary;
            var dt = s["dt"] as Number;
            var v = s["v"] as Number;
            var sec = 600.0;
            if (dt == 0) {
                sec = v.toFloat();
            } else if (dt == 1) {
                var pace = s["pf"] != null ? ((s["pf"] as Number) + (s["ps"] as Number)) / 2.0 : 360.0;
                sec = v / 1000.0 * pace;
            }
            if (sec < 5.0) {
                sec = 5.0;
            }
            weights[i] = sec;
            ints[i] = s["i"];
            totalW += sec;
        }
    }

    function stepFrac(t as Number, d as Float) as Float {
        if (idx >= steps.size()) {
            return 1.0;
        }
        var s = cur();
        var dt = s["dt"] as Number;
        var v = s["v"] as Number;
        var f = 0.0;
        if (dt == 0 && v > 0) {
            f = ((t - stepStartMs) / 1000.0) / v;
        } else if (dt == 1 && v > 0) {
            f = (d - stepStartDist) / v;
        }
        return f < 0.0 ? 0.0 : f > 1.0 ? 1.0 : f;
    }

    //! Session progress 0..1 (drives the rising sun).
    function progress(t as Number, d as Float) as Float {
        if (idx >= steps.size()) {
            return 1.0;
        }
        if (steps.size() == 1 && (cur()["dt"] as Number) == 2) {
            var f = t / 3600000.0;   // free run: the sun takes an hour
            return f > 1.0 ? 1.0 : f;
        }
        var done = 0.0;
        for (var i = 0; i < idx; i++) {
            done += weights[i] as Float;
        }
        done += (weights[idx] as Float) * stepFrac(t, d);
        return totalW > 0.0 ? done / totalW : 0.0;
    }

    //! Haptic language: 0 countdown tick, 1 too high (three sharp), 2 new step, 3 too low (double), 4 fuel (da-da-daaa),
    //! 5 turn for home (three long).
    function pattern(kind as Number) as Array<Attention.VibeProfile> {
        if (kind == 0) {
            return [new Attention.VibeProfile(60, 90)] as Array<Attention.VibeProfile>;
        }
        if (kind == 1) {
            return [new Attention.VibeProfile(100, 140), new Attention.VibeProfile(0, 90),
                    new Attention.VibeProfile(100, 140), new Attention.VibeProfile(0, 90),
                    new Attention.VibeProfile(100, 140)] as Array<Attention.VibeProfile>;
        }
        if (kind == 3) {
            return [new Attention.VibeProfile(70, 220), new Attention.VibeProfile(0, 110),
                    new Attention.VibeProfile(70, 220)] as Array<Attention.VibeProfile>;
        }
        if (kind == 4) {
            return [new Attention.VibeProfile(100, 110), new Attention.VibeProfile(0, 90),
                    new Attention.VibeProfile(100, 110), new Attention.VibeProfile(0, 90),
                    new Attention.VibeProfile(100, 450)] as Array<Attention.VibeProfile>;
        }
        if (kind == 5) {
            return [new Attention.VibeProfile(100, 500), new Attention.VibeProfile(0, 200),
                    new Attention.VibeProfile(100, 500), new Attention.VibeProfile(0, 200),
                    new Attention.VibeProfile(100, 500)] as Array<Attention.VibeProfile>;
        }
        return [new Attention.VibeProfile(100, 300), new Attention.VibeProfile(0, 150),
                new Attention.VibeProfile(100, 300)] as Array<Attention.VibeProfile>;
    }

    function buzz(kind as Number) as Void {
        if (Attention has :vibrate) {
            Attention.vibrate(pattern(kind));
        }
        if (kind != 0 && Attention has :playTone) {
            Attention.playTone(kind == 1 ? Attention.TONE_ALERT_HI : kind == 3 ? Attention.TONE_ALERT_LO : Attention.TONE_LAP);
        }
    }

    function tick() as Void {
        var info = Activity.getActivityInfo() as Activity.Info;
        lastInfo = info;
        if (paused) {
            WatchUi.requestUpdate();
            return;
        }
        var t = info.timerTime != null ? info.timerTime as Number : 0;
        var d = info.elapsedDistance != null ? info.elapsedDistance as Float : 0.0;
        var s = cur();
        if (idx < steps.size()) {
            var dt = s["dt"] as Number;
            var v = s["v"] as Number;
            if ((dt == 0 && (t - stepStartMs) / 1000 >= v) || (dt == 1 && d - stepStartDist >= v)) {
                nextStep(t, d);
                s = cur();
            }
        }
        if (turn != null) {
            var th = turn as TurnHome;
            th.sample(d, idx < steps.size() ? s["i"] as Number : -1);
            var alt = info.altitude != null ? info.altitude as Float : null;
            var cue = th.update(t, d, alt, steps, idx, stepStartMs, stepStartDist);
            if (cue == 2) {
                flash("TURN HOME", 12, RunHud.OK);
                buzz(5);
            }
        }
        var hr = info.currentHeartRate;
        if (hr != null) {
            lastHrT = t;
            var zi = RunHud.zoneOf(hr) - 1;
            if (zi < 0) {
                zi = 0;
            }
            zoneSecs[zi] = zoneSecs[zi] + 1;
        }
        // countdown: a gentle tick at 10 s and 3-2-1 before a timed step ends
        if (idx < steps.size() && (s["dt"] as Number) == 0 && (s["v"] as Number) >= 25) {
            var rem = (s["v"] as Number) - (t - stepStartMs) / 1000;
            if (rem != lastCd && (rem == 10 || (rem >= 1 && rem <= 3))) {
                lastCd = rem;
                buzz(0);
            }
        }
        // fuel: gel / carbs on the plan's schedule
        if (fuelEvery > 0 && t / 1000 >= nextFuelS) {
            fuelCount += 1;
            nextFuelS += fuelEvery;
            flash("GEL NOW #" + fuelCount.toString(), 8, RunHud.GOLD);
            buzz(4);
        }
        if (mindText != null && t / 1000 >= mindAtS) {
            flash(mindText as String, 10, RunHud.OK);
            buzz(2);
            mindText = null;
        }
        if (hr != null && s["hl"] != null) {
            var lo = s["hl"] as Number;
            var hi = s["hh"] as Number;
            withHr += 1;
            if (hr >= lo && hr <= hi) {
                inRange += 1;
            }
            if (hr > hi + 3) {
                if (highSince == null) {
                    highSince = t;
                } else if (t - highSince > 15000 && t - lastAlert > 60000) {
                    lastAlert = t;
                    flash("EASE OFF", 5, RunHud.HIGH);
                    buzz(1);
                }
            } else {
                highSince = null;
            }
            // only nag to speed up on work steps with a demanding target
            if (hr < lo - 5 && (s["i"] as Number) == 0 && lo >= 150) {
                if (lowSince == null) {
                    lowSince = t;
                } else if (t - lowSince > 30000 && t - lastAlert > 60000) {
                    lastAlert = t;
                    flash("PICK IT UP", 5, RunHud.LOW);
                    buzz(3);
                }
            } else {
                lowSince = null;
            }
        }
        WatchUi.requestUpdate();
    }

    //! Advance to the next step (automatic at the end of a step, or manual with LAP).
    function nextStep(t as Number, d as Float) as Void {
        if (idx >= steps.size()) {
            if (session != null) {
                session.addLap();
            }
            return;
        }
        // Strides and their walk-backs (time steps under 90 s) fold into the next lap: a lap there only made
        // the watch/phone announce useless "lap time 1 minute" prompts.
        var done = steps[idx] as Dictionary;
        var shortStep = (done["dt"] as Number) == 0 && (done["v"] as Number) < 90;
        idx += 1;
        stepStartMs = t;
        stepStartDist = d;
        highSince = null;
        lowSince = null;
        lastCd = -1;
        if (session != null && !shortStep) {
            session.addLap();
        }
        buzz(2);
        if (idx < steps.size()) {
            flash(stepName(), 5, stepColor());
        } else {
            flash("PLAN DONE", 8, RunHud.OK);
            if (steps.size() > 1 || ((steps[0] as Dictionary)["dt"] as Number) != 2) {
                startPetals();
            }
        }
    }

    function startPetals() as Void {
        petalT0 = System.getTimer();
        if (animTimer == null) {
            animTimer = new Timer.Timer();
        }
        (animTimer as Timer.Timer).start(method(:animTick), 100, true);
    }

    function animTick() as Void {
        if (System.getTimer() - petalT0 > 4500) {
            petalT0 = 0;
            (animTimer as Timer.Timer).stop();
        }
        WatchUi.requestUpdate();
    }

    function lap() as Void {
        var info = Activity.getActivityInfo();
        var t = info != null && info.timerTime != null ? info.timerTime as Number : 0;
        var d = info != null && info.elapsedDistance != null ? info.elapsedDistance as Float : 0.0;
        nextStep(t, d);
        WatchUi.requestUpdate();
    }

    function pause() as Void {
        if (session != null && session.isRecording()) {
            session.stop();
        }
        paused = true;
    }

    function resume() as Void {
        if (session != null && !session.isRecording()) {
            session.start();
        }
        paused = false;
    }

    function stopAll() as Void {
        timer.stop();
        if (animTimer != null) {
            (animTimer as Timer.Timer).stop();
        }
        Position.enableLocationEvents(Position.LOCATION_DISABLE, method(:onPosition));
    }

    //! Watch came off mid-session (Idle): keep it if anything happened, timed up to the last heart beat.
    function autoSave() as Void {
        var s = summary();
        var d = s["distance_m"];
        stopAll();
        if (session != null) {
            if (session.isRecording()) {
                session.stop();
            }
            if (lastHrT < 60000 && !(d != null && (d as Float) >= 200.0)) {
                session.discard();
                return;
            }
            session.save();
        }
        if (lastHrT >= 0 && lastHrT / 1000 < (s["duration_s"] as Number)) {
            s["duration_s"] = lastHrT / 1000;
        }
        Outbox.add(s);
    }

    function summary() as Dictionary {
        var info = lastInfo != null ? lastInfo : Activity.getActivityInfo();
        var now = Time.now().value();
        var dur = info != null && info.timerTime != null ? (info.timerTime as Number) / 1000 : 0;
        var start = info != null && info.startTime != null ? (info.startTime as Time.Moment).value() : now - dur;
        var out = {
            "id" => "watch-" + start.toString(), "start" => start, "sport" => sport, "planned" => planned,
            "duration_s" => dur, "completed_steps" => idx,
            "completed_frac" => steps.size() > 0 ? (idx < steps.size() ? idx : steps.size()).toFloat() / steps.size() : 1.0,
            "in_range_pct" => withHr > 0 ? (inRange * 100) / withHr : null,
            "zone_s" => zoneSecs,
            "device" => System.getDeviceSettings().partNumber
        };
        if (info != null) {
            out["distance_m"] = info.elapsedDistance;
            out["avg_hr"] = info.averageHeartRate;
            out["max_hr"] = info.maxHeartRate;
            out["cadence"] = info.averageCadence;
            out["ascent"] = info.totalAscent;
            out["calories"] = info.calories;
        }
        return out;
    }

    var hudPage as Number = 0;

    function cyclePage(dir as Number) as Void {
        hudPage = (hudPage + dir + 3) % 3;
        WatchUi.requestUpdate();
    }

    function fmtStepSummary(st as Dictionary) as String {
        var n = st["n"] as String;
        if (st["r"] != null) {
            n += " " + st["r"];
        }
        var dt = st["dt"] as Number;
        var v = st["v"] as Number;
        if (dt == 0 && v > 0) {
            n += " " + Coach.fmtTime(v);
        } else if (dt == 1 && v > 0) {
            n += " " + (v / 1000.0).format("%.1f") + "k";
        }
        if (st["pf"] != null) {
            n += " @" + Coach.fmtPace(st["pf"] as Number);
        } else if (st["hl"] != null) {
            n += " " + st["hl"].toString() + "-" + st["hh"].toString();
        }
        return n;
    }

    function onUpdate(dc as Dc) as Void {
        var info = lastInfo;
        var s = cur();
        var t = info != null && info.timerTime != null ? info.timerTime as Number : 0;
        var d = info != null && info.elapsedDistance != null ? info.elapsedDistance as Float : 0.0;
        var inPlan = idx < steps.size();
        var left = Coach.fmtTime(t / 1000);
        var leftCap = "TIME";
        var frac = -1.0;
        if (inPlan) {
            var dt = s["dt"] as Number;
            var v = s["v"] as Number;
            if (dt == 0) {
                left = Coach.fmtTime(v - (t - stepStartMs) / 1000);
                leftCap = "LEFT";
                frac = v > 0 ? ((t - stepStartMs) / 1000.0) / v : 0.0;
            } else if (dt == 1) {
                var rem = v - (d - stepStartDist);
                left = (rem > 0 ? rem / 1000.0 : 0.0).format("%.2f");
                leftCap = "KM LEFT";
                frac = v > 0 ? (d - stepStartDist) / v : 0.0;
            }
        }
        var pace = "--";
        var pstat = 2;
        var pdelta = null;
        var spd = info != null ? info.currentSpeed : null;
        if (spd != null && (spd as Float) > 0.5) {
            var p = (1000.0 / (spd as Float)).toNumber();
            pace = Coach.fmtPace(p);
            if (s["pf"] != null) {
                var pf = s["pf"] as Number;
                var ps = s["ps"] as Number;
                pstat = p >= pf - 5 && p <= ps + 5 ? 0 : 1;
                pdelta = p < pf - 2 ? p - pf : p > ps + 2 ? p - ps : 0;
            }
        }
        var next = idx + 1 < steps.size() ? (steps[idx + 1] as Dictionary)["n"] as String : (inPlan ? "finish" : null);
        var upNext = [] as Array<String>;
        for (var u = idx + 1; u < steps.size() && upNext.size() < 2; u++) {
            upNext.add(fmtStepSummary(steps[u] as Dictionary));
        }
        var fuelRem = fuelEvery > 0 && nextFuelS > t / 1000 ? Coach.fmtTime(nextFuelS - t / 1000) : null;
        var m = {
            "page" => hudPage,
            "hr" => info != null ? info.currentHeartRate : null,
            "lo" => s["hl"], "hi" => s["hh"],
            "step" => inPlan ? (idx + 1).toString() + "/" + steps.size().toString() + " " + stepName() : "FREE RUN",
            "step2" => inPlan ? stepName() : "FREE RUN",
            "si" => inPlan ? s["i"] : 0,
            "frac" => frac,
            "pace" => pace, "pstat" => pstat, "pdelta" => pdelta,
            "ptarget" => s["pf"] != null ? Coach.fmtPace(s["pf"] as Number) + "-" + Coach.fmtPace(s["ps"] as Number) : "/KM",
            "left" => left, "leftCap" => leftCap,
            "tot" => Coach.fmtTime(t / 1000), "dist" => (d / 1000.0).format("%.2f") + "k",
            "next" => next, "upNext" => upNext,
            "cad" => info != null ? info.currentCadence : null,
            "inPct" => withHr > 0 ? (inRange * 100) / withHr : null,
            "fuelRem" => fuelRem,
            "home" => turn != null ? (turn as TurnHome).label() : null,
            "zoneSecs" => zoneSecs,
            "msg" => msg != null && System.getTimer() < msgUntil ? msg : null,
            "msgc" => msgColor,
            "paused" => paused,
            "tick" => System.getTimer() / 4000,
            "tlw" => weights, "tli" => ints, "idx" => idx,
            "prog" => progress(t, d),
            "petal" => petalT0 > 0 ? (System.getTimer() - petalT0) / 4500.0 : -1.0
        };
        RunHud.draw(dc, m);
    }
}

class WorkoutDelegate extends WatchUi.BehaviorDelegate {

    var view as WorkoutView;

    function initialize(v as WorkoutView) {
        BehaviorDelegate.initialize();
        view = v;
    }

    //! START/STOP: pause and show Resume / Save / Discard
    function onSelect() as Boolean {
        view.pause();
        var menu = new WatchUi.Menu2({ :title => "Paused" });
        menu.addItem(new WatchUi.MenuItem("Resume", null, :resume, null));
        menu.addItem(new WatchUi.MenuItem("Save", null, :save, null));
        menu.addItem(new WatchUi.MenuItem("Discard", null, :discard, null));
        WatchUi.pushView(menu, new PauseDelegate(view), WatchUi.SLIDE_UP);
        return true;
    }

    //! UP/DOWN: switch live HUD pages (Main HUD <-> Pacer & Mechanics <-> Live Zones & Up Next)
    function onPreviousPage() as Boolean {
        view.cyclePage(-1);
        return true;
    }

    function onNextPage() as Boolean {
        view.cyclePage(1);
        return true;
    }

    //! BACK/LAP: next step (never exits mid-workout)
    function onBack() as Boolean {
        view.lap();
        return true;
    }
}

class PauseDelegate extends WatchUi.Menu2InputDelegate {

    var view as WorkoutView;

    function initialize(v as WorkoutView) {
        Menu2InputDelegate.initialize();
        view = v;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        if (id == :resume) {
            view.resume();
            WatchUi.popView(WatchUi.SLIDE_DOWN);
        } else if (id == :save) {
            var summary = view.summary();
            view.stopAll();
            if (view.session != null) {
                view.session.save();
            }
            WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
            Finish.askEffort(summary);   // replaces the workout view
        } else if (id == :discard) {
            Idle.setRecorder(null);
            view.stopAll();
            if (view.session != null) {
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
