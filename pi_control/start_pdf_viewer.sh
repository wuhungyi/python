#!/bin/bash
source /home/pi/dev/bin/activate
export DISPLAY=:0
cd /home/pi
exec python3 /home/pi/pdf_sop_viewer.py "$@" > /tmp/pdf_viewer.log 2>&1
