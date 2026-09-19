"""Small Android intent helpers for QR/barcode result actions."""


def open_uri(uri: str):
    from kivy.utils import platform
    if platform != "android":
        raise RuntimeError("This action is only available on Android.")
    value = str(uri or "").strip()
    if not value:
        raise ValueError("No URI to open.")
    from jnius import autoclass
    from storage.android_compat import start_activity_checked

    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    intent = Intent(Intent.ACTION_VIEW, Uri.parse(value))
    return start_activity_checked(
        intent,
        "No installed Android app can open this link or action.",
    )


def action_uri_from_qr(value: str):
    raw = str(value or "").strip()
    upper = raw.upper()
    if raw.startswith(("http://", "https://")):
        return raw
    if upper.startswith("TEL:"):
        return raw
    if upper.startswith("MAILTO:"):
        return raw
    if upper.startswith("SMS:") or upper.startswith("SMSTO:"):
        if upper.startswith("SMSTO:"):
            body = raw[6:]
            number = body.split(":", 1)[0]
            message = body.split(":", 1)[1] if ":" in body else ""
            from urllib.parse import quote
            return f"sms:{number}?body={quote(message)}" if message else f"sms:{number}"
        return raw
    return None


def share_text(subject: str, text: str):
    """Open Android's native share sheet with plain text."""
    from kivy.utils import platform
    if platform != "android":
        raise RuntimeError("Sharing is only available on Android.")
    from jnius import autoclass
    from storage.android_compat import start_activity_checked

    Intent = autoclass("android.content.Intent")
    intent = Intent(Intent.ACTION_SEND)
    intent.setType("text/plain")
    intent.putExtra(Intent.EXTRA_SUBJECT, str(subject or "Pycam diagnostics"))
    intent.putExtra(Intent.EXTRA_TEXT, str(text or ""))
    chooser = Intent.createChooser(intent, str(subject or "Share"))
    return start_activity_checked(
        chooser,
        "No installed Android app is available for sharing.",
    )
