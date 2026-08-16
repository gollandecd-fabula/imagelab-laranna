from __future__ import annotations

# Install the M2A/M2B routing adapter once at package initialization so every
# caller receives the same processing contract, independent of import order.
from app.services import image_processing as _legacy_processing
from app.services import halftone_fidelity as _halftone_fidelity
from app.services import background_fidelity as _background_fidelity
from app.services import extract_fidelity as _extract_fidelity
from app.services.m2a_processing import process_image as _m2a_process_image


def _m2b_process_image(asset, operation: str, params):
    normalized = operation.strip().lower()
    if normalized == "halftone":
        return _halftone_fidelity.process_halftone(asset, params)
    if normalized == "background" and str(params.get("action", "remove")).strip().lower() == "remove":
        return _background_fidelity.process_background(asset, params)
    if normalized == "extract_print":
        return _extract_fidelity.process_extract(asset, params)
    return _m2a_process_image(asset, operation, params)


_legacy_processing.process_image = _m2b_process_image

# v1.4.4 QA-9.1 separation adapter. Package initialization runs before callers
# import qa_service/repair_service, so all runtime consumers receive the same
# four-layer QA contract without changing processing engines.
from app.services import qa_contract as _qa_contract
_qa_contract.install()
