"""Registry of all supported export formats."""
from typing import Dict

from app.exports.base import Exporter
from app.exports.basic_exporters import CsvExporter, JsonExporter, MarkdownExporter
from app.exports.excel_exporter import ExcelExporter
from app.exports.tool_exporters import (
    AzureDevOpsExporter,
    TestRailExporter,
    XrayExporter,
    ZephyrExporter,
)

_EXPORTERS: Dict[str, Exporter] = {
    "json": JsonExporter(),
    "csv": CsvExporter(),
    "markdown": MarkdownExporter(),
    "excel": ExcelExporter(),
    "testrail": TestRailExporter(),
    "zephyr": ZephyrExporter(),
    "xray": XrayExporter(),
    "azure_devops": AzureDevOpsExporter(),
}


def get_exporter(format_name: str) -> Exporter:
    exporter = _EXPORTERS.get(format_name)
    if exporter is None:
        raise ValueError(
            f"Unsupported export format '{format_name}'. Supported: {list(_EXPORTERS)}"
        )
    return exporter
