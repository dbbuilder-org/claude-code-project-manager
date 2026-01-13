"""Scanner module for detecting and parsing projects."""

from .detector import ProjectDetector
from .parser import ProgressParser

__all__ = ["ProjectDetector", "ProgressParser"]
