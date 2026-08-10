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
