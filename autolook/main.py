"""AutoLook entry point — CLI for testing, later launches GUI."""

import argparse
import sys
import time

from autolook.utils.silence import silence_third_party_noise

silence_third_party_noise()

from autolook.config import Config
from autolook.db.netmonitor_db import NetMonitorDB
from autolook.db.incident_db import AlertStore
from autolook.engine.scanner import Scanner


def print_status(config: Config, nm_db: NetMonitorDB, store: AlertStore):
    """Print a summary of current state."""
    print("=" * 60)
    print("AutoLook Status")
    print("=" * 60)
    print(f"Net Monitor DB : {config.netmonitor_db_path}")
    print(f"Recording path : {config.recording_path or '(not set)'}")
    print()
    for table in NetMonitorDB.TABLES:
        if nm_db.table_exists(table):
            count = nm_db.row_count(table)
            print(f"  {table:20s} : {count:>6d} rows")
    print()
    print(f"Session alerts : {store.incident_count()} (not saved)")


def print_incidents(incidents: list[dict]):
    """Print detected incidents to console."""
    for inc in incidents:
        level = inc.get("alert_level", "?").upper()
        dtype = inc.get("detection_type", "?")
        source = inc.get("source", "?")
        desc = inc.get("description", "")
        row = inc.get("row", {})
        ts = row.get("TIME", row.get("Time", "?"))
        user = row.get("USER", row.get("User", "?"))
        host = row.get("HOST", row.get("Host", "?"))
        print(f"  [{level:8s}] {ts} | {host}/{user} | {source} | {dtype} | {desc[:80]}")


def main():
    parser = argparse.ArgumentParser(description="AutoLook - Content Detection for Net Monitor")
    parser.add_argument("--config", type=str, default=None, help="Path to user config JSON")
    parser.add_argument("--status", action="store_true", help="Print status and exit")
    parser.add_argument("--poll", action="store_true", help="Poll once for new data and exit")
    parser.add_argument("--watch", action="store_true", help="Continuously poll for new data")
    parser.add_argument("--scan", nargs=2, metavar=("START", "END"),
                        help="Scan history range (e.g. '2026-09-01' '2026-09-04')")
    parser.add_argument("--gui", action="store_true", help="Launch GUI mode")
    args = parser.parse_args()

    if args.gui:
        from autolook.gui.main_window import run_gui
        run_gui()
        return

    config = Config(args.config)
    nm_db = NetMonitorDB(config.netmonitor_db_path)
    store = AlertStore(config.autolook_db_path)
    visits = VisitStore(config.visits_db_path)
    scanner = Scanner(config, nm_db, store, visits)

    if args.status:
        print_status(config, nm_db, store)
        return

    if args.poll:
        scanner.begin_runtime()
        incidents = scanner.scan_new()
        print(f"Polled: {len(incidents)} incidents detected.")
        print_incidents(incidents)
        return

    if args.watch:
        print(f"Watching every {config.scan_interval}s ... (Ctrl+C to stop)")
        scanner.begin_runtime()
        try:
            while True:
                incidents = scanner.scan_new()
                if incidents:
                    print(f"\n{len(incidents)} new incidents:")
                    print_incidents(incidents)
                time.sleep(config.scan_interval)
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    if args.scan:
        start, end = args.scan
        print(f"Scanning history: {start} to {end} ...")
        folder = str(config.recording_path or "")
        incidents = scanner.scan_history_folder(folder, start, end)
        print(f"Found {len(incidents)} alerts.")
        print_incidents(incidents)
        return

    print_status(config, nm_db, store)
    print("\nUsage: --poll | --watch | --scan START END | --status")


if __name__ == "__main__":
    main()
