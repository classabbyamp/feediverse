#!/bin/sh

while true; do
    /env/bin/feediverse ${VERBOSE+-v} ${DRY_RUN+-n} ${CONFIG_FILE:+-c "$CONFIG_FILE"} \
        ${STATE_FILE:+-s "$STATE_FILE"} ${DELAY:+-d "$DELAY"} ${DEDUPE:+-p "$DEDUPE"}
    sleep "${INTERVAL:-900}"
done
