#!/bin/bash
cd /home/user/workspace/jarvis_api
python3 -m uvicorn main:app --host 0.0.0.0 --port 8020 --reload
