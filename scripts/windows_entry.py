"""Absolute imports allow PyInstaller to resolve the package from this script."""
from bg_review.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
