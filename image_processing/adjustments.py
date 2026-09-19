"""Fine page adjustments used by PreviewScreen."""
import cv2
import numpy as np


def adjust_image(image_bgr, brightness=0, contrast=1.0, saturation=1.0, sharpness=0.0):
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Empty image")
    img = image_bgr.astype(np.float32)
    img = (img - 127.5) * float(contrast) + 127.5 + float(brightness)
    img = np.clip(img, 0, 255).astype(np.uint8)

    sat = max(0.0, float(saturation))
    if abs(sat - 1.0) > 1e-3:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat, 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    sharp = max(0.0, float(sharpness))
    if sharp > 1e-3:
        blurred = cv2.GaussianBlur(img, (0, 0), 1.2)
        img = cv2.addWeighted(img, 1.0 + sharp, blurred, -sharp, 0)
    return img
