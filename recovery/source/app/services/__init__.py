from __future__ import annotations

# Install the M2A geometry adapter once at package initialization so every
# caller receives the same processing contract, independent of import order.
from app.services import image_processing as _legacy_processing
from app.services.m2a_processing import process_image as _m2a_process_image

_legacy_processing.process_image = _m2a_process_image
