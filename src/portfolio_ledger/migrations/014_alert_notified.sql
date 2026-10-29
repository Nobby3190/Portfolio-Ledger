-- 系統通知 (2026-10-26): the alerts already sent as a macOS notification, so a restart does not send them again.
CREATE TABLE alert_notified (
    key  TEXT PRIMARY KEY,
    date TEXT NOT NULL
);
