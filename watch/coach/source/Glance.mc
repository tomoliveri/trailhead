import Toybox.Application;
import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

(:glance)
class CoachGlance extends WatchUi.GlanceView {

    function initialize() {
        GlanceView.initialize();
    }

    function onUpdate(dc as Dc) as Void {
        var s = Application.Storage.getValue("sync");
        var w = dc.getWidth();
        var h = dc.getHeight();
        var top = s instanceof Dictionary && (s as Dictionary)["race"] instanceof String
            ? ((s as Dictionary)["race"] as String).toUpper() : "RACE";
        var rdyTxt = "";
        var rdyCol = 0xFF4F2E;
        var mid = "Open to sync";
        var low = "";
        var frac = 0.0;

        if (s instanceof Dictionary && Cfg.stale(s as Dictionary)) {
            rdyCol = 0xFBBF24;
            mid = "Plan out of date";
            low = "Synced " + Cfg.planDay(s as Dictionary) + " - open to sync";
        } else if (s instanceof Dictionary) {
            var cd = s["cd"] != null ? s["cd"] as Number : null;
            var tot = s["tot"] != null && (s["tot"] as Number) > 0 ? s["tot"] as Number : 158;
            if (cd != null) {
                top = top + "  " + cd.toString() + "d";
                frac = (tot - cd).toFloat() / tot;
            }
            if (s["rd"] instanceof Number) {
                var r = s["rd"] as Number;
                rdyCol = r >= 70 ? 0x4ADE80 : r >= 45 ? 0xFBBF24 : 0xFF4F2E;
                rdyTxt = "RDY " + r.toString();
            }
            var t = s["today"];
            var ts = s["tasks"];
            var nxt = null;
            if (ts instanceof Array) {
                for (var i = 0; i < (ts as Array).size(); i++) {
                    var tk = (ts as Array)[i] as Dictionary;
                    if (tk["d"] != true) {
                        nxt = tk;
                        break;
                    }
                }
            }
            if (nxt != null) {
                mid = "Next: " + nxt["t"];
                low = (nxt["at"] != null ? nxt["at"].toString() : "");
                if (t instanceof Dictionary && t["m"] != null && (t["m"] as Number) > 0) {
                    low += (low.length() > 0 ? " · " : "") + t["m"].toString() + "m";
                }
                if (t instanceof Dictionary && t["hr"] instanceof Array) {
                    var hr = t["hr"] as Array;
                    low += " · " + hr[0].toString() + "-" + hr[1].toString();
                }
            } else if (ts instanceof Array && (ts as Array).size() > 0) {
                rdyCol = 0x4ADE80;
                mid = "All done today";
                low = s["pred"] instanceof String ? "Est " + (s["pred"] as String) : "Recover well";
            } else if (t instanceof Dictionary) {
                mid = (s["done"] == true ? "Done: " : "") + t["t"];
                if (t["m"] != null && (t["m"] as Number) > 0) {
                    low = t["m"].toString() + " min";
                }
                if (t["hr"] instanceof Array) {
                    var hr2 = t["hr"] as Array;
                    low += "  HR " + hr2[0].toString() + "-" + hr2[1].toString();
                }
            }
        }

        // Left status accent bar
        dc.setColor(rdyCol, Graphics.COLOR_TRANSPARENT);
        dc.fillRoundedRectangle(0, 4, 4, h - 10, 2);

        // Rising sun dot + top countdown
        dc.setColor(0xFF4F2E, Graphics.COLOR_TRANSPARENT);
        dc.fillCircle(13, (h * 0.16).toNumber(), 4);
        dc.drawText(21, h * 0.04, Graphics.FONT_XTINY, top, Graphics.TEXT_JUSTIFY_LEFT);
        if (rdyTxt.length() > 0) {
            dc.setColor(rdyCol, Graphics.COLOR_TRANSPARENT);
            dc.drawText(w - 4, h * 0.04, Graphics.FONT_XTINY, rdyTxt, Graphics.TEXT_JUSTIFY_RIGHT);
        }

        // Middle session line
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(10, h * 0.34, Graphics.FONT_TINY, Txt.fit(dc, mid, Graphics.FONT_TINY, w - 14), Graphics.TEXT_JUSTIFY_LEFT);

        // Bottom metadata line
        dc.setColor(0x9A9AAA, Graphics.COLOR_TRANSPARENT);
        dc.drawText(10, h * 0.66, Graphics.FONT_XTINY, Txt.fit(dc, low, Graphics.FONT_XTINY, w - 14), Graphics.TEXT_JUSTIFY_LEFT);

        // Bottom journey progress bar
        if (frac > 0.0) {
            if (frac > 1.0) { frac = 1.0; }
            dc.setColor(0x22202E, Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(10, h - 3, w - 14, 2);
            dc.setColor(0xFF4F2E, Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(10, h - 3, ((w - 14) * frac).toNumber(), 2);
        }
    }
}
