#!/usr/bin/env bash
# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail
: "${COMPOSE_PROJECT_NAME:?Set a separate Compose project for each CI job}"

compose=(docker compose -f e2e/bub/compose.yaml -f e2e/bub/compose.oceanbase.yaml)
"${compose[@]}" up --detach --wait --wait-timeout 660 oceanbase
container_id=$("${compose[@]}" ps -q oceanbase)
# The slim image's default 1 GB maximum is too small for the
# indexes created across isolated acceptance databases.
docker exec "$container_id" \
  obclient -h127.0.0.1 -P2881 -uroot@sys \
  -e "ALTER SYSTEM SET datafile_maxsize='8G'; ALTER SYSTEM SET datafile_next='512M'; ALTER SYSTEM SET datafile_size='4G';"
datafile_ready=false
for config_attempt in $(seq 1 30); do
  docker exec "$container_id" \
    obclient -h127.0.0.1 -P2881 -uroot@sys --batch --skip-column-names \
    -e "SHOW PARAMETERS WHERE name IN ('datafile_size', 'datafile_maxsize', 'datafile_next');" \
    > "$RUNNER_TEMP/acceptance-datafile.tsv"
  if awk '
    $5 == "datafile_size" && $7 == "4G" { size = 1 }
    $5 == "datafile_maxsize" && $7 == "8G" { maximum = 1 }
    $5 == "datafile_next" && $7 == "512M" { increment = 1 }
    END { exit !(size && maximum && increment) }
  ' "$RUNNER_TEMP/acceptance-datafile.tsv"; then
    datafile_ready=true
    break
  fi
  sleep 2
done
cat "$RUNNER_TEMP/acceptance-datafile.tsv"
if [ "$datafile_ready" != true ]; then
  echo 'OceanBase datafile configuration did not become effective within one minute.' >&2
  exit 1
fi
docker exec "$container_id" \
  obclient -h127.0.0.1 -P2881 -uroot@test -ppowercontext-e2e \
  -Dpowercontext \
  -e "SET GLOBAL recyclebin=OFF; SELECT VERSION(); SHOW VARIABLES LIKE 'ob_compatibility_mode'; SHOW VARIABLES LIKE 'recyclebin';"
