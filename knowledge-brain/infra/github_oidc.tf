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

  # GitHub includes immutable numeric org/repo IDs alongside the names
  # in this account's OIDC subject claims (protects against a renamed
  # or transferred repo inheriting trust meant for the original one) —
  # confirmed from the exact subject Azure rejected on a real run, not
  # guessed at. The plain name-only format this was originally written
  # with no longer matches what GitHub actually sends.
  subject = "repo:NavdeepTU@35778181/genai_projects@1321286864:ref:refs/heads/main"
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
