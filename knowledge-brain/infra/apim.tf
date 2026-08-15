resource "azurerm_api_management" "main" {
  name                = "${var.project_name}-${var.environment}-apim"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  publisher_name      = var.apim_publisher_name
  publisher_email     = var.apim_publisher_email

  # Consumption tier: pay-per-call, no fixed monthly cost, matches every
  # other "cheapest managed option" choice in this project (Postgres
  # Burstable, ACR Basic). The real trade-off: this tier has no VNet
  # integration and no static outbound IP at all (confirmed live via
  # `az apim show`), so network-level restriction on the Container App's
  # ingress isn't achievable here — see infra/main.tf's ingress block
  # and ADR-026. The gateway_secret_middleware app-level check is the
  # one real lock protecting the backend today.
  sku_name = "Consumption_0"

  # APIM needs its own identity now — not for anything in chunk 1, but
  # because it's about to need to read one secret from Key Vault itself
  # (the gateway secret below). Added now, not upfront, for the same
  # reason nothing in this project gets built before it's actually needed.
  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags
}

resource "random_password" "gateway_secret" {
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "gateway_secret" {
  name         = "apim-gateway-secret"
  value        = random_password.gateway_secret.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

# APIM's identity gets its own, separate grant — the backend's managed
# identity already has an access policy on this Key Vault, but that
# policy only covers that one identity's object ID. Key Vault checks a
# per-identity list, not "anything already trusted once."
resource "azurerm_key_vault_access_policy" "apim" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_api_management.main.identity[0].principal_id

  secret_permissions = ["Get", "List"]
}

resource "azurerm_api_management_api" "backend" {
  name                = "knowledge-brain-backend"
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main.name
  revision            = "1"
  display_name        = "Knowledge Brain Backend"
  path                  = "v1"
  protocols             = ["https"]
  subscription_required = false

  # Where APIM actually forwards traffic to, once a request passes every
  # check — the real Container App address, never shown to the public.
  service_url = "https://${azurerm_container_app.backend.ingress[0].fqdn}"

  # Rather than hand-declaring every route (/documents/upload, /query, ...)
  # a second time, APIM reads them straight from FastAPI's own
  # auto-generated OpenAPI spec — the same /openapi.json Swagger UI
  # already uses. Stays accurate as routes change, as long as this file
  # gets re-applied after they do.
  import {
    content_format = "openapi+json-link"
    content_value  = "https://${azurerm_container_app.backend.ingress[0].fqdn}/openapi.json"
  }
}

# A place inside APIM to reference a config value by name, rather than
# pasting the raw secret string directly into the policy XML below.
# `value_from_key_vault` means APIM fetches the live value itself, using
# the identity and access policy from the previous chunk — Terraform
# never sees or stores the plaintext secret a second time here.
resource "azurerm_api_management_named_value" "gateway_secret" {
  name                = "gateway-secret"
  resource_group_name = azurerm_resource_group.main.name
  api_management_name = azurerm_api_management.main.name
  display_name        = "gateway-secret"
  secret              = true

  value_from_key_vault {
    secret_id = azurerm_key_vault_secret.gateway_secret.id
  }

  depends_on = [azurerm_key_vault_access_policy.apim]
}

resource "azurerm_api_management_api_policy" "backend" {
  api_name            = azurerm_api_management_api.backend.name
  api_management_name = azurerm_api_management.main.name
  resource_group_name = azurerm_resource_group.main.name

  # Rate limiting deliberately left out for now: Consumption tier's
  # rate-limit-by-key policy isn't supported at all ("Policy is not
  # allowed in 'Consumption' sku", confirmed live), and the plain
  # rate-limit policy Azure offers instead is scoped per-subscription —
  # meaningless here since subscription_required = false. Adding it back
  # honestly would mean reversing that decision first, not just pasting
  # in a snippet. Tracked as a named, deferred gap, not forgotten.
  xml_content = <<XML
<policies>
  <inbound>
    <base />
    <set-header name="X-Gateway-Secret" exists-action="override">
      <value>{{gateway-secret}}</value>
    </set-header>
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
XML

  depends_on = [azurerm_api_management_named_value.gateway_secret]
}
