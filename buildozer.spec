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
# REQUIREMENTS
#
# IMPORTANT:
# Kivy 2.3.0 officially supports Python through 3.12.
# We explicitly pin BOTH target Python and hostpython to 3.12.11
# so current python-for-android does not silently select Python 3.14.
# ================================================================
requirements = python3==3.12.11,hostpython3==3.12.11,kivy==2.3.0,kivymd==1.2.0,pyjnius,numpy,pillow,opencv,camera4kivy,gestures4kivy,androidstorage4kivy


# ================================================================
# DISPLAY
# ================================================================
orientation = portrait
fullscreen = 0


# ================================================================
# ANDROID SDK / NDK
# ================================================================
android.api = 33
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24
android.archs = arm64-v8a


# ================================================================
# ANDROID PERMISSIONS
# ================================================================
android.permissions = CAMERA,INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO


# ================================================================
# STORAGE / ACTIVITY
# ================================================================
android.private_storage = True
android.entrypoint = org.kivy.android.PythonActivity
android.activity_class_name = org.kivy.android.PythonActivity


# ================================================================
# PYTHON-FOR-ANDROID
# ================================================================
p4a.bootstrap = sdl2
p4a.branch = master
p4a.hook = camerax_provider/gradle_options.py


# ================================================================
# ANDROID BUILD OPTIONS
# ================================================================
android.copy_libs = 1
android.accept_sdk_license = True
android.allow_backup = False
android.logcat_filters = *:S python:D


# ================================================================
# BUILDOZER
# ================================================================
[buildozer]
log_level = 2
warn_on_root = 0
