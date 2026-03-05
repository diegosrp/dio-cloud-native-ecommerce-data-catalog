# AzureRM provider configuration for this environment.

provider "azurerm" {
  # Target Azure subscription used by this deployment.
  subscription_id = var.subscription_id

  # Provider-level feature flags.
  features {
    # Allows deleting a resource group even if it still contains resources.
    # Useful for lab/demo teardown workflows.
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
  }
}
