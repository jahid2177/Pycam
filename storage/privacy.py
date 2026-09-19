"""Android privacy helpers.

`FLAG_SECURE` blocks screenshots/screen-recording previews while sensitive
content is visible. On non-Android platforms the helpers are safe no-ops.
"""
def set_secure_window(enabled: bool) -> bool:
    from kivy.utils import platform
    if platform != "android":
        return False
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
        activity = PythonActivity.mActivity
        window = activity.getWindow()
        if enabled:
            window.addFlags(LayoutParams.FLAG_SECURE)
        else:
            window.clearFlags(LayoutParams.FLAG_SECURE)
        return True
    except Exception:
        return False
