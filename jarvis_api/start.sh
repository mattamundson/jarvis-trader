#!/bin/bash
cd /mnt/c/Users/mattm/ThinkorSwim/jarvis-trader/jarvis_api
export PYTHONPATH="/mnt/c/Users/mattm/ThinkorSwim/jarvis-trader"
python3 -m uvicorn main:app --host 0.0.0.0 --port 8020 --reload
