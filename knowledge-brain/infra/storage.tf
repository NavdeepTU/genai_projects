# Document file storage (ADR-044) — the original uploaded file, kept
# separately from the extracted/chunked text that lives in Postgres.
# Locally this is emulated by Azurite (see docker-compose.yml); this file
# is what stands up the real thing.

resource "azurerm_storage_account" "documents" {
  name                     = replace("${var.project_name}${var.environment}docs", "-", "")
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  # LRS (locally-redundant storage): one data centre, three copies — the
  # cheapest redundancy tier, and the right call for a project without a
  # cross-region durability requirement. Same reasoning already applied to
  # every other resource here that offers a redundancy choice.
  account_replication_type = "LRS"
  # Defense in depth on top of the documents container's own
  # container_access_type = "private" below: no container in this
  # account — this one or any added later — can ever be granted
  # anonymous public access, even by mistake.
  allow_nested_items_to_be_public = false
  tags                             = local.common_tags
}

resource "azurerm_storage_container" "documents" {
  name                  = "documents"
  storage_account_name = azurerm_storage_account.documents.name
  # private: no anonymous public access at all. Every document is served
  # through the backend's own permission-checked route
  # (GET /documents/{id}/content), never a direct blob URL — a public
  # container would bypass that check entirely.
  container_access_type = "private"
}

# Grants the backend's own Managed Identity permission to read and write
# blobs directly against this account — no connection string, no Key
# Vault secret, no storage key exists anywhere in this app's configuration
# at all. See app/core/blob_storage.py: DefaultAzureCredential picks this
# role up automatically once the Container App runs under this identity,
# the cleanest form of ADR-020's Managed Identity requirement in this
# project so far, since Blob Storage supports passwordless auth natively —
# Postgres and Neo4j, by contrast, still need a real connection-string
# secret in Key Vault, since neither speaks Azure AD auth here.
resource "azurerm_role_assignment" "backend_blob_access" {
  scope                = azurerm_storage_account.documents.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.backend.principal_id
}
