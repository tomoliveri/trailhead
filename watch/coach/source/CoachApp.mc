import Toybox.Application;
import Toybox.Background;
import Toybox.Lang;
import Toybox.Math;
import Toybox.Notifications;
import Toybox.System;
import Toybox.Time;
import Toybox.WatchUi;

//! Trailhead Coach: today's session from your Trailhead server, guided workout with
//! HR-range alerts, and upload of the finished activity back to the site.
(:background, :glance)
class CoachApp extends Application.AppBase {

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
        // Poll the site every 15 min (10:00-22:00): refresh the plan and show any due notification.
        if (Background.getTemporalEventRegisteredTime() == null) {
            Background.registerForTemporalEvent(new Time.Duration(15 * 60));
        }
    }

    function getServiceDelegate() as [System.ServiceDelegate] {
        return [new SyncDelegate()];
    }

    function onBackgroundData(data as Application.PersistableType) as Void {
        if (data != null) {
            Application.Storage.setValue("sync", data);
        }
        WatchUi.requestUpdate();
    }

    (:typecheck(disableBackgroundCheck))
    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        ensurePairCode();
        if (Toybox has :Notifications) {
            Notifications.registerForNotificationMessages(method(:onNotification));
        }
        Idle.start();
        var view = new HomeView();
        return [view, new HomeDelegate(view)];
    }

    //! Pairing builds: make this watch's 8-character code once (foreground only; background just reads it).
    (:typecheck(disableBackgroundCheck))
    function ensurePairCode() as Void {
        if (!Cfg.pairing() || Cfg.token().length() == 8) {
            return;
        }
        var chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
        Math.srand(Time.now().value() + System.getTimer());
        var code = "";
        for (var i = 0; i < 8; i++) {
            var k = (Math.rand() % 32).abs();
            code += chars.substring(k, k + 1);
        }
        Application.Properties.setValue("token", code);
    }

    (:typecheck(disableBackgroundCheck))
    function onNotification(message as Notifications.NotificationMessage) as Void {
        if (message.type == Notifications.NOTIFICATION_MESSAGE_TYPE_SELECTED && message.action == 1) {
            Coach.startPlanned();
        }
    }

    (:glance)
    function getGlanceView() as [WatchUi.GlanceView] or [WatchUi.GlanceView, WatchUi.GlanceViewDelegate] or Null {
        return [new CoachGlance()];
    }
}
