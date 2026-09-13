#!/usr/bin/env bash
#
# Starts or stops the deployed Azure Postgres server, so it isn't left
# running (and billing) between work sessions. Storage keeps billing
# either way — this only pauses/resumes the compute hours.
#
# Usage: scripts/db.sh start|stop
#
# Azure restarts a stopped server on its own after 7 days, regardless of
# this script — a known Azure behavior, not something this script can
# prevent. Run `scripts/db.sh stop` again if you come back after a
# longer break and want to be sure it's actually stopped.

set -euo pipefail

ACTION="${1:-}"
if [[ "$ACTION" != "start" && "$ACTION" != "stop" ]]; then
  echo "Usage: $0 start|stop" >&2
  exit 1
fi

if ! command -v az >/dev/null 2>&1; then
  echo "Azure CLI ('az') isn't installed — install it first: https://learn.microsoft.com/cli/azure/install-azure-cli" >&2
  exit 1
fi

if ! command -v terraform >/dev/null 2>&1; then
  echo "Terraform isn't installed — install it first, it's how this script finds your deployed server's name." >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "Not logged into Azure CLI — run 'az login' first." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$SCRIPT_DIR/../infra"

RESOURCE_GROUP="$(terraform -chdir="$INFRA_DIR" output -raw resource_group_name)"
SERVER_NAME="$(terraform -chdir="$INFRA_DIR" output -raw postgres_server_name)"

if [[ "$ACTION" == "stop" ]]; then
  echo "Stopping '$SERVER_NAME' — this pauses compute billing; storage keeps billing as normal."
else
  echo "Starting '$SERVER_NAME' — the database will be reachable again once this finishes."
fi

az postgres flexible-server "$ACTION" --name "$SERVER_NAME" --resource-group "$RESOURCE_GROUP"

if [[ "$ACTION" == "stop" ]]; then
  echo "Done — '$SERVER_NAME' is now stopped."
else
  echo "Done — '$SERVER_NAME' is now running."
fi
