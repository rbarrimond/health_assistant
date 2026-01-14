"""No-op placeholder kept for compatibility.

TLS verification for local Azurite HTTPS is now disabled in code to simplify
development; no CA bundle generation is required. This script remains to avoid
import or tooling errors if referenced elsewhere.
"""

def main() -> int:  # pragma: no cover - trivial
    print("No CA bundle generation required. Verification is disabled for local Azurite HTTPS.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
