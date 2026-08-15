terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.0"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "azurerm" {
  features {}
}

locals {
  common_tags = {
    environment = var.environment
    project     = var.project_name
    team        = var.team
    cost_centre = "learning"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "${var.project_name}-${var.environment}-rg"
  location = var.azure_region
  tags     = local.common_tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.project_name}-${var.environment}-logs"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "PerGB2018"
  retention_in_days    = 30
  tags                = local.common_tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "${var.project_name}-${var.environment}-env"
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.common_tags
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "${var.project_name}-${var.environment}-pg"
  resource_group_name    = azurerm_resource_group.main.name
  location               = azurerm_resource_group.main.location
  version                = "15"
  administrator_login    = var.postgres_admin_username
  administrator_password = var.postgres_admin_password
  storage_mb             = 32768
  sku_name                = "B_Standard_B1ms"
  tags                    = local.common_tags

  # Azure assigns/manages the availability zone dynamically after creation;
  # without this, Terraform keeps trying to "correct" a value it shouldn't
  # be fighting over — a documented AzureRM provider limitation, not a
  # mistake in this config. See registry.terraform.io's own notes on this
  # resource, and hashicorp/terraform-provider-azurerm#25538.
  lifecycle {
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_configuration" "pgvector" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR"
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "knowledge_brain"
  server_id = azurerm_postgresql_flexible_server.main.id
}

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  name                = "${var.project_name}-${var.environment}-kv"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"
  tags                = local.common_tags
}

resource "azurerm_user_assigned_identity" "backend" {
  name                = "${var.project_name}-${var.environment}-identity"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tags                = local.common_tags
}

resource "azurerm_key_vault_access_policy" "backend" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = azurerm_user_assigned_identity.backend.principal_id

  secret_permissions = ["Get", "List"]
}

resource "azurerm_key_vault_access_policy" "terraform_admin" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = data.azurerm_client_config.current.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = ["Get", "List", "Set", "Delete"]
}

locals {
  database_url = "postgresql+asyncpg://${var.postgres_admin_username}:${var.postgres_admin_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${azurerm_postgresql_flexible_server_database.main.name}"
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = local.database_url
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

resource "azurerm_key_vault_secret" "neo4j_password" {
  name         = "neo4j-password"
  value        = var.neo4j_password
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "openai-api-key"
  value        = var.openai_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

resource "azurerm_key_vault_secret" "voyage_api_key" {
  name         = "voyage-api-key"
  value        = var.voyage_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

resource "azurerm_key_vault_secret" "mcp_api_key" {
  name         = "mcp-api-key"
  value        = var.mcp_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

resource "azurerm_key_vault_secret" "azure_language_key" {
  name         = "azure-language-key"
  value        = var.azure_language_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_key_vault_access_policy.terraform_admin]
}

resource "azurerm_container_registry" "main" {
  name                = replace("${var.project_name}${var.environment}acr", "-", "")
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  tags                = local.common_tags
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id          = azurerm_user_assigned_identity.backend.principal_id
}

resource "azurerm_container_app" "backend" {
  name                         = "${var.project_name}-${var.environment}-backend"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.backend.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "neo4j-password"
    key_vault_secret_id = azurerm_key_vault_secret.neo4j_password.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "openai-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.openai_api_key.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "voyage-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.voyage_api_key.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "mcp-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.mcp_api_key.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "azure-language-key"
    key_vault_secret_id = azurerm_key_vault_secret.azure_language_key.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  secret {
    name                = "apim-gateway-secret"
    key_vault_secret_id = azurerm_key_vault_secret.gateway_secret.versionless_id
    identity            = azurerm_user_assigned_identity.backend.id
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "backend"
      image  = "${azurerm_container_registry.main.login_server}/knowledge-brain-backend:latest"
      cpu    = 0.5
      memory = "1Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "NEO4J_PASSWORD"
        secret_name = "neo4j-password"
      }

      env {
        name        = "OPENAI_API_KEY"
        secret_name = "openai-api-key"
      }

      env {
        name        = "VOYAGE_API_KEY"
        secret_name = "voyage-api-key"
      }

      env {
        name        = "MCP_API_KEY"
        secret_name = "mcp-api-key"
      }

      env {
        name        = "AZURE_LANGUAGE_KEY"
        secret_name = "azure-language-key"
      }

      env {
        name  = "NEO4J_URI"
        value = var.neo4j_uri
      }

      env {
        name  = "NEO4J_USER"
        value = var.neo4j_user
      }

      env {
        name  = "AZURE_LANGUAGE_ENDPOINT"
        value = var.azure_language_endpoint
      }

      env {
        name        = "APIM_GATEWAY_SECRET"
        secret_name = "apim-gateway-secret"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport         = "http"

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }

    # No IP restriction here, deliberately, not an oversight: Consumption
    # tier APIM (see apim.tf) doesn't expose a static, queryable outbound
    # IP at all — confirmed live via `az apim show ... publicIpAddresses`,
    # which came back empty. A network-level lock down to "only APIM can
    # reach this" would need Developer/Premium tier's VNet integration
    # instead, a real fixed monthly cost we chose not to take on right
    # now. The gateway_secret_middleware app-level check (see
    # app/core/middleware.py) is the one real lock protecting this
    # backend today — accepted, named trade-off, same shape as the MCP
    # server's single shared-secret gate.
  }

  tags = local.common_tags

  # Once deployed, GitHub Actions owns which image tag is actually
  # running (a plain `az containerapp update` on every push to main) —
  # Terraform provisions the Container App's shape (secrets, env vars,
  # scaling, ingress) but deliberately stops tracking the image field
  # after the first apply, so a later `terraform apply` for an
  # unrelated change never reverts a CI-deployed image back to this
  # file's static `:latest` reference. Same pattern as the Postgres
  # `zone` lifecycle block above, applied to a different kind of drift.
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
