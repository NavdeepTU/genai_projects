variable "project_name" {
  description = "Short name used to prefix every resource, so they're identifiable at a glance in the Azure portal."
  type        = string
  default     = "knowledge-brain"
}

variable "environment" {
  description = "Which environment this is — dev, staging, or prod. Used both in resource names and as a required cost-tracking tag."
  type        = string
  default     = "dev"
}

variable "team" {
  description = "Required cost-tracking tag identifying who owns these resources — no default, must be set explicitly."
  type        = string
}

variable "azure_region" {
  description = "Which Azure region to deploy into. eastus was tried first and found to be restricted for Postgres Flexible Server on this subscription (confirmed via az postgres flexible-server list-skus); centralus is not."
  type        = string
  default     = "centralus"
}

variable "postgres_admin_username" {
  description = "Admin username for the managed Postgres server."
  type        = string
  default     = "knowledge_brain_admin"
}

variable "postgres_admin_password" {
  description = "Admin password for the managed Postgres server. No default, deliberately — never checked into git."
  type        = string
  sensitive   = true
}

variable "neo4j_uri" {
  description = "Connection URI for the Neo4j AuraDB instance the deployed backend talks to. Not a secret itself, but specific to this deployment, so no default."
  type        = string
}

variable "neo4j_user" {
  description = "Neo4j username. AuraDB instances always use 'neo4j' as the admin username, so this defaults to it."
  type        = string
  default     = "neo4j"
}

variable "neo4j_password" {
  description = "Password for the Neo4j AuraDB instance. No default, deliberately — never checked into git."
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key used for embeddings and answer generation. No default, deliberately — never checked into git."
  type        = string
  sensitive   = true
}

variable "voyage_api_key" {
  description = "Voyage AI API key used for reranking. No default, deliberately — never checked into git."
  type        = string
  sensitive   = true
}

variable "mcp_api_key" {
  description = "Shared API key gating this project's own MCP server endpoint. No default, deliberately — never checked into git."
  type        = string
  sensitive   = true
}

variable "azure_language_endpoint" {
  description = "Endpoint URL for the Azure AI Language resource used for PII detection. Not a secret itself, but specific to this deployment, so no default."
  type        = string
}

variable "azure_language_key" {
  description = "API key for the Azure AI Language resource used for PII detection. No default, deliberately — never checked into git."
  type        = string
  sensitive   = true
}

variable "apim_publisher_name" {
  description = "Organization name shown on API Management's developer-facing pages (docs, notification emails). Cosmetic only, not a secret."
  type        = string
  default     = "Knowledge Brain"
}

variable "apim_publisher_email" {
  description = "Contact email Azure API Management sends service notifications to (e.g. certificate expiry warnings). Not a secret, but no default — must be a real address you actually check."
  type        = string
}
