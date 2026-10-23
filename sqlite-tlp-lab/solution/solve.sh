#!/bin/sh
set -eu
SOURCE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT=${APP_ROOT:-/app}
for module in compiler generator runner __main__; do
    cp "$SOURCE/$module.py" "$APP_ROOT/tlp/$module.py"
done
cd "$APP_ROOT"
python -m unittest discover -s public_tests -v
python -m tlp campaign --seed 17 --count 112 --out reports/oracle-campaign
