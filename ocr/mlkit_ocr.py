"""
English text recognition via Google ML Kit (on-device, Latin script).

IMPORTANT LIMITATION discovered while planning step 12-13: ML Kit's
on-device Text Recognition only covers 5 scripts - Latin, Chinese,
Devanagari, Japanese, Korean. Bengali is NOT one of them (verified
against Google's own docs). This module only ever handles English/
Latin text; Bengali goes through ocr/tesseract_ocr.py instead - see
this project's README for the full explanation.

Design note: ML Kit's recognizer.process() returns a Task (Google Play
Services' async type), normally consumed via addOnSuccessListener/
addOnFailureListener. Implementing those as Java interfaces from Python
(via jnius.PythonJavaClass) is the "normal" PyJNIus pattern, but it's
also the most failure-prone part of a bridge like this to get right
without a real device to iterate against. Since OCR already runs on a
background thread (ocr_manager never calls this from the UI thread),
blocking that thread with com.google.android.gms.tasks.Tasks.await()
is both simpler and more robust than proxying a callback interface -
it turns the async call into an ordinary blocking function call.

Step 14 revision: the original version created a brand new ML Kit
client PER PAGE and never released it or the decoded Bitmap - wasteful
(client creation loads the on-device model each time) and a native
resource leak (Bitmaps hold native heap memory that Java's GC doesn't
reclaim on its own; the recognizer client also holds native resources
until closed). EnglishRecognizer now creates the client once per
document and reuses it across every page, recycling each page's Bitmap
immediately after that page is processed and closing the client when
the whole document is done - see ocr_manager.py for how a session
spans exactly one "Run OCR" call, not one page.

Requires (see buildozer.spec):
    android.gradle_dependencies = com.google.android.gms:play-services-mlkit-text-recognition:19.0.1

Cannot be exercised or verified outside a real Android device/emulator
- the jnius.autoclass() calls below reference Google Play Services
classes that simply do not exist on a development machine, so imports
of this module succeed everywhere, but EnglishRecognizer itself can
only ever run on-device.
"""

from kivy.utils import platform

MLKIT_AVAILABLE = platform == "android"

DEFAULT_TIMEOUT_SECONDS = 15.0


class EnglishRecognizer:
    """One ML Kit client, reused across every page of a document.

    Usage:
        with EnglishRecognizer() as recognizer:
            for path in page_paths:
                text = recognizer.recognize(path)

    The client (`__enter__`) and each page's Bitmap (recycled inside
    `recognize`) have separate lifetimes on purpose: the client is
    expensive to create and safe to reuse; a Bitmap is cheap to create
    but holds real native memory per page and should not accumulate
    across a multi-page document.
    """

    def __init__(self, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS):
        if not MLKIT_AVAILABLE:
            raise RuntimeError("ML Kit OCR is only available on Android")
        self.timeout_seconds = timeout_seconds
        self._client = None
        self._Tasks = None
        self._TimeUnit = None
        self._InputImage = None
        self._BitmapFactory = None

    def __enter__(self):
        from jnius import autoclass

        TextRecognition = autoclass("com.google.mlkit.vision.text.TextRecognition")
        TextRecognizerOptions = autoclass("com.google.mlkit.vision.text.latin.TextRecognizerOptions")
        self._InputImage = autoclass("com.google.mlkit.vision.common.InputImage")
        self._BitmapFactory = autoclass("android.graphics.BitmapFactory")
        self._Tasks = autoclass("com.google.android.gms.tasks.Tasks")
        self._TimeUnit = autoclass("java.util.concurrent.TimeUnit")

        self._client = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)
        return self

    def recognize(self, image_path: str) -> str:
        """Run the (already-created) recognizer on one page. Raises
        RuntimeError on a decode failure, timeout, or other bridge
        failure - ocr_manager.py catches this per page rather than
        letting one bad page abort the whole document."""
        bitmap = self._BitmapFactory.decodeFile(image_path)
        if bitmap is None:
            raise RuntimeError(f"Could not decode image for OCR: {image_path}")

        try:
            input_image = self._InputImage.fromBitmap(bitmap, 0)
            task = self._client.process(input_image)

            # Blocks THIS (background) thread until the recognizer
            # finishes, or raises after timeout_seconds - never call
            # this from the Android main/UI thread. Called via getattr
            # rather than Tasks.await(...) because "await" is a
            # reserved keyword in Python 3.7+ - the dotted form is a
            # SyntaxError even though it's a Java method name here,
            # not Python's async/await.
            await_method = getattr(self._Tasks, "await")
            result = await_method(
                task, int(self.timeout_seconds * 1000), self._TimeUnit.MILLISECONDS
            )
            return result.getText() or ""
        finally:
            # Bitmaps hold native heap memory outside Java's GC -
            # recycle promptly rather than letting them pile up across
            # a multi-page document.
            bitmap.recycle()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._client is not None:
            self._client.close()
            self._client = None
        return False
