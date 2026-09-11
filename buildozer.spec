[app]
title = Document Scanner
package.name = camscannerpython
package.domain = org.example

source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt,ttf,traineddata

version = 0.1.0

# p4a recipe names (NOT pip package names - e.g. "opencv" not
# "opencv-python-headless"). Keep this in sync with requirements.txt
# when adding new dependencies.
requirements = python3,kivy==2.3.0,kivymd==1.2.0,opencv,numpy,pillow,reportlab,pyjnius,camera4kivy,androidstorage4kivy

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/assets/icons/app_icon.png

# --- Android specifics ---------------------------------------------------

android.permissions = CAMERA
# READ_MEDIA_IMAGES/VIDEO deliberately NOT requested: nothing in this
# app reads from the shared media library (no gallery picker) - every
# image the app touches lives in its own app-private storage
# (StorageManager) or is handed to androidstorage4kivy for sharing,
# neither of which needs those permissions. Requesting permissions the
# app doesn't use is worth avoiding on its own merits, not just Play
# Store review.

# camera4kivy's camerax_provider imports Android packages that currently
# constrain this to API 33 - do not bump without checking the provider's
# compatibility notes first.
android.api = 33
android.minapi = 24
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True

# Required because every third-party Android dependency this app uses
# (CameraX, ML Kit, Tesseract4Android, androidstorage4kivy) is built on
# AndroidX - without this, expect "duplicate class" / "class not found"
# errors at build or runtime.
android.enable_androidx = True

# Required by camera4kivy: injects the CameraX gradle dependencies and
# native provider sources. Run this once before building:
#   git clone https://github.com/Android-for-Python/camerax_provider.git
#   rm -rf camerax_provider/.git
# so that ./camerax_provider/ sits next to this buildozer.spec.
p4a.hook = camerax_provider/gradle_options.py

# OCR (step 12-13): ML Kit for English (Latin script), Tesseract4Android
# for Bengali (ML Kit has no Bengali support at all - see README).
# Tesseract4Android is only on JitPack, not Google's/Maven Central's
# default repos, so it needs its own repository line.
android.gradle_repositories = https://jitpack.io
android.gradle_dependencies = com.google.android.gms:play-services-mlkit-text-recognition:19.0.1, cz.adaptech.tesseract4android:tesseract4android:4.9.0

# python-for-android sometimes needs this bumped when opencv/pyjnius
# recipes lag behind the latest p4a release - pin explicitly if a CI
# build breaks after a p4a update.
# p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 1
