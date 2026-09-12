[app]

# ================================================================
# APP INFORMATION
# ================================================================

title = Pycam
package.name = pycam
package.domain = com.jahid2177

version = 1.0.0


# ================================================================
# SOURCE FILES
# ================================================================

source.dir = .

source.include_exts = py,kv,png,jpg,jpeg,webp,atlas,json,txt,ttf,otf,xml

source.exclude_dirs = .git,.github,.buildozer,bin,__pycache__,venv,.venv,camerax_provider/.git

source.exclude_patterns = *.pyc,*.pyo,*.log


# ================================================================
# PYTHON / KIVY REQUIREMENTS
#
# gestures4kivy is included because Camera4Kivy's Android example
# declares it together with camera4kivy.
# ================================================================

requirements = python3,kivy==2.3.0,kivymd==1.2.0,pyjnius,numpy,pillow,opencv,camera4kivy,gestures4kivy,androidstorage4kivy


# ================================================================
# DISPLAY
# ================================================================

orientation = portrait

fullscreen = 0


# ================================================================
# ANDROID SDK / NDK
#
# NDK r28c is the current minimum/recommended NDK in current p4a
# documentation and is supported by Buildozer on Ubuntu 24.04.
# ================================================================

android.api = 33

android.minapi = 24

android.ndk = 28c

android.ndk_api = 24

android.archs = arm64-v8a


# ================================================================
# ANDROID PERMISSIONS
#
# CAMERA       -> Camera4Kivy / CameraX
# INTERNET     -> network features
#
# READ_EXTERNAL_STORAGE / WRITE_EXTERNAL_STORAGE are retained for
# compatibility with older Android devices and your existing app.
# READ_MEDIA_* applies to Android 13+ media access.
# ================================================================

android.permissions = CAMERA,INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO


# ================================================================
# STORAGE
# ================================================================

android.private_storage = True


# ================================================================
# ANDROID ACTIVITY
# ================================================================

android.entrypoint = org.kivy.android.PythonActivity

android.activity_class_name = org.kivy.android.PythonActivity


# ================================================================
# PYTHON-FOR-ANDROID
#
# Keep master paired with Python 3.12 in GitHub Actions.
# Camera4Kivy on Android uses the CameraX provider Gradle hook.
# ================================================================

p4a.bootstrap = sdl2

p4a.branch = master

p4a.hook = camerax_provider/gradle_options.py


# ================================================================
# ANDROID BUILD OPTIONS
# ================================================================

android.copy_libs = 1

android.accept_sdk_license = True


# ================================================================
# BACKUP
# ================================================================

android.allow_backup = False


# ================================================================
# LOGCAT / DEBUG
# ================================================================

android.logcat_filters = *:S python:D


# ================================================================
# IOS - NOT USED
# ================================================================

ios.kivy_ios_url = https://github.com/kivy/kivy-ios

ios.kivy_ios_branch = master


# ================================================================
# OSX - NOT USED
# ================================================================

osx.python_version = 3

osx.kivy_version = 2.3.0


# ================================================================
# BUILDOZER
# ================================================================

[buildozer]

log_level = 2

warn_on_root = 0
