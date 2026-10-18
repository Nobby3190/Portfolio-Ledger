"""隱藏金額的解鎖: the system's own Touch ID / login-password prompt (LocalAuthentication), and a hook for
when the screen locks or the Mac sleeps, so the amounts are hidden again. See DESIGN.md「隱藏金額與解鎖」."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

REASON = "顯示帳本裡的金額"
TIMEOUT = 300  # seconds the prompt may stay open


class Cancelled(Exception):
    """The user closed the prompt; nothing to report."""


class UnlockError(Exception):
    pass


def authenticate(reason: str = REASON) -> None:
    """Blocks until the user passes Touch ID or types the login password; raises Cancelled or UnlockError.
    Called from pywebview's js_api thread, so waiting here doesn't freeze the window."""
    try:
        import LocalAuthentication as LA
    except ImportError:
        raise UnlockError("這台電腦不能用 Touch ID 或密碼驗證") from None
    ctx = LA.LAContext.alloc().init()
    policy = LA.LAPolicyDeviceOwnerAuthentication  # Touch ID first, the login password as fallback
    ok, err = ctx.canEvaluatePolicy_error_(policy, None)
    if not ok:
        raise UnlockError(f"這台 Mac 沒辦法驗證：{err.localizedDescription() if err else '未知原因'}")
    done = threading.Event()
    result: dict[str, object] = {}

    def reply(success: bool, error: object) -> None:
        result["ok"], result["error"] = success, error
        done.set()

    ctx.evaluatePolicy_localizedReason_reply_(policy, reason, reply)
    if not done.wait(TIMEOUT):
        ctx.invalidate()
        raise Cancelled
    if result["ok"]:
        return
    error = result["error"]
    code = error.code() if error is not None else None
    if code in (LA.LAErrorUserCancel, LA.LAErrorSystemCancel, LA.LAErrorAppCancel):
        raise Cancelled
    raise UnlockError("驗證沒有通過")


_observer = None  # kept alive for as long as the app runs


def watch_lock(on_lock: Callable[[], None]) -> None:
    """Calls on_lock when the screen locks, the displays sleep or the Mac goes to sleep. on_lock runs on the
    main (Cocoa) thread and must not block."""
    global _observer
    try:
        from AppKit import NSWorkspace, NSWorkspaceScreensDidSleepNotification, NSWorkspaceWillSleepNotification
        from Foundation import NSDistributedNotificationCenter, NSObject
    except ImportError:
        return

    class LockObserver(NSObject):
        def locked_(self, _note: object) -> None:
            try:
                on_lock()
            except Exception:
                log.exception("lock handler failed")

    _observer = LockObserver.alloc().init()
    NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
        _observer, "locked:", "com.apple.screenIsLocked", None
    )
    ws = NSWorkspace.sharedWorkspace().notificationCenter()
    for name in (NSWorkspaceWillSleepNotification, NSWorkspaceScreensDidSleepNotification):
        ws.addObserver_selector_name_object_(_observer, "locked:", name, None)
