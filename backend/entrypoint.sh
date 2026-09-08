#!/bin/sh
set -eu
# Guard every command, including migrations. The deployment controls migration ordering.
python -m app.core.deployment
exec "$@"
