#!/bin/bash
# Launch the Optimus Meknes scraper in the background
cd /home/z/my-project/optimus-scraper
export CLOAKBROWSER_SUPPRESS_FONT_WARNING=1
export PYTHONUNBUFFERED=1  # flush logs immediately

exec venv/bin/python run_scraper.py "$@"