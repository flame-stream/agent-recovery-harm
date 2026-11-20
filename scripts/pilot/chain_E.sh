#!/bin/bash
# condition E: strictly sequential, one world and one request to LM Studio at a time
P=
run() { # stand dv py
  cd "$1" || return
  PROJ=$P STAND="$1" APPWORLD_DATA="$1/data" COND=E DATAVER=$2 \
    "$3" -u $P/pilot_run.py >> $P/pilot_E/pilot_E_$2.log 2>&1
}
run $P/replay_root 0.1.0 $P/.venv311/bin/python
run $P/stand020   0.2.0 $P/stand020/venv/bin/python
echo DONE
