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
  description = "Which Azure region to deploy into."
  type        = string
  default     = "eastus"
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
