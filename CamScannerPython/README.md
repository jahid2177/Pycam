# CamScannerPython

A document scanner Android app built with Python (Kivy/KivyMD + OpenCV)
for image processing and a thin Android-native bridge (CameraX, ML Kit)
for camera and OCR. See the original build spec for the full feature
list and step-by-step plan.

Original CamScanner branding, logo, and source code are **not** used
anywhere in this project — UI, icons, and implementation are original.

## Status: Step 1-16 complete

- [x] **Step 1 — Project architecture**: folder layout, `main.py` app
      shell, `DocumentDatabase` (SQLite), `StorageManager` (Android vs.
      desktop path resolution)
- [x] **Step 2 — Home screen (KivyMD UI)**: recent documents list,
      empty state, search, rename/delete/share menu, navigation to
      Scanner / Documents / Settings
- [x] **Step 3 — Camera integration**: live preview + capture, built on
      [Camera4Kivy](https://github.com/Android-for-Python/Camera4Kivy)
      (a Kivy↔CameraX bridge - see note below), CAMERA permission
      request flow, capture → session pages → review screen
      (retake / add page / done)
- [x] **Step 4 — OpenCV real-time edge detection**: `scanner/detector.py`
      finds the document's 4-corner outline in each preview frame
      (Canny edges → contours → largest convex quadrilateral); the
      camera screen draws a live green outline over the detected
      document and shows a "Document detected" hint. Detector logic is
      pure OpenCV/numpy (no Kivy import), independently tested against
      synthetic images - see `## Testing the detector` below.
- [x] **Step 5 — Auto capture**: `scanner/auto_capture.py` tracks how
      long a detected document has held roughly still (centroid
      movement below a threshold that scales with frame size) and
      fires the shutter automatically after ~0.9s of stability; a
      progress ring fills around the shutter button as it counts down.
      A timer icon in the top bar toggles auto-capture off in favor of
      manual-only. Pure logic, no Kivy/camera dependency - unit tested
      against steady, moving, interrupted, and jittery sequences.
- [x] **Step 6 — Perspective correction**: `image_processing/perspective.py`
      re-detects the document on the full-resolution capture (reusing
      `DocumentDetector`) and warps it into a flat, cropped rectangle
      via `cv2.getPerspectiveTransform`/`warpPerspective`. Runs on a
      background thread right after capture so the UI never stutters;
      falls back to the raw, uncorrected photo if detection misses on
      that particular shot rather than losing the page. Verified
      against a synthetic skewed photo - the output was a clean,
      edge-to-edge rectangle at the expected size.
- [x] **Step 7 — Manual crop editor**: `ui/crop.py` shows the *raw*
      capture (not the already-corrected one) with 4 draggable corner
      handles, seeded from auto-detection or a centered fallback rect.
      "Apply crop" runs the same `four_point_transform` step 6 uses,
      just with the user's corners; a reset button re-runs
      auto-detection. All screen↔image coordinate math (accounting for
      `keep_ratio` letterboxing and the image/widget y-axis flip) lives
      in `ui/crop_geometry.py`, has zero Kivy dependency, and is
      unit-tested: letterboxing on both axes, exact corner mapping,
      20-point round-trip, and edge-clamping when a drag goes past the
      image bounds.
- [x] **Step 8 — Image enhancement**: `image_processing/filters.py`
      adds Auto Enhance (illumination-flattening via morphological
      background estimation + CLAHE + a light sharpen), Grayscale,
      B&W (adaptive threshold - the classic clean-text-scan look), and
      Color Boost (saturation + local contrast for photos/color forms).
      All 5 filters verified numerically against a synthetic page with
      an uneven-lighting gradient (grayscale channel equality, B&W
      binarization, saturation increase, and - after an initial
      Gaussian-blur version produced visible halos around text and was
      replaced - confirmed illumination-flattening with no halo
      artifact on text). Wired into the preview screen as a chip row;
      each filter's output is cached per page and applied on a
      background thread so switching filters doesn't reprocess or
      block the UI.
- [x] **Step 9 — Multi-page scanner**: `ui/editor.py` turns the Editor
      screen into a real page manager - thumbnail strip with move
      left/right (reorder), rotate (in-place, verified against a real
      image that dimensions actually swap and content lands in the
      right place, not just that it runs), delete (with confirmation),
      and an "Add page" card that returns to the scanner without
      resetting the session. "Save Document" writes the finished pages
      into `DocumentDatabase`, which gained a `pages_json` column this
      step (with an in-place `ALTER TABLE` migration verified against a
      real SQLite file, including backward-compat for a doc saved
      before the column existed) so it can hold an ordered, multi-page
      document rather than just one image. Saved documents now
      actually appear in Home's recent list - the capture→save loop is
      complete, though re-opening a saved document for further editing
      is deliberately left to step 10 (see `HomeScreen.open_document`).
- [x] **Step 10 — Documents library + reopening a saved document**:
      `ui/documents.py` is the full searchable/sortable list of every
      saved document (Home still only shows a short recent list), with
      an explicit "Select" mode for bulk delete (chosen over a
      long-press gesture, which isn't practical to get right without
      real-device touch testing). Reopening a document (from either
      Home or Documents) now actually works - it loads that document's
      pages back into the active session and "Save" updates the
      existing record instead of creating a duplicate. Two real gaps
      got fixed along the way rather than carried forward:
      - `DocumentListItem.on_release_row` existed since step 2 but was
        never wired to an actual touch handler, so tapping a document
        row silently did nothing; fixed with a proper `on_touch_up`
        override that still lets the row's own overflow-menu button
        handle its own taps first.
      - Opening a saved document while a scan is already in progress
        would have silently discarded the unsaved pages; both entry
        points now confirm before discarding.
      Sort logic (newest/oldest/name/page-count) is unit tested against
      a small fixed dataset.
- [x] **Step 11 — PDF/JPG/PNG export**: `pdf/export.py` writes a
      multi-page PDF via reportlab (each page sized to *its own* image
      aspect ratio rather than forced onto a fixed A4/Letter box, so a
      portrait ID card and a landscape receipt in one document don't
      distort), or JPG/PNG (a single file for a one-page document, a
      zip of numbered images for multi-page). Verified against real
      files, not just "it ran": read the exported PDF back with an
      actual PDF library and confirmed 3 pages with the exact expected
      aspect ratios; confirmed the JPG/PNG outputs are genuinely that
      format via PIL; confirmed the zip's contents and that no leftover
      temp files were left behind. Wired into an "Export" action
      (replacing the old placeholder "Share" that didn't really share
      anything) on both Home and Documents - picks a format, exports on
      a background thread, and reports the saved file's path. Actual
      OS share-sheet handoff to other apps is step 14's job; this step
      only produces the file.
- [x] **Step 12-13 — OCR (English + Bengali)**: **important correction
      to the original plan, found before building anything** - Google's
      on-device ML Kit Text Recognition only supports 5 scripts (Latin,
      Chinese, Devanagari, Japanese, Korean); Bengali isn't one of them,
      confirmed against Google's own docs. So this is two separate
      native bridges rather than one:
      - `ocr/mlkit_ocr.py` - English via ML Kit. Rather than
        implementing ML Kit's OnSuccessListener/OnFailureListener as a
        Java interface in Python (the "normal" PyJNIus pattern, but
        also the most failure-prone to get right blind), it blocks the
        already-background OCR thread on `Tasks.await()`, turning the
        async call into an ordinary function call. Caught a real bug
        while writing this: `Tasks.await(...)` is a `SyntaxError` in
        Python 3.7+ even though `await` is a genuine Java method name
        here, not Python's async/await - fixed via
        `getattr(Tasks, "await")(...)`, the standard PyJNIus workaround
        for a Java method name that collides with a Python keyword.
      - `ocr/tesseract_ocr.py` - Bengali via Tesseract4Android. Needs
        `assets/tessdata/ben.traineddata`, which is **not included** -
        it's a multi-megabyte binary this environment has no network
        access to fetch, and a fake placeholder would just fail
        confusingly on-device instead of honestly; see
        `assets/tessdata/README_DOWNLOAD_BENGALI_DATA.txt` for the
        exact download command. No asset-copying JNI code was needed
        to reach it either: Tesseract needs a real filesystem path
        containing a `tessdata` folder, and python-for-android already
        extracts this project's `assets/` onto the device's real
        filesystem at first launch (the same mechanism `main.py`
        already relies on for its icon path) - so
        `assets/tessdata/ben.traineddata` already sits exactly where
        Tesseract expects it once that file is added.
      - `ocr/ocr_manager.py` - dispatches by language and joins
        per-page results; one page's OCR failure doesn't lose the
        whole document. Deliberately built with an injectable backend
        dict specifically so this dispatch/joining logic is unit
        testable without Android (7 scenarios covered: single-page,
        multi-page with page markers, one page failing among several,
        every page failing, empty page list, unsupported language,
        all-blank results).
      - Wired into a "Run OCR" menu action (Home + Documents) with a
        language picker; the result is written via
        `DocumentDatabase.update_ocr_text`, and since `list_documents`
        has searched `ocr_text` since step 1, a document's actual
        *content* becomes searchable the moment it's OCR'd - verified
        this end-to-end against a real SQLite file (search by content
        matched the right document, excluded an unrelated one, and
        `update_ocr_text` persisted correctly).
      **Neither native OCR bridge can be executed or verified outside a
      real Android device** - `jnius.autoclass()` calls reference
      Google Play Services / Tesseract4Android classes that don't exist
      on a development machine. Both raise a clear `RuntimeError` off-
      Android rather than pretending to produce text; the desktop UI
      shows this plainly instead of hanging or failing silently.
- [x] **Step 14 — Native bridge optimization + real share-sheet**:
      audited every PyJNIus bridge built so far and found two concrete,
      documented anti-patterns in the OCR bridges - both created a
      brand-new native object (an ML Kit client / a Tesseract instance)
      **per page** instead of per document, and neither released native
      resources afterward (ML Kit's client was never `.close()`'d,
      decoded Bitmaps were never `.recycle()`'d - both hold native heap
      memory outside Java's garbage collector). Refactored both into
      `EnglishRecognizer`/`BengaliRecognizer` context-manager sessions -
      one native object created and cleaned up per "Run OCR" call,
      reused across every page. Verified the fix's actual claim, not
      just that the code runs: with a fake session object, confirmed
      the session is entered/exited exactly ONCE regardless of page
      count, confirmed it's still cleaned up correctly when a page
      fails mid-way, and confirmed a session-creation failure (e.g.
      missing traineddata) propagates with its original message
      instead of being swallowed into "every page failed".
      Also closed out the real Android share-sheet integration that
      earlier steps' comments had been deferring to "step 14":
      `storage/share.py` uses `androidstorage4kivy` (same
      Android-for-Python ecosystem as camera4kivy) rather than
      hand-rolling FileProvider manifest XML - that setup is easy to
      get subtly wrong and this project has no real device/build to
      verify it against, whereas androidstorage4kivy already handles
      it internally. Export's "complete" dialog now has a working
      SHARE button on Android.
- [x] **Step 15-16 — Buildozer + GitHub Actions, hardened**: these were
      scaffolded back in step 1, but a from-scratch review with every
      dependency now known turned up three things that would have
      broken a real build or shipped something wrong:
      - `assets/icons/app_icon.png` was referenced by both
        `buildozer.spec` and `main.py` but the file never actually
        existed - `assets/icons/` was empty. Generated a real (simple,
        placeholder-quality - swap in real branding when you have it)
        icon via PIL: a blue rounded-square with a white document
        glyph, matching the app's own Material Blue theme.
      - The CI workflow never cloned `camerax_provider`, so
        `buildozer.spec`'s `p4a.hook` pointed at a file that wouldn't
        exist in a fresh CI checkout - every CI build would have failed
        immediately. Added that clone as an explicit workflow step.
      - `android.enable_androidx = True` was missing entirely, despite
        every third-party dependency in this app (CameraX, ML Kit,
        Tesseract4Android, androidstorage4kivy) being AndroidX-based -
        without it, expect "duplicate class"/"class not found" errors.
        Added it. Also trimmed `READ_MEDIA_IMAGES`/`READ_MEDIA_VIDEO`
        from `android.permissions`: grepped the codebase and confirmed
        nothing reads from the shared media library (no gallery
        picker), so the app was requesting permissions it doesn't use.
      Verified `buildozer.spec` still parses as valid INI and the CI
      workflow as valid YAML after all these edits.
- [ ] Step 17 — Real device testing (genuinely can't be done from this
      environment - no Android device/emulator, and Kivy itself isn't
      installable here to even smoke-test on desktop; see the repeated
      notes throughout this README about what could and couldn't be
      verified without one)

## Beyond the original plan

- [x] **Settings screen**: `ui/settings.py` is now real (was a
      scaffold through step 16), backed by `storage/preferences.py` (a
      small JSON file - tested for defaults, persistence across
      restart, an unknown key, a corrupt file, and forward-compat with
      an older partial file). Controls: auto-capture on/off (applied
      as each new session's starting value; toggling it mid-scan on
      the scanner screen also updates this default going forward),
      default export format and OCR language (pre-highlighted the next
      time either dialog opens), and a live light/dark theme switch.
- [ ] Step 17 — Real device testing

Scanner, Preview, Editor, Documents, and Settings screens currently
exist as real, navigable scaffold screens (`ui/_scaffold_screen.py`)
that honestly say which build step fills them in — nothing in them is
faked as working.

## Project structure

```
CamScannerPython/
├── main.py                  # App entry point, ScreenManager, lifecycle
├── requirements.txt         # Desktop/dev pip dependencies
├── buildozer.spec           # Android build configuration
├── ui/
│   ├── kv/home.kv            # Home screen layout
│   ├── home.py                # Home screen logic (done)
│   ├── _scaffold_screen.py    # Shared base for not-yet-built screens
│   ├── scanner.py             # Camera + detection (step 3-8)
│   ├── preview.py             # Capture review (step 6-7)
│   ├── editor.py               # Multi-page editor + export (step 9-11)
│   ├── documents.py            # Document library (step 10)
│   └── settings.py             # Preferences
├── database/database.py     # SQLite document store (done)
├── storage/manager.py       # File path resolution, Android + desktop (done)
├── scanner/                 # OpenCV detection pipeline (step 3-8, empty for now)
├── image_processing/        # Filters/enhancement (step 8, empty for now)
├── ocr/                     # ML Kit bridge (step 12-13, empty for now)
├── pdf/                     # PDF export (step 11, empty for now)
└── .github/workflows/build-apk.yml
```

## Testing the detector

`scanner/detector.py` has zero Kivy/Android dependencies, so it can be
sanity-checked without the app running at all:

```python
import cv2
from scanner.detector import DocumentDetector

detector = DocumentDetector()
frame = cv2.imread("some_photo_of_a_document.jpg")
quad = detector.detect(frame)  # None, or a (4, 2) array of corners
```

Detection quality depends on lighting/contrast against the background,
same as any edge-based scanner - `MIN_AREA_RATIO` and
`DETECTION_WIDTH` in that file are the two knobs to tune first if it's
missing documents or picking up false positives.

## Camera setup note (Step 3)

`scanner/camera.py` wraps **Camera4Kivy**, the most direct maintained
path from Kivy to Android's CameraX (writing a full CameraX↔PyJNIus
bridge by hand would be its own multi-week project). Its upstream repo
is archived but the API is stable and widely used; if it ever breaks
against a newer Kivy/p4a, only this one module needs to change - no
other screen talks to the camera directly.

Before building for Android, add its native provider once:

```bash
cd CamScannerPython
git clone https://github.com/Android-for-Python/camerax_provider.git
rm -rf camerax_provider/.git
```

`buildozer.spec` already points `p4a.hook` at
`camerax_provider/gradle_options.py` and pins `android.api = 33`
(camerax_provider's current constraint).

## Run on desktop (dev/testing)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

This opens the KivyMD Home screen in a desktop window so you can test
navigation and the database/storage layers without a device.

## Build an Android APK locally

Follow the WSL/Ubuntu setup, `buildozer init`/`buildozer android debug`
steps from the original spec (section 19-21) — `buildozer.spec` here is
already configured with this project's package name, permissions, and
requirements, so you can skip straight to:

```bash
buildozer android debug
```

The APK lands in `bin/`.

## Build via GitHub Actions

Push to `main` (or run the workflow manually) and `.github/workflows/build-apk.yml`
builds a debug APK and uploads it as a workflow artifact named
`android-apk`.

> Buildozer/python-for-android versions move fast. If a CI build fails
> after a `buildozer-action` or Android SDK update, the fix is almost
> always a pinned recipe version in `buildozer.spec`, not a project
> rewrite.
