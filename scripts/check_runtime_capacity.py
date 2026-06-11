from __future__ import annotations

import argparse
import shutil
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Check runtime filesystem capacity.")
    parser.add_argument("--path", default="/")
    parser.add_argument("--warning", type=float, default=75.0)
    parser.add_argument("--critical", type=float, default=85.0)
    args = parser.parse_args()

    usage = shutil.disk_usage(args.path)
    percent = round((usage.used / usage.total) * 100, 2)
    if percent >= args.critical:
        status, exit_code = "critical", 2
    elif percent >= args.warning:
        status, exit_code = "warning", 1
    else:
        status, exit_code = "ok", 0
    print(f"disk_status={status} used_percent={percent} path={args.path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
