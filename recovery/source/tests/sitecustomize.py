from __future__ import annotations

import builtins
import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

TRACE_PATH = os.environ.get("PILOT_GEOMETRY_TRACE", "").strip()
_TARGET_MODULE = "app.services.image_processing"

if TRACE_PATH:
    _original_import = builtins.__import__
    _wrapped = False
    _installing = False

    def _append_trace(payload: dict[str, Any]) -> None:
        path = Path(TRACE_PATH).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def _install_trace_if_loaded() -> None:
        global _wrapped, _installing
        if _wrapped or _installing:
            return
        module = sys.modules.get(_TARGET_MODULE)
        if module is None or not hasattr(module, "_geometry"):
            return

        _installing = True
        try:
            original_geometry = module._geometry
            module_path = Path(module.__file__).resolve()
            source_bytes = module_path.read_bytes()
            function_source = inspect.getsource(original_geometry).encode("utf-8")

            def traced_geometry(image, ppi, params):
                base = {
                    "pid": os.getpid(),
                    "module_file": str(module_path),
                    "module_sha256": hashlib.sha256(source_bytes).hexdigest(),
                    "function_source_sha256": hashlib.sha256(function_source).hexdigest(),
                    "function_first_line": original_geometry.__code__.co_firstlineno,
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
                    output, output_ppi = original_geometry(image, ppi, params)
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

            module._geometry = traced_geometry
            _wrapped = True
            builtins.__import__ = _original_import
        finally:
            _installing = False

    def _tracing_import(name, globals=None, locals=None, fromlist=(), level=0):
        result = _original_import(name, globals, locals, fromlist, level)
        if name == _TARGET_MODULE or _TARGET_MODULE in sys.modules:
            _install_trace_if_loaded()
        return result

    builtins.__import__ = _tracing_import
