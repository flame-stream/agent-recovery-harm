#!/bin/bash
# one process per setup: the conditions run one after another, so as not to overload LM Studio
STAND_DIR=$1; DV=$2; PY=$3; shift 3
for C in "$@"; do
  cd "$STAND_DIR" || exit 1
  PROJ= STAND="$STAND_DIR" \
  APPWORLD_DATA="$STAND_DIR/data" COND=$C DATAVER=$DV \
  "$PY" -u pilot_run.py \
    >> pilot_${C}_${DV}.log 2>&1
done
