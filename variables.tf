variable "default_location" {
  description = "Azure region where the resource group and regional services are created."
  type        = string
  default     = "australiaeast"
}

variable "subscription_id" {
  description = "Azure subscription ID used by the provider."
  type        = string
  default     = "" # Replace with your subscription ID or set via environment variable.
}

variable "prefix" {
  description = "Short naming prefix used in resource names."
  type        = string
  default     = "ecomm"
}

variable "environment" {
  description = "Environment label used in resource names, for example lab, dev, or prod."
  type        = string
  default     = "lab"
}

variable "sql_admin_login" {
  description = "Base SQL admin login."
  type        = string
  default     = "sqladminuser"
}

variable "sql_aad_admin_login_username" {
  description = "Optional Microsoft Entra SQL admin username; when null, the user-assigned identity name is used."
  type        = string
  default     = null
  nullable    = true
}

variable "sql_aad_admin_object_id" {
  description = "Optional Microsoft Entra SQL admin object ID; when null, the user-assigned identity principal ID is used."
  type        = string
  default     = null
  nullable    = true
}

variable "tenant_id" {
  description = "Optional Microsoft Entra tenant ID for SQL admin setup; when null, the current authenticated tenant is used."
  type        = string
  default     = null
  nullable    = true
}

variable "vnet_address_space" {
  description = "Address space assigned to the shared virtual network."
  type        = list(string)
  default     = ["10.30.0.0/16"]
}

variable "app_integration_subnet_cidr" {
  description = "CIDR range for the delegated App Service VNet integration subnet."
  type        = list(string)
  default     = ["10.30.1.0/24"]
}

variable "private_endpoints_subnet_cidr" {
  description = "CIDR range for the subnet that hosts private endpoint network interfaces."
  type        = list(string)
  default     = ["10.30.2.0/24"]
}

variable "tags" {
  description = "Tag map applied to resources that support tags in this deployment."
  type        = map(string)
  default = {
    deployed_by = "terraform"
    environment = "lab"
    project     = "ecommerce"
  }
}
