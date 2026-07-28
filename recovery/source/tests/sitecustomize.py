from __future__ import annotations

import hashlib
import inspect
import json
import os
from pathlib import Path
from typing import Any

TRACE_PATH = os.environ.get("PILOT_GEOMETRY_TRACE", "").strip()

if TRACE_PATH:
    from app.services import image_processing as _image_processing

    _original_geometry = _image_processing._geometry
    _module_path = Path(_image_processing.__file__).resolve()
    _source_bytes = _module_path.read_bytes()
    _function_source = inspect.getsource(_original_geometry).encode("utf-8")

    def _append_trace(payload: dict[str, Any]) -> None:
        path = Path(TRACE_PATH).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _traced_geometry(image, ppi, params):
        base = {
            "pid": os.getpid(),
            "module_file": str(_module_path),
            "module_sha256": hashlib.sha256(_source_bytes).hexdigest(),
            "function_source_sha256": hashlib.sha256(_function_source).hexdigest(),
            "function_first_line": _original_geometry.__code__.co_firstlineno,
            "input_size": list(image.size),
            "input_ppi": ppi,
            "parameters": {
                key: params.get(key)
                for key in (
                    "width_mm",
                    "height_mm",
                    "ppi",
                    "preserve_aspect",
                    "canvas_width_mm",
                    "canvas_height_mm",
                    "margin_top_mm",
                    "margin_right_mm",
                    "margin_bottom_mm",
                    "margin_left_mm",
                )
                if key in params
            },
            "canvas_requested": any(
                params.get(key) is not None and params.get(key) != ""
                for key in (
                    "canvas_width_mm",
                    "canvas_height_mm",
                    "margin_top_mm",
                    "margin_right_mm",
                    "margin_bottom_mm",
                    "margin_left_mm",
                )
            ),
        }
        try:
            output, output_ppi = _original_geometry(image, ppi, params)
        except Exception as exc:
            _append_trace(
                {
                    **base,
                    "status": "raised",
                    "exception_type": type(exc).__name__,
                    "exception": str(exc),
                }
            )
            raise
        _append_trace(
            {
                **base,
                "status": "returned",
                "output_size": list(output.size),
                "output_ppi": output_ppi,
            }
        )
        return output, output_ppi

    _image_processing._geometry = _traced_geometry
