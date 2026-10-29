"""macOS 系統通知 (DESIGN.md「系統通知」). In the built .app: UserNotifications, which asks the user
for permission once. Run from source the process is not an app bundle and UserNotifications refuses
it, so `display notification` through osascript stands in. Failures are logged, never raised."""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

log = logging.getLogger(__name__)

_center = None
_delegate = None  # kept alive: the center holds it weakly
_lock = threading.Lock()


def _bundle_center():
    """The notification center, set up on first use; None when not running as the .app."""
    global _center, _delegate
    with _lock:
        if _center is not None:
            return _center
        if not getattr(sys, "frozen", False):
            return None
        import objc
        import UserNotifications as UN
        from Foundation import NSObject

        class Delegate(NSObject, protocols=[objc.protocolNamed("UNUserNotificationCenterDelegate")]):
            # Shown as a banner even while the window is in front (macOS hides them otherwise).
            def userNotificationCenter_willPresentNotification_withCompletionHandler_(self, center, note, done):
                done(UN.UNNotificationPresentationOptionBanner | UN.UNNotificationPresentationOptionList)

        center = UN.UNUserNotificationCenter.currentNotificationCenter()
        _delegate = Delegate.alloc().init()
        center.setDelegate_(_delegate)

        def answered(granted: bool, error: object) -> None:
            if not granted:
                log.info("notifications not allowed: %s", error)

        center.requestAuthorizationWithOptions_completionHandler_(
            UN.UNAuthorizationOptionAlert | UN.UNAuthorizationOptionSound, answered
        )
        _center = center
        return center


def send(title: str, body: str) -> None:
    try:
        center = _bundle_center()
        if center is None:
            script = f"display notification {_quote(body)} with title {_quote(title)}"
            subprocess.run(["osascript", "-e", script], check=False, capture_output=True, timeout=10)
            return
        import UserNotifications as UN

        content = UN.UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(body)
        content.setSound_(UN.UNNotificationSound.defaultSound())
        request = UN.UNNotificationRequest.requestWithIdentifier_content_trigger_(f"alerts-{id(content)}", content, None)

        def added(error: object) -> None:
            if error is not None:
                log.warning("notification failed: %s", error)

        center.addNotificationRequest_withCompletionHandler_(request, added)
    except Exception:
        log.exception("notification failed")


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
