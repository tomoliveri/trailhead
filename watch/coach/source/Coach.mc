import Toybox.Activity;
import Toybox.Application;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.Sensor;
import Toybox.System;
import Toybox.Time;
import Toybox.Timer;
import Toybox.WatchUi;

module Coach {

    function sync() as Dictionary? {
        var s = Application.Storage.getValue("sync");
        return s instanceof Dictionary ? s as Dictionary : null;
    }

    function today() as Dictionary? {
        var s = sync();
        if (s == null || Cfg.stale(s)) {
            return null;
        }
        var t = s["today"];
        return t instanceof Dictionary ? t as Dictionary : null;
    }

    function tasks() as Array {
        var s = sync();
        return s != null && !Cfg.stale(s) && s["tasks"] instanceof Array ? s["tasks"] as Array : [] as Array;
    }

    function nextTask() as Dictionary? {
        var ts = tasks();
        for (var i = 0; i < ts.size(); i++) {
            var t = ts[i] as Dictionary;
            if (t["d"] != true) {
                return t;
            }
        }
        return null;
    }

    function startNext() as Void {
        var n = nextTask();
        if (n != null && n["p"].equals("sec")) {
            startStrength();
        } else {
            startPlanned();
        }
    }

    function startStrength() as Void {
        var t = today();
        if (t == null || !(t["x"] instanceof Array) || (t["x"] as Array).size() == 0) {
            WatchUi.showToast("No strength today", null);
            return;
        }
        if (t["xh"] instanceof Array && (t["xh"] as Array).size() > 0) {
            var menu = new WatchUi.Menu2({ :title => "Where today?" });
            menu.addItem(new WatchUi.MenuItem("Gym", null, :gym, null));
            menu.addItem(new WatchUi.MenuItem("At home", "KB, DBs, bar", :home, null));
            WatchUi.pushView(menu, new WhereDelegate(), WatchUi.SLIDE_UP);
            return;
        }
        startStrengthAt(false);
    }

    function startStrengthAt(home as Boolean) as Void {
        var t = today();
        if (t == null) {
            return;
        }
        var title = t["sec"] instanceof String ? t["sec"] as String : "Strength";
        var view = new StrengthView(home ? title + " (home)" : title, (home ? t["xh"] : t["x"]) as Array,
                                    t["sk"] instanceof String ? t["sk"] as String : null);
        WatchUi.pushView(view, new StrengthDelegate(view), WatchUi.SLIDE_UP);
    }

    function startPlanned() as Void {
        var t = today();
        if (t == null || t["k"].equals("rest") || !(t["s"] instanceof Array) || (t["s"] as Array).size() == 0) {
            startFree("run");
            return;
        }
        var sp = t["sp"] instanceof String ? t["sp"] as String : "run";
        var fu = t["fu"];
        var fuel = null;
        if (fu instanceof Array) {
            fuel = fu as Array;
        }
        var mc = t["mc"] instanceof Array ? t["mc"] as Array : null;
        var view = new WorkoutView(t["t"] as String, sp, t["s"] as Array, t["k"] as String, fuel, mc);
        if (t["th"] instanceof Number) {
            view.enableTurnHome(t["th"] as Number);
        }
        WatchUi.pushView(view, new WorkoutDelegate(view), WatchUi.SLIDE_UP);
    }

    function startFree(sport as String) as Void {
        var name = sport.equals("bike") ? "Bike" : sport.equals("walk") ? "Walk" : "Run";
        var steps = [{ "n" => name, "i" => 0, "dt" => 2, "v" => 0 }] as Array;
        var view = new WorkoutView(name, sport, steps, null, null, null);
        WatchUi.pushView(view, new WorkoutDelegate(view), WatchUi.SLIDE_UP);
    }

    function logRestDay() as Void {
        var now = Time.now().value();
        Outbox.add({
            "id" => "watch-rest-" + (now / 86400).toString(),
            "start" => now,
            "sport" => "rest",
            "duration_s" => 0,
            "device" => System.getDeviceSettings().partNumber
        });
        Outbox.flush();
        if (WatchUi has :showToast) {
            WatchUi.showToast("Rest day logged", null);
        }
    }

    //! Pull the latest plan in the foreground (when the app is open).
    function refresh() as Void {
        Communications.makeWebRequest(Cfg.url("/api/device/sync"), null, Cfg.getOptions(), new Method(Coach, :onRefresh));
    }

    var _manual as Boolean = false;

    function syncNow() as Void {
        _manual = true;
        refresh();
    }

    function onRefresh(code as Number, data as Dictionary or String or Null) as Void {
        if (_manual && (WatchUi has :showToast)) {
            // negative codes: Bluetooth / Garmin Connect problem on the phone side
            WatchUi.showToast(code == 200 ? "Plan synced" : code < 0 ? "No phone link (" + code.toString() + ")" : "Sync failed (" + code.toString() + ")", null);
        }
        _manual = false;
        if (code == 200 && data instanceof Dictionary) {
            data.remove("n");
            Application.Storage.setValue("sync", data as Application.PropertyValueType);
            WatchUi.requestUpdate();
        }
        Outbox.flush();
    }

    function fmtTime(sec as Number) as String {
        if (sec < 0) {
            sec = 0;
        }
        var h = sec / 3600;
        var m = (sec % 3600) / 60;
        var s = sec % 60;
        return h > 0 ? h.format("%d") + ":" + m.format("%02d") + ":" + s.format("%02d") : m.format("%d") + ":" + s.format("%02d");
    }

    function fmtPace(secPerKm as Number) as String {
        return (secPerKm / 60).format("%d") + ":" + (secPerKm % 60).format("%02d");
    }
}

//! Finished activities wait here until the phone connection is available.
module Outbox {
    var _busy as Boolean = false;
    var _cb as Method? = null;
    var _lastCheer as String = "Saved";

    //! Queue a finished session. A later copy of the same session (e.g. with the effort answers) replaces a
    //! queued one, unless that one is being sent right now (then both go; the server merges them).
    function add(summary as Dictionary) as Void {
        var box = Application.Storage.getValue("outbox");
        var arr = box instanceof Array ? box as Array : [] as Array;
        var replaced = false;
        for (var i = _busy ? 1 : 0; i < arr.size(); i++) {
            var e = arr[i];
            if (e instanceof Dictionary && e["id"] != null && e["id"].equals(summary["id"])) {
                arr[i] = summary;
                replaced = true;
            }
        }
        if (!replaced) {
            arr.add(summary);
        }
        while (arr.size() > 10) {
            arr = arr.slice(1, null);
        }
        Application.Storage.setValue("outbox", arr as Application.PropertyValueType);
    }

    function pending() as Number {
        var box = Application.Storage.getValue("outbox");
        return box instanceof Array ? (box as Array).size() : 0;
    }

    function flush() as Void {
        flushThen(null);
    }

    function flushThen(cb as Method?) as Void {
        var box = Application.Storage.getValue("outbox");
        if (_busy) {
            if (cb != null) {
                _cb = cb;   // answered when the upload in flight (and the rest of the queue) is done
            }
            return;
        }
        if (!(box instanceof Array) || (box as Array).size() == 0) {
            if (cb != null) {
                cb.invoke(_lastCheer);   // nothing waiting: everything already reached the site
            }
            return;
        }
        _busy = true;
        _cb = cb;
        Communications.makeWebRequest(Cfg.url("/api/device/activity"), (box as Array)[0] as Dictionary, Cfg.postOptions(),
                                      new Method(Outbox, :onSent));
    }

    function onSent(code as Number, data as Dictionary or String or Null) as Void {
        _busy = false;
        var cheer = null;
        if (code == 200 || code == 201 || code == 400) {
            // 400 = rejected permanently (bad data); drop it so the queue can't jam
            var box = Application.Storage.getValue("outbox") as Array;
            Application.Storage.setValue("outbox", box.slice(1, null) as Application.PropertyValueType);
            if (data instanceof Dictionary && data["cheer"] instanceof String) {
                cheer = data["cheer"];
                _lastCheer = cheer as String;
            }
            if (pending() > 0) {
                flushThen(_cb);
                return;
            }
        }
        var cb = _cb;
        _cb = null;
        if (cb != null) {
            cb.invoke(code == 200 || code == 201 ? (cheer == null ? "Saved to " + Cfg.brand() : cheer) : null);
        }
    }
}

class WhereDelegate extends WatchUi.Menu2InputDelegate {

    function initialize() {
        Menu2InputDelegate.initialize();
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        WatchUi.popView(WatchUi.SLIDE_IMMEDIATE);
        Coach.startStrengthAt(item.getId() == :home);
    }
}

//! Watch taken off: no heart rate for 30 minutes on any screen -> save whatever is recording and close the app,
//! so the screen doesn't stay on forever.
module Idle {
    const LIMIT_S = 30 * 60;
    var _timer as Timer.Timer? = null;
    var _lastHr as Number = 0;
    var _saver as Method? = null;   // autoSave of the WorkoutView / StrengthView recording now

    function start() as Void {
        _lastHr = Time.now().value();
        Sensor.setEnabledSensors([Sensor.SENSOR_HEARTRATE] as Array<Sensor.SensorType>);
        if (_timer == null) {
            _timer = new Timer.Timer();
            (_timer as Timer.Timer).start(new Method(Idle, :check), 60000, true);
        }
    }

    function heartRate() as Number? {
        var si = Sensor.getInfo();
        if (si != null && si.heartRate != null) {
            return si.heartRate as Number;
        }
        var ai = Activity.getActivityInfo();
        return ai != null ? ai.currentHeartRate : null;
    }

    //! Seconds since the last heart-rate reading.
    function quietFor() as Number {
        if (heartRate() != null) {
            _lastHr = Time.now().value();
        }
        return Time.now().value() - _lastHr;
    }

    function setRecorder(m as Method?) as Void {
        _saver = m;
    }

    function check() as Void {
        if (quietFor() < LIMIT_S) {
            return;
        }
        var m = _saver;
        _saver = null;
        if (m != null) {
            m.invoke();
        }
        Outbox.flush();
        System.exit();
    }
}
