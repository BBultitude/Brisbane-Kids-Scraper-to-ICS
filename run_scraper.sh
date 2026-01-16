#!/bin/bash
export DISPLAY=:0
cd /home/bryan/scraper-project
source venv/bin/activate
python3 brisbanekids-scraper.py
