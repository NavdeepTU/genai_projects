output "resource_group_name" {
  description = "The resource group everything else was created inside."
  value       = azurerm_resource_group.main.name
}

output "container_app_environment_id" {
  description = "Needed when we define the actual Container App resource in a later chunk."
  value       = azurerm_container_app_environment.main.id
}

output "postgres_server_fqdn" {
  description = "The Postgres server's address, for building a connection string."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "key_vault_uri" {
  description = "The Key Vault's address, for wiring up secret references later."
  value       = azurerm_key_vault.main.vault_uri
}

output "managed_identity_client_id" {
  description = "Needed to attach this identity to the Container App later."
  value       = azurerm_user_assigned_identity.backend.client_id
}

output "managed_identity_principal_id" {
  description = "Needed to grant this identity further roles later, e.g. permission to pull images from the container registry."
  value       = azurerm_user_assigned_identity.backend.principal_id
}

output "backend_url" {
  description = "The Container App's stable public URL. Always resolves to whichever revision currently holds live traffic — unlike a revision-pinned URL, it doesn't go stale when a new revision is deployed."
  value       = "https://${azurerm_container_app.backend.ingress[0].fqdn}"
}

output "container_registry_login_server" {
  description = "Needed later to tag and push our own image, once we're ready to replace the placeholder."
  value       = azurerm_container_registry.main.login_server
}

output "github_actions_client_id" {
  description = "Set as the AZURE_CLIENT_ID GitHub Actions variable (not a secret) — identifies the OIDC identity to azure/login."
  value       = azuread_application.github_actions.client_id
}

output "github_actions_tenant_id" {
  description = "Set as the AZURE_TENANT_ID GitHub Actions variable (not a secret)."
  value       = data.azurerm_client_config.current.tenant_id
}

output "github_actions_subscription_id" {
  description = "Set as the AZURE_SUBSCRIPTION_ID GitHub Actions variable (not a secret)."
  value       = data.azurerm_client_config.current.subscription_id
}

output "container_registry_name" {
  description = "Set as the ACR_NAME GitHub Actions variable — needed for `az acr login --name`."
  value       = azurerm_container_registry.main.name
}

output "container_app_name" {
  description = "Set as the CONTAINER_APP_NAME GitHub Actions variable — needed for `az containerapp update --name`."
  value       = azurerm_container_app.backend.name
}

output "apim_gateway_url" {
  description = "The public URL meant to be used to reach the backend. The Container App's own direct URL still works too (Consumption tier has no static IP to restrict to — see ADR-026); the gateway secret header is the one real lock, not network isolation."
  value       = "${azurerm_api_management.main.gateway_url}/${azurerm_api_management_api.backend.path}"
}
