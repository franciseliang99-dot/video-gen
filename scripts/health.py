#!/usr/bin/env python3
"""video-gen health-check CLI (out-of-band of the SKILL).

Usage:
    python3 scripts/health.py --version       # plain: "video-gen 0.2.5"
    python3 scripts/health.py --version --json # health-check JSON

Exit codes (matches director maintainer protocol):
    0 = healthy
    1 = degraded (non-critical dep missing, can still partial-render)
    2 = broken (critical dep missing, cannot render)
    3 = protocol error (script itself crashed)
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = ROOT / "VERSION"
__version__ = VERSION_FILE.read_text().strip() if VERSION_FILE.exists() else "unknown"

NOTO_CJK_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto-cjk/NotoSansCJK-Regular.ttc",
]


def _health_dict() -> dict:
    deps, checks, reasons = [], [], []

    # Critical binaries: ffmpeg + ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        deps.append({"name": tool, "kind": "binary", "ok": path is not None,
                     "found": path or "", "required": "any (>=4.x)"})
        if path is None:
            reasons.append(f"{tool} not on PATH (critical)")

    # Critical python deps
    for pkg, mod_name in (("Pillow", "PIL"), ("pydantic", "pydantic")):
        try:
            mod = __import__(mod_name)
            ver = getattr(mod, "__version__", "unknown")
            deps.append({"name": pkg, "kind": "python", "ok": True,
                         "found": ver, "required": "any"})
        except ImportError as e:
            deps.append({"name": pkg, "kind": "python", "ok": False, "error": str(e)})
            reasons.append(f"{pkg} not installed (critical)")

    # Optional but expected: Noto CJK font for caption rendering
    cjk_found = next((p for p in NOTO_CJK_CANDIDATES if Path(p).exists()), None)
    deps.append({"name": "NotoSansCJK", "kind": "file",
                 "ok": cjk_found is not None,
                 "found": cjk_found or "",
                 "required": "fonts-noto-cjk (degraded if missing — Latin captions still work)"})

    crit = [d for d in deps if not d["ok"] and d["name"] in ("ffmpeg", "ffprobe", "Pillow", "pydantic")]
    cjk_dep = deps[-1]
    healthy = not crit
    if not healthy:
        severity = "broken"
    elif not cjk_dep["ok"]:
        severity = "degraded"
        reasons.append("NotoSansCJK font missing — CJK captions will fall back to default font")
    else:
        severity = "ok"

    return {
        "name": "video-gen", "version": __version__,
        "healthy": healthy,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "deps": deps, "env": [], "checks": checks, "reasons": reasons,
        "extra": {
            "runtime": f"python{sys.version_info.major}.{sys.version_info.minor}",
            "skill_dir": str(ROOT),
            "severity": severity,
        },
    }


def main() -> int:
    if "--version" not in sys.argv:
        print("usage: python3 scripts/health.py --version [--json]", file=sys.stderr)
        return 1
    if "--json" not in sys.argv:
        print(f"video-gen {__version__}")
        return 0
    h = _health_dict()
    print(json.dumps(h, indent=2, ensure_ascii=False))
    return 0 if h["healthy"] else (1 if h["extra"]["severity"] == "degraded" else 2)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        sys.stderr.write(f"protocol error: {e!r}\n")
        sys.exit(3)
