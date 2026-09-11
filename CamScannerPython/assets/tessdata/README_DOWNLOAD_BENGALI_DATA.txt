This directory must contain `ben.traineddata` before building for
Android - it's the Bengali language model Tesseract needs for
ocr/tesseract_ocr.py to work.

It is NOT included in this project: it's a multi-megabyte binary file,
and the environment that built this scaffold has no network access to
fetch it (and a fake placeholder file would just fail confusingly
on-device instead of being honest about the gap).

To add it:
    curl -L -o ben.traineddata \
      https://github.com/tesseract-ocr/tessdata_fast/raw/main/ben.traineddata

For higher accuracy at a larger file size, use tessdata_best instead:
    https://github.com/tesseract-ocr/tessdata_best/raw/main/ben.traineddata

The final path must be exactly:
    CamScannerPython/assets/tessdata/ben.traineddata

recognize_bengali() in ocr/tesseract_ocr.py checks for this file and
raises a clear error if it's missing, rather than failing silently.
