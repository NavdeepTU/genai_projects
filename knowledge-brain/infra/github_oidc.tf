provider "azuread" {}

resource "azuread_application" "github_actions" {
  display_name = "${var.project_name}-${var.environment}-github-actions"
}

resource "azuread_service_principal" "github_actions" {
  client_id = azuread_application.github_actions.client_id
}

resource "azuread_application_federated_identity_credential" "github_actions" {
  application_id = azuread_application.github_actions.id
  display_name   = "github-actions-knowledge-brain-main"
  description    = "Trusts GitHub Actions runs on knowledge-brain's main branch to authenticate via OIDC, no stored secret."
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:NavdeepTU/genai_projects:ref:refs/heads/main"
}

resource "azurerm_role_assignment" "github_actions_acr_push" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "github_actions_container_apps" {
  scope                = azurerm_container_app.backend.id
  role_definition_name = "Container Apps Contributor"
  principal_id         = azuread_service_principal.github_actions.object_id
}
