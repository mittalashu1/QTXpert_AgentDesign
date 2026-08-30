#!/usr/bin/env python3
"""Preview or execute QTXpert generated-data retention against Neon.

Examples (run from ``backend`` with the production ``POSTGRES_URL`` and R2
secrets supplied through the environment):

    python scripts/purge_generated_data.py
    python scripts/purge_generated_data.py --execute

The default is a read-only preview.  ``--execute`` is intentionally required
for deletion so an accidentally invoked cron/container command cannot purge
data without an explicit operator decision.
"""
from __future__ import annotations

import argparse
import asyncio
import json

from app.config import get_settings
from app.database.session import AsyncSessionLocal
from app.services.data_retention import cleanup_generated_data


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    async with AsyncSessionLocal() as session:
        summary = await cleanup_generated_data(
            session,
            settings,
            dry_run=not args.execute,
            days=args.days,
            keep_latest=args.keep_latest,
        )
    print(json.dumps(summary.as_dict(), indent=2, sort_keys=True))
    return 0 if not summary.storage_failures and not summary.local_path_failures else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="delete eligible generated rows/assets after the preview policy is reviewed",
    )
    parser.add_argument("--days", type=int, default=None, help="override the configured age cutoff")
    parser.add_argument(
        "--keep-latest",
        type=int,
        default=None,
        help="override the newest-records-per-surface retention count",
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
