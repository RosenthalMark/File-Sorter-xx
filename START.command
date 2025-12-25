#!/bin/zsh
cd "$(dirname "$0")"

# Activate venv
source .venv/bin/activate

# Make sure deps exist (safe to run repeatedly)
pip -q install -r requirements.txt

# Start server in the background
python server.py > server.log 2>&1 &

# Give it a second to boot
sleep 1

# Open the UI
open "http://127.0.0.1:5050"