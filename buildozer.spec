[app]

# --------------------------------------------------
# APP INFORMATION
# --------------------------------------------------

title = Pycam

package.name = pycam
package.domain = com.jahid2177

version = 1.0.0


# --------------------------------------------------
# SOURCE
# --------------------------------------------------

source.dir = .

source.include_exts = py,kv,png,jpg,jpeg,webp,atlas,json,txt,ttf,otf,xml

source.exclude_dirs = .git,.github,.buildozer,bin,__pycache__,venv,.venv

source.exclude_patterns = *.pyc,*.pyo,*.log


# --------------------------------------------------
# PYTHON / KIVY REQUIREMENTS
# --------------------------------------------------

requirements = python3,kivy==2.3.0,kivymd==1.2.0,opencv,numpy,pillow,pyjnius,camera4kivy,androidstorage4kivy


# --------------------------------------------------
# SCREEN
# --------------------------------------------------

orientation = portrait

fullscreen = 0


# --------------------------------------------------
# ANDROID
# --------------------------------------------------

android.api = 33

android.minapi = 24

android.ndk = 28c

android.ndk_api = 24

android.archs = arm64-v8a


# --------------------------------------------------
# ANDROID PERMISSIONS
# --------------------------------------------------

android.permissions = CAMERA,INTERNET,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_IMAGES,READ_MEDIA_VIDEO


# --------------------------------------------------
# ANDROID STORAGE
# --------------------------------------------------

android.private_storage = True


# --------------------------------------------------
# ANDROID ACTIVITY
# --------------------------------------------------

android.entrypoint = org.kivy.android.PythonActivity

android.activity_class_name = org.kivy.android.PythonActivity


# --------------------------------------------------
# PYTHON-FOR-ANDROID
# --------------------------------------------------

p4a.bootstrap = sdl2

p4a.branch = master

p4a.hook = camerax_provider/gradle_options.py


# --------------------------------------------------
# ANDROID BUILD OPTIONS
# --------------------------------------------------

android.copy_libs = 1

android.accept_sdk_license = True


# --------------------------------------------------
# APP BACKUP
# --------------------------------------------------

android.allow_backup = False


# --------------------------------------------------
# LOGCAT / DEBUG
# --------------------------------------------------

android.logcat_filters = *:S python:D


# --------------------------------------------------
# IOS - NOT USED
# --------------------------------------------------

ios.kivy_ios_url = https://github.com/kivy/kivy-ios

ios.kivy_ios_branch = master


# --------------------------------------------------
# OSX - NOT USED
# --------------------------------------------------

osx.python_version = 3

osx.kivy_version = 2.3.0


# --------------------------------------------------
# BUILD
# --------------------------------------------------

[buildozer]

log_level = 2

warn_on_root = 0
