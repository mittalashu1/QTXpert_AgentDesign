"""Export format abstraction - one exporter per output target.

Adding TestRail/Zephyr/Xray/Azure DevOps or any future format only requires
implementing `Exporter` and registering it in `registry.py`; API routes and
the frontend Export button never change.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.database.models.generation_run import GenerationRun


@dataclass
class ExportResult:
    filename: str
    media_type: str
    content: bytes


class Exporter(ABC):
    format_name: str = "base"

    @abstractmethod
    def export(self, run: GenerationRun) -> ExportResult:
        ...
