# Closes the one remaining gap in Enterprise Requirement 1 (API Gateway):
# APIM already handles versioning and the gateway-secret check, but never
# recorded a single request/response anywhere. Metadata only, deliberately
# — no bodies — so document/query content never lands in a third system,
# and so this stays inside Azure Monitor's 5 GB/month free ingestion
# allowance at this project's real traffic (a metadata-only entry is a
# couple KB; the free tier is 5,000,000 KB).
#
# Reuses the Log Analytics workspace azurerm_log_analytics_workspace.main
# (main.tf) already provisioned for Container Apps' own logs, rather than
# standing up a second one — Application Insights is workspace-based now,
# so it needs a workspace underneath it either way, and one already exists.
resource "azurerm_application_insights" "main" {
  name                = "${var.project_name}-${var.environment}-appinsights"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  workspace_id        = azurerm_log_analytics_workspace.main.id
  application_type    = "web"
  tags                = local.common_tags
}

# Tells APIM where "Application Insights" actually is — the destination
# half of the two-part setup (logger = address, diagnostic = what to send
# there and how much of it).
resource "azurerm_api_management_logger" "app_insights" {
  name                = "app-insights-logger"
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name
  resource_id         = azurerm_application_insights.main.id

  application_insights {
    instrumentation_key = azurerm_application_insights.main.instrumentation_key
  }
}

# The actual "turn logging on" switch, scoped to just the backend API —
# azurerm_api_management_api_diagnostic (api_name), not the plain
# azurerm_api_management_diagnostic resource, which is instance-wide and
# has no api_name argument at all; confirmed against the provider's own
# docs before writing this, not assumed from the similar-sounding name.
# 100% sampling, not partial — safe specifically because body_bytes = 0
# on every leg keeps each entry a couple KB, so there's no cost reason to
# sample down. http_correlation_protocol = "None" because this project
# already has its own correlation-ID scheme (X-Correlation-ID, set by
# app/core/middleware.py, not APIM) — turning on APIM's own W3C/Legacy
# correlation would just be a second, unused ID scheme running alongside
# the real one. headers_to_log instead explicitly captures the one header
# that lets an APIM log entry be matched back to the exact backend log
# lines (correlation_id-tagged JSON) that handled the same request.
#
# api_name is the literal "knowledge-brain-backend" string, deliberately
# not a azurerm_api_management_api.backend.name reference. Terraform
# dependency edges are whole-resource, not per-attribute: referencing
# .name would make this resource depend on that entire API resource,
# which itself depends on azurerm_container_app.backend (its service_url
# reads the container app's FQDN) — and that resource already had a
# pending, unrelated change sitting in main.tf (the Blob Storage env
# vars from an earlier, since-applied session) when this was written,
# which would in turn have dragged in creating the storage account just
# to turn on logging. The literal string is exactly what that API
# resource's own `name` argument is set to in apim.tf — stable, not
# Azure-generated.
#
# The real cost of that choice, hit live: a literal has no implicit
# ordering either. Recreating both azurerm_api_management_api.backend
# and this resource in the same apply once raced — Terraform started
# creating this diagnostic before the API resource's own destroy+create
# cycle had finished, and Azure rejected it with "Api not found" for
# the ~1 minute the old API was gone and the new one wasn't ready yet.
# depends_on restores correct ordering without reintroducing the
# argument-level reference (and the storage entanglement it caused) —
# it only affects apply order, not this resource's own values.
resource "azurerm_api_management_api_diagnostic" "backend" {
  identifier               = "applicationinsights"
  resource_group_name      = azurerm_resource_group.main.name
  api_management_name      = azurerm_api_management.main.name
  api_name                 = "knowledge-brain-backend"
  api_management_logger_id = azurerm_api_management_logger.app_insights.id

  sampling_percentage       = 100
  always_log_errors         = true
  log_client_ip             = true
  verbosity                 = "information"
  http_correlation_protocol = "None"

  frontend_request {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }

  frontend_response {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }

  backend_request {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }

  backend_response {
    body_bytes     = 0
    headers_to_log = ["X-Correlation-ID"]
  }

  depends_on = [
    azurerm_api_management_logger.app_insights,
    azurerm_api_management_api.backend,
  ]
}
