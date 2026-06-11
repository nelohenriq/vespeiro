#!/usr/bin/env python3
"""
Start both the API server and Vite dev server for the Analisa.pt dashboard.

Usage:
    python start.py              # Start both servers
    python start.py --api-only   # API server only (port 8080)
    python start.py --build      # Build React app and serve from API server
"""

import argparse
import subprocess
import sys
import time
import urllib.request
import json
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
API_SERVER = SCRIPT_DIR.parent / "tools" / "api_server.py"


def wait_for_server(port: int, max_wait: int = 15) -> bool:
    """Wait for a server to be ready on the given port."""
    for i in range(max_wait):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def start_api_server(port: int = 8080):
    """Start the Python API server."""
    print(f"[1/2] Starting API server on port {port}...")
    proc = subprocess.Popen(
        [sys.executable, str(API_SERVER), "--port", str(port)],
        cwd=str(API_SERVER.parent),
    )
    return proc


def start_vite_dev(port: int = 3001, api_port: int = 8080):
    """Start the Vite dev server."""
    print(f"[2/2] Starting Vite dev server on port {port}...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "npx", "vite", "--port", str(port), "--host"],
        cwd=str(SCRIPT_DIR),
        shell=True,
    )
    return proc


def main():
    parser = argparse.ArgumentParser(description="Start Analisa.pt dashboard")
    parser.add_argument("--api-port", type=int, default=8080, help="API server port")
    parser.add_argument("--port", type=int, default=3001, help="Frontend port")
    parser.add_argument("--api-only", action="store_true", help="API server only")
    args = parser.parse_args()

    api_proc = start_api_server(args.api_port)

    # Wait for API server to be ready
    if wait_for_server(args.api_port):
        print(f"  API server ready on http://localhost:{args.api_port}")
    else:
        print(f"  WARNING: API server may not be ready on port {args.api_port}")

    if not args.api_only:
        vite_proc = start_vite_dev(args.port, args.api_port)
        print(f"\n  Dashboard: http://localhost:{args.port}")
        print(f"  API:       http://localhost:{args.api_port}")
        print(f"\n  Press Ctrl+C to stop both servers.\n")
    else:
        print(f"\n  API:       http://localhost:{args.api_port}")
        print(f"\n  Press Ctrl+C to stop.\n")

    try:
        api_proc.wait()
    except KeyboardInterrupt:
        print("\n  Stopping servers...")
        api_proc.terminate()
        if not args.api_only:
            vite_proc.terminate()
        api_proc.wait(timeout=5)
        if not args.api_only:
            vite_proc.wait(timeout=5)
        print("  Done.")


if __name__ == "__main__":
    main()
