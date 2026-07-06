#!/usr/bin/env python3
"""Self-daemonizing wrapper for the scraper.

Usage:
    python daemon.py              # start in background
    python daemon.py --pages 5    # scrape 5 pages in background

Logs are written to logs/console.out and logs/scraper.log.
"""

import os
import sys

# Resolve project root (where this file lives)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Daemonize: double-fork to fully detach from terminal
if os.fork() > 0:
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    sys.exit(0)

# Redirect stdout/stderr to log file
log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)
sys.stdout = sys.stderr = open(os.path.join(log_dir, "console.out"), "a", buffering=1)

# Set working directory and environment
os.chdir(PROJECT_ROOT)
os.environ["CLOAKBROWSER_SUPPRESS_FONT_WARNING"] = "1"
os.environ["PYTHONUNBUFFERED"] = "1"

# Ensure project root is on the Python path
sys.path.insert(0, PROJECT_ROOT)

# Pass through any CLI arguments (e.g., --pages, --start-page)
sys.argv = ["run_scraper.py"] + sys.argv[1:]

# Import and run
from run_scraper import main
main()