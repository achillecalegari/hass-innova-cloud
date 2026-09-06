"""Make the HA-independent ``api`` package importable without Home Assistant installed."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "custom_components" / "innova_cloud"))  # append: select.py must not shadow the stdlib
