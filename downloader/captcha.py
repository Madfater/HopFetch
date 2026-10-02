"""Captcha solving with offline OCR."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from .providers.base import CaptchaSpec, Cancelled, ProviderError

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
    """Solves the captchas of one job with OCR only.

    - Each call reads one image. A guess that does not fit the spec returns None, which tells
      the provider to fetch a new image without submitting anything.
    - After `max_attempts` calls, or when the OCR model cannot run, raises
      `ProviderError("captcha_failed")`.
    """

    def __init__(self, ocr: OcrSolver, max_attempts: int, cancelled: threading.Event,
                 on_attempt: Callable[[int], None] = lambda n: None):
        self.ocr = ocr
        self.max_attempts = max_attempts
        self.cancelled = cancelled
        self.on_attempt = on_attempt
        self.attempts = 0

    def solve(self, image: bytes, spec: CaptchaSpec) -> str | None:
        """Return an answer for `image`, or None to request a fresh image."""
        if self.cancelled.is_set():
            raise Cancelled()
        if self.attempts >= self.max_attempts:
            raise ProviderError("captcha_failed")
        self.attempts += 1
        self.on_attempt(self.attempts)
        try:
            text = self.ocr.read(image)
        except Exception as exc:
            log.warning("OCR failed: %s", exc)
            raise ProviderError("captcha_failed", "errors.captcha_failed_ocr") from exc
        answer = spec.normalize(text)
        log.info("OCR read %r -> %r", text, answer)
        return answer
