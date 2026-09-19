"""Android biometric authentication helper with PIN-safe fallback.

Uses the platform ``android.hardware.biometrics.BiometricPrompt`` on Android
API 28+ so it works with the standard python-for-android ``PythonActivity``
without requiring a FragmentActivity. Callers must always keep PIN fallback
available because biometric authentication can be unavailable, locked out or
cancelled by the user.
"""

_ACTIVE = []  # Keep Java callback proxies alive until authentication finishes.


def _android_api_level():
    try:
        from jnius import autoclass
        return int(autoclass("android.os.Build$VERSION").SDK_INT)
    except Exception:
        return 0


def availability():
    """Return ``(available: bool, message: str)`` for biometric authentication."""
    if _android_api_level() < 28:
        return False, "Biometric unlock requires Android 9 or newer."
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        KeyguardManager = autoclass("android.app.KeyguardManager")
        PackageManager = autoclass("android.content.pm.PackageManager")

        activity = PythonActivity.mActivity
        km = activity.getSystemService(Context.KEYGUARD_SERVICE)
        if km is None or not bool(km.isDeviceSecure()):
            return False, "Set up a secure screen lock and biometric in Android Settings first."

        pm = activity.getPackageManager()
        has_biometric = bool(
            pm.hasSystemFeature(PackageManager.FEATURE_FINGERPRINT)
            or pm.hasSystemFeature("android.hardware.biometrics.face")
            or pm.hasSystemFeature("android.hardware.biometrics.iris")
        )
        if not has_biometric:
            return False, "No biometric hardware is available on this device."
        return True, "Biometric authentication is available."
    except Exception as exc:
        return False, f"Biometric service unavailable: {exc}"


def authenticate(title, on_success, on_error=None, *, subtitle="Use fingerprint or face to unlock"):
    """Show the Android biometric prompt.

    Returns True when the prompt was started. ``on_error`` receives a readable
    string for cancellation/lockout/unavailability. PIN fallback should remain
    visible to the user regardless of this return value.
    """
    ok, message = availability()
    if not ok:
        if on_error:
            on_error(message)
        return False

    try:
        from jnius import autoclass, PythonJavaClass, java_method

        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        BiometricPromptBuilder = autoclass("android.hardware.biometrics.BiometricPrompt$Builder")
        CancellationSignal = autoclass("android.os.CancellationSignal")

        activity = PythonActivity.mActivity
        executor = activity.getMainExecutor()
        cancel_signal = CancellationSignal()

        holder = {"finished": False}

        def finish():
            if holder["finished"]:
                return False
            holder["finished"] = True
            for obj in list(holder.values()):
                try:
                    if obj in _ACTIVE:
                        _ACTIVE.remove(obj)
                except Exception:
                    pass
            return True

        class AuthCallback(PythonJavaClass):
            __javaclass__ = "android/hardware/biometrics/BiometricPrompt$AuthenticationCallback"
            __javacontext__ = "app"

            @java_method("(Landroid/hardware/biometrics/BiometricPrompt$AuthenticationResult;)V")
            def onAuthenticationSucceeded(self, result):
                if finish():
                    on_success()

            @java_method("()V")
            def onAuthenticationFailed(self):
                if on_error:
                    on_error("Biometric not recognized. Try again or use your PIN.")

            @java_method("(ILjava/lang/CharSequence;)V")
            def onAuthenticationError(self, code, errString):
                if finish() and on_error:
                    on_error(str(errString) if errString is not None else "Biometric authentication cancelled.")

            @java_method("(ILjava/lang/CharSequence;)V")
            def onAuthenticationHelp(self, helpCode, helpString):
                if on_error and helpString is not None:
                    on_error(str(helpString))

        class NegativeListener(PythonJavaClass):
            __javainterfaces__ = ["android/content/DialogInterface$OnClickListener"]
            __javacontext__ = "app"

            @java_method("(Landroid/content/DialogInterface;I)V")
            def onClick(self, dialog, which):
                try:
                    cancel_signal.cancel()
                except Exception:
                    pass
                if finish() and on_error:
                    on_error("Use your PIN to unlock.")

        callback = AuthCallback()
        negative = NegativeListener()
        holder.update({"callback": callback, "negative": negative, "cancel": cancel_signal})
        _ACTIVE.extend([callback, negative, cancel_signal])

        builder = BiometricPromptBuilder(activity)
        builder.setTitle(str(title or "Unlock"))
        builder.setSubtitle(str(subtitle or "Use biometric authentication"))
        builder.setNegativeButton("USE PIN", executor, negative)
        prompt = builder.build()
        holder["prompt"] = prompt
        _ACTIVE.append(prompt)
        prompt.authenticate(cancel_signal, executor, callback)
        return True
    except Exception as exc:
        if on_error:
            on_error(f"Biometric prompt could not start: {exc}")
        return False
