import Toybox.Application;
import Toybox.Background;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.Notifications;
import Toybox.System;
import Toybox.Time;
import Toybox.Time.Gregorian;

(:background, :glance)
module Cfg {
    function url(path as String) as String {
        var b = Application.Properties.getValue("baseUrl");
        if (!(b instanceof String) || (b as String).length() < 8) {
            b = "https://example.org";
        }
        return (b as String) + path;
    }

    //! True when the cached plan isn't for today's date (the phone link has been down since).
    function stale(s as Dictionary?) as Boolean {
        if (s == null || !(s["today"] instanceof Dictionary)) {
            return false;
        }
        var d = (s["today"] as Dictionary)["date"];
        var g = Gregorian.info(Time.now(), Time.FORMAT_SHORT);
        var today = (g.year as Number).format("%04d") + "-" + (g.month as Number).format("%02d") + "-" + (g.day as Number).format("%02d");
        return !(d instanceof String) || !(d as String).equals(today);
    }

    //! "12/10" from the cached plan's date.
    function planDay(s as Dictionary) as String {
        var d = (s["today"] as Dictionary)["date"];
        if (d instanceof String && (d as String).length() == 10) {
            return (d as String).substring(8, 10) + "/" + (d as String).substring(5, 7);
        }
        return "?";
    }

    function token() as String {
        var t = Application.Properties.getValue("token");
        return t instanceof String ? t as String : "";
    }

    //! Builds that pair with a plan (Trailhead) instead of carrying a baked-in token.
    function pairing() as Boolean {
        return Application.Properties.getValue("pair") == true;
    }

    function brand() as String {
        var b = Application.Properties.getValue("brand");
        return b instanceof String && (b as String).length() > 0 ? b as String : "Trailhead";
    }

    //! The server's host name, for the pairing screen ("garmin.example.org").
    function host() as String {
        var u = url("");
        var i = u.find("://");
        return i != null ? u.substring(i + 3, u.length()) : u;
    }

    //! "ABCD-1234" for the pairing screen.
    function pairCode() as String {
        var t = token();
        return t.length() == 8 ? t.substring(0, 4) + "-" + t.substring(4, 8) : t;
    }

    function getOptions() as Dictionary {
        return {
            :method => Communications.HTTP_REQUEST_METHOD_GET,
            :headers => { "Authorization" => "Bearer " + token() },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };
    }

    function postOptions() as Dictionary {
        return {
            :method => Communications.HTTP_REQUEST_METHOD_POST,
            :headers => { "Authorization" => "Bearer " + token(), "Content-Type" => Communications.REQUEST_CONTENT_TYPE_JSON },
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };
    }
}

//! Background: fetch the plan; show the notification the server says is due now.
(:background)
class SyncDelegate extends System.ServiceDelegate {

    function initialize() {
        ServiceDelegate.initialize();
    }

    function onTemporalEvent() as Void {
        var hour = System.getClockTime().hour;
        if (hour < 10 || hour >= 22) {
            Background.exit(null);
            return;
        }
        Communications.makeWebRequest(Cfg.url("/api/device/sync"), null, Cfg.getOptions(), method(:onSync));
    }

    function onSync(code as Number, data as Dictionary or String or Null) as Void {
        if (code == 200 && data instanceof Dictionary) {
            var n = data["n"];
            if (n instanceof Dictionary && (Toybox has :Notifications)) {
                var opts = { :body => n["body"] as String, :data => 1, :dismissPrevious => true };
                if (n["act"] == 1) {
                    opts[:actions] = [
                        { :label => "Start", :data => 1 },
                        { :label => "Later", :data => 0 }
                    ] as Array<Notifications.Action>;
                }
                Notifications.showNotification(n["title"] as String, n["sub"] as String, opts);
            }
            data.remove("n");
            try {
                Background.exit(data as Application.PropertyValueType);
            } catch (e instanceof Background.ExitDataSizeLimitException) {
                Background.exit(null);
            }
            return;
        }
        Background.exit(null);
    }
}
