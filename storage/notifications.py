"""
Android notifications for explicit document save/export events.

Important behavior:
- No notification is emitted for Preview DONE, Crop, Rotate, Filter,
  reorder/delete, or other editing actions.
- A new document's explicit SAVE DOCUMENT action may notify.
- Updating/re-saving an existing document does not notify.
- A successful Export may notify because it creates a new output file.

This module uses Android framework APIs through PyJNIus, which is already in
this project. No notification package/dependency is added.

Android 13+ notification permission is requested only when a real Save/Export
needs a notification. Denial never blocks the underlying save/export.
"""

import os
from typing import Callable, Optional

from kivy.utils import platform


CHANNEL_ID = "document_saves"
CHANNEL_NAME = "Saved documents"
CHANNEL_DESCRIPTION = "Notifications when a document or export is newly saved"

POST_NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"


# Notification IDs are process-local and intentionally monotonic enough for
# multiple saves in one session without replacing an earlier notification.
_next_notification_id = 4100


def _allocate_notification_id() -> int:
    global _next_notification_id
    _next_notification_id += 1
    if _next_notification_id > 2_000_000_000:
        _next_notification_id = 4101
    return _next_notification_id


def _android_sdk_int() -> int:
    try:
        from jnius import autoclass
        VERSION = autoclass("android.os.Build$VERSION")
        return int(VERSION.SDK_INT)
    except Exception:
        return 0


def _has_notification_permission() -> bool:
    if platform != "android":
        return False

    # Android 12L and below do not require runtime POST_NOTIFICATIONS.
    if _android_sdk_int() < 33:
        return True

    try:
        from android.permissions import check_permission
        return bool(check_permission(POST_NOTIFICATIONS))
    except Exception:
        return False


def _request_notification_permission(
    callback: Callable[[bool], None],
) -> None:
    """Request Android 13+ permission without affecting save/export success."""
    if platform != "android":
        callback(False)
        return

    if _android_sdk_int() < 33:
        callback(True)
        return

    if _has_notification_permission():
        callback(True)
        return

    try:
        from android.permissions import request_permissions

        def _result(permissions, grants):
            granted = bool(grants) and all(bool(value) for value in grants)
            callback(granted)

        request_permissions(
            [POST_NOTIFICATIONS],
            _result,
        )
    except Exception:
        callback(False)


def _ensure_channel(context, notification_manager) -> None:
    if _android_sdk_int() < 26:
        return

    from jnius import autoclass

    NotificationChannel = autoclass("android.app.NotificationChannel")
    NotificationManager = autoclass("android.app.NotificationManager")

    channel = NotificationChannel(
        CHANNEL_ID,
        CHANNEL_NAME,
        NotificationManager.IMPORTANCE_DEFAULT,
    )
    channel.setDescription(CHANNEL_DESCRIPTION)
    notification_manager.createNotificationChannel(channel)


def _post_notification(title: str, text: str) -> bool:
    """Post one native Android notification. Safe no-op on non-Android."""
    if platform != "android":
        return False

    try:
        from jnius import autoclass

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        NotificationBuilder = autoclass("android.app.Notification$Builder")

        context = PythonActivity.mActivity
        manager = context.getSystemService(Context.NOTIFICATION_SERVICE)
        _ensure_channel(context, manager)

        if _android_sdk_int() >= 26:
            builder = NotificationBuilder(context, CHANNEL_ID)
        else:
            builder = NotificationBuilder(context)

        # Use the app's own icon resource. No PendingIntent is created here,
        # avoiding Android 12+ FLAG_IMMUTABLE/FLAG_MUTABLE issues entirely.
        app_icon = int(context.getApplicationInfo().icon)

        builder.setSmallIcon(app_icon)
        builder.setContentTitle(str(title))
        builder.setContentText(str(text))
        builder.setAutoCancel(True)

        manager.notify(
            _allocate_notification_id(),
            builder.build(),
        )
        return True

    except Exception:
        # Notification failure must never turn a successful save into an app
        # error/crash.
        return False


def notify_saved(
    title: str,
    text: str,
) -> None:
    """
    Notify after a genuine Save/Export event.

    Android 13+ permission is requested lazily here. The caller should invoke
    this only AFTER its actual save/export operation succeeds.
    """
    if platform != "android":
        return

    if _has_notification_permission():
        _post_notification(title, text)
        return

    def _after_permission(granted: bool):
        if granted:
            _post_notification(title, text)

    _request_notification_permission(
        _after_permission
    )


def notify_new_document_saved(document_name: str) -> None:
    name = (document_name or "Document").strip() or "Document"
    notify_saved(
        "Document saved",
        f'{name} was saved successfully.',
    )


def notify_export_saved(file_path: str) -> None:
    filename = os.path.basename(file_path or "") or "Export"
    notify_saved(
        "Export saved",
        f'{filename} was saved successfully.',
    )
