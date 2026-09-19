[app]

# ================================================================
# APP INFORMATION
# ================================================================
title = Pycam
package.name = pycam
package.domain = com.jahid2177
version = 1.1.0


# ================================================================
# SOURCE FILES
# ================================================================
source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,webp,atlas,json,txt,ttf,otf,afm,pfb,xml,traineddata
source.exclude_dirs = .git,.github,.buildozer,bin,__pycache__,venv,.venv,camerax_provider/.git,tests,build-debug,release,.pytest_cache
source.exclude_patterns = *.pyc,*.pyo,*.log,*.zip,*.apk,*.aab,*.sha256,*~


# ================================================================
# REQUIREMENTS
#
# IMPORTANT:
# Kivy 2.3.0 officially supports Python through 3.12.
# We pin BOTH target Python and hostpython to 3.11.5 and pair them
# with python-for-android v2024.01.21, whose Python recipe defaults to 3.11.5.
#
# ReportLab is intentionally NOT listed here. p4a v2024.01.21 has an old
# ReportLab recipe pinned to a 2016 Mercurial archive which can return HTTP
# 403 and is too old for our Python 3.11 target. GitHub Actions vendors the
# official pure-Python ReportLab 4.2.5 wheel into the project source instead.
# ================================================================
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,kivymd==1.2.0,pyjnius,numpy,pillow,opencv,camera4kivy,gestures4kivy,androidstorage4kivy,chardet==5.2.0,pypdf,qrcode,pyaes==1.6.1


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
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a


# ================================================================
# ANDROID PERMISSIONS
# ================================================================
android.permissions = CAMERA,INTERNET,(name=android.permission.READ_EXTERNAL_STORAGE;maxSdkVersion=32),READ_MEDIA_IMAGES,POST_NOTIFICATIONS,USE_BIOMETRIC


# ================================================================
# ML KIT OCR
# Required by ocr/mlkit_ocr.py for Extract Text / Photo Translation.
# ================================================================
android.gradle_dependencies = com.google.android.gms:play-services-mlkit-text-recognition:19.0.1,com.rmtheis:tess-two:9.1.0

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
p4a.branch = v2024.01.21
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
