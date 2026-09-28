"""Captcha solving: offline OCR first, then the user answers in the web UI."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .providers.base import CaptchaSpec, Cancelled

log = logging.getLogger(__name__)


class OcrSolver:
    """ddddocr text recognizer, loaded on first use and shared by all jobs.

    - Uses the `beta` model, which reads the k2s captcha style best.
    - Returns the raw recognized text; `CaptchaSpec.normalize` decides whether it is usable.
    """

    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()

    def read(self, image: bytes) -> str:
        """Return the text the model reads in `image`."""
        with self._lock:
            if self._model is None:
                import ddddocr

                self._model = ddddocr.DdddOcr(show_ad=False, beta=True)
            return self._model.classification(image)


class CaptchaSession:
    """Solves the captchas of one job.

    - The first `ocr_attempts` calls go to OCR. A guess that does not fit the spec returns None,
      which tells the provider to fetch a new image without submitting anything.
    - Later calls hand the image to the UI through `on_manual` and block until `submit` delivers
      the answer, or raise `Cancelled` when `cancelled` is set.
    """

    def __init__(self, ocr: OcrSolver | None, ocr_attempts: int, cancelled: threading.Event,
                 on_manual: Callable[[bytes], None], on_ocr: Callable[[int], None] = lambda n: None):
        self.ocr = ocr
        self.ocr_attempts = ocr_attempts if ocr else 0
        self.cancelled = cancelled
        self.on_manual = on_manual
        self.on_ocr = on_ocr
        self.attempts = 0
        self._answer: str | None = None
        self._answered = threading.Event()

    def solve(self, image: bytes, spec: CaptchaSpec) -> str | None:
        """Return an answer for `image`, or None to request a fresh image."""
        if self.cancelled.is_set():
            raise Cancelled()
        self.attempts += 1
        if self.ocr is not None and self.attempts <= self.ocr_attempts:
            self.on_ocr(self.attempts)
            try:
                text = self.ocr.read(image)
            except Exception as exc:
                log.warning("OCR failed: %s", exc)
                self.ocr_attempts = 0
            else:
                answer = spec.normalize(text)
                log.info("OCR read %r -> %r", text, answer)
                return answer
        return self._ask_user(image, spec)

    def submit(self, answer: str) -> None:
        """Deliver the user's answer to the waiting `solve` call."""
        self._answer = answer.strip()
        self._answered.set()

    def _ask_user(self, image: bytes, spec: CaptchaSpec) -> str | None:
        """Publish the image and wait for `submit` or cancellation."""
        self._answered.clear()
        self.on_manual(image)
        while not self._answered.wait(0.5):
            if self.cancelled.is_set():
                raise Cancelled()
        answer = self._answer or ""
        return spec.normalize(answer) or answer or None
