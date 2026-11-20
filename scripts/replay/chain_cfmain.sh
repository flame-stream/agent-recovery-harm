#!/bin/bash
# capture of all calls of the 200 sample episodes: strictly sequential, without a model
P=
run() { # stand dv py
  cd "$1" || return
  PROJ=$P STAND="$1" DATAVER=$2 PYBIN="$3" "$3" -u $P/capture_main_batch.py 2>&1 \
    | grep --line-buffered -v -i warning >> $P/reports/counterfactual_main/capture_$2.log
}
run $P/replay_root 0.1.0 $P/.venv311/bin/python
run $P/stand020   0.2.0 $P/stand020/venv/bin/python
echo DONE >> $P/reports/counterfactual_main/capture_0.2.0.log
