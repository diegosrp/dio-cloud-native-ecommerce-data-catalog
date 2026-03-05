# Pin Terraform CLI and provider versions to keep deployments reproducible across environments.

terraform {
  required_providers {
    # Azure Resource Manager provider.
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.62.1"
    }

    # Random value generator for deterministic resource naming patterns.
    random = {
      source  = "hashicorp/random"
      version = "= 3.8.1"
    }

    # Archive provider used to build deployable ZIP packages.
    archive = {
      source  = "hashicorp/archive"
      version = "= 2.7.1"
    }
  }

  # Required Terraform CLI version for this configuration.
  required_version = "= 1.12.2"
}
