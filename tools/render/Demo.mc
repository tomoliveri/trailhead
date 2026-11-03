import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Timer;
import Toybox.WatchUi;

//! Render build only: cycles through the real screens with a real plan so the simulator can be screenshotted.
//! 0-2 home pages, 3-5 workout HUD pages, 6 turn-for-home cue, 7 pairing.
class DemoView extends WatchUi.View {

    var shot as Number = 0;
    var home as HomeView;
    var timer as Timer.Timer;

    function initialize() {
        View.initialize();
        home = new HomeView();
        var start = Application.Properties.getValue("demoShot");
        shot = start instanceof Number ? start as Number : 0;
        timer = new Timer.Timer();
        timer.start(method(:next), 2500, true);
    }

    function next() as Void {
        shot = (shot + 1) % 8;
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Dc) as Void {
        if (shot <= 2) {
            Application.Storage.setValue("sync", DemoData.sync() as Application.PropertyValueType);
            home.page = shot;
            home.onUpdate(dc);
            return;
        }
        if (shot == 7) {
            Application.Storage.deleteValue("sync");
            home.onUpdate(dc);
            return;
        }
        RunHud.draw(dc, hud(shot == 4 ? 1 : shot == 5 ? 2 : 0, shot == 6));
    }

    function hud(page as Number, turn as Boolean) as Dictionary {
        var steps = (DemoData.sync()["today"] as Dictionary)["s"] as Array;
        var n = steps.size();
        var w = new [n];
        var ints = new [n];
        var idx = -1;
        for (var i = 0; i < n; i++) {
            var s = steps[i] as Dictionary;
            var dt = s["dt"] as Number;
            var v = s["v"] as Number;
            var sec = dt == 0 ? v.toFloat() : dt == 1 ? v / 1000.0 * (s["pf"] != null ? (s["pf"] as Number) : 330) : 600.0;
            w[i] = sec < 5.0 ? 5.0 : sec;
            ints[i] = s["i"];
            if (idx < 0 && (s["i"] as Number) == 0 && s["pf"] != null) {
                idx = i;
            }
        }
        if (idx < 0) {
            idx = n > 1 ? 1 : 0;
        }
        var st = steps[idx] as Dictionary;
        var hl = st["hl"] != null ? st["hl"] as Number : 161;
        var hh = st["hh"] != null ? st["hh"] as Number : 172;
        var pf = st["pf"] != null ? st["pf"] as Number : 290;
        var ps = st["ps"] != null ? st["ps"] as Number : 300;
        var up = [] as Array<String>;
        for (var u = idx + 1; u < n && up.size() < 2; u++) {
            up.add((steps[u] as Dictionary)["n"] as String);
        }
        var name = (st["n"] as String) + (st["r"] != null ? " " + (st["r"] as String) : "");
        return {
            "page" => page, "hr" => turn ? 148 : hl + 6, "lo" => turn ? 136 : hl, "hi" => turn ? 152 : hh,
            "step" => (idx + 1).toString() + "/" + n.toString() + " " + name, "step2" => name, "si" => 0,
            "frac" => 0.62, "pace" => Coach.fmtPace(turn ? 352 : (pf + ps) / 2), "pstat" => 0, "pdelta" => 0,
            "ptarget" => Coach.fmtPace(pf) + "-" + Coach.fmtPace(ps), "left" => "1:46", "leftCap" => "LEFT",
            "tot" => "31:12", "dist" => "6.04k", "next" => up.size() > 0 ? up[0] : "finish", "upNext" => up,
            "cad" => 178, "inPct" => 86, "fuelRem" => null, "zoneSecs" => [240, 610, 520, 410, 170],
            "msg" => turn ? "TURN HOME" : null, "msgc" => RunHud.OK, "paused" => false, "tick" => 4,
            "tlw" => w, "tli" => ints, "idx" => idx, "prog" => 0.48, "petal" => -1.0,
            "home" => "TURN IN 6:20"
        };
    }
}
