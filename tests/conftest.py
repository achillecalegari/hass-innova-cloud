"""Make the HA-independent ``api`` package importable without Home Assistant installed."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components" / "innova_cloud"))
