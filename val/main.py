"""CLI entrypoint wrapping the refined main_simple core logic."""

import sys
from pathlib import Path

# Add the parent directory of this file to sys.path if not present to support running directly or as a module
parent_dir = str(Path(__file__).resolve().parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from main_simple import main
except ImportError:
    from val.main_simple import main

if __name__ == "__main__":
    sys.exit(main())