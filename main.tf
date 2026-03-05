#------------------------------------------------------------------------
#                              Resource Group
#------------------------------------------------------------------------
# Primary resource group that contains all environment resources.
resource "azurerm_resource_group" "ecommerce" {
  name     = "rg-${var.prefix}-${var.environment}"
  location = var.default_location
  tags     = var.tags
}

#------------------------------------------------------------------------
#                                Network
#------------------------------------------------------------------------
# Shared virtual network for app integration and private endpoints.
resource "azurerm_virtual_network" "ecommerce" {
  resource_group_name = azurerm_resource_group.ecommerce.name
  location            = azurerm_resource_group.ecommerce.location
  name                = "vnet-${var.prefix}-${var.environment}"
  address_space       = var.vnet_address_space
  tags                = var.tags
}

# Delegated subnet used by App Service regional VNet integration.
resource "azurerm_subnet" "app_integration" {
  resource_group_name  = azurerm_resource_group.ecommerce.name
  virtual_network_name = azurerm_virtual_network.ecommerce.name
  name                 = "snet-app-integration"
  address_prefixes     = var.app_integration_subnet_cidr

  delegation {
    name = "app-service-delegation"

    service_delegation {
      name    = "Microsoft.Web/serverFarms"
      actions = ["Microsoft.Network/virtualNetworks/subnets/action"]
    }
  }
}

# Isolated subnet dedicated to private endpoint NICs.
resource "azurerm_subnet" "private_endpoints" {
  resource_group_name  = azurerm_resource_group.ecommerce.name
  virtual_network_name = azurerm_virtual_network.ecommerce.name
  name                 = "snet-private-endpoints"
  address_prefixes     = var.private_endpoints_subnet_cidr
}

#------------------------------------------------------------------------
#                       Security / Shared Secrets
#------------------------------------------------------------------------
# Strong random SQL admin password kept in Terraform state.
resource "random_password" "sql_admin" {
  length           = 24
  special          = true
  override_special = "!@#$%*-_=+"
}

#------------------------------------------------------------------------
#                          Storage Account
#------------------------------------------------------------------------
# Private storage account for product images and app assets.
resource "azurerm_storage_account" "ecommerce" {
  resource_group_name           = azurerm_resource_group.ecommerce.name
  location                      = azurerm_resource_group.ecommerce.location
  name                          = substr(lower("st${var.prefix}${replace(var.environment, "-", "")}${substr(md5(var.subscription_id), 0, 5)}"), 0, 24)
  account_tier                  = "Standard"
  account_replication_type      = "LRS"
  public_network_access_enabled = false
  tags                          = var.tags
}

#------------------------------------------------------------------------
#                           Blob Container
#------------------------------------------------------------------------
# Private container that stores uploaded product images.
resource "azurerm_storage_container" "ecommerce" {
  storage_account_id    = azurerm_storage_account.ecommerce.id
  name                  = "images"
  container_access_type = "private"

  depends_on = [azurerm_storage_account.ecommerce]
}

#------------------------------------------------------------------------
#                            SQL Server
#------------------------------------------------------------------------
# Logical SQL Server with private networking and Entra admin configured.
resource "azurerm_mssql_server" "ecommerce" {
  resource_group_name           = azurerm_resource_group.ecommerce.name
  location                      = azurerm_resource_group.ecommerce.location
  name                          = substr(lower("sql${var.prefix}${replace(var.environment, "-", "")}${substr(md5(var.subscription_id), 0, 5)}"), 0, 63)
  version                       = "12.0"
  connection_policy             = "Proxy"
  administrator_login           = "${var.sql_admin_login}${var.prefix}"
  administrator_login_password  = random_password.sql_admin.result
  minimum_tls_version           = "1.2"
  public_network_access_enabled = false

  azuread_administrator {
    azuread_authentication_only = false
    login_username              = coalesce(var.sql_aad_admin_login_username, azurerm_user_assigned_identity.ecommerce_app.name)
    object_id                   = coalesce(var.sql_aad_admin_object_id, azurerm_user_assigned_identity.ecommerce_app.principal_id)
    tenant_id                   = coalesce(var.tenant_id, data.azurerm_client_config.current.tenant_id)
  }

  tags = var.tags
}

#------------------------------------------------------------------------
#                          SQL Single Database
#------------------------------------------------------------------------
# Serverless SQL database used by the Streamlit catalog app.
resource "azurerm_mssql_database" "ecommerce" {
  server_id                   = azurerm_mssql_server.ecommerce.id
  name                        = "db-${var.prefix}-${var.environment}"
  collation                   = "SQL_Latin1_General_CP1_CI_AS"
  sku_name                    = "GP_S_Gen5_1"
  storage_account_type        = "Local"
  zone_redundant              = false
  geo_backup_enabled          = false
  min_capacity                = 0.5
  max_size_gb                 = 32
  auto_pause_delay_in_minutes = 60
  read_replica_count          = 0

  depends_on = [azurerm_mssql_server.ecommerce]
}

#------------------------------------------------------------------------
#                  User-Assigned Managed Identity for Web App
#------------------------------------------------------------------------
# User-assigned identity used by the web app for Azure resource access.
resource "azurerm_user_assigned_identity" "ecommerce_app" {
  resource_group_name = azurerm_resource_group.ecommerce.name
  location            = azurerm_resource_group.ecommerce.location
  name                = "id-app-${var.prefix}-${var.environment}"
  tags                = var.tags
}

# Grants blob data permissions to the web app managed identity.
resource "azurerm_role_assignment" "blob_data_contributor_web_app" {
  scope                = azurerm_storage_account.ecommerce.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ecommerce_app.principal_id
}

#------------------------------------------------------------------------
#                         App Service Plan
#------------------------------------------------------------------------
# Linux App Service Plan that hosts the Streamlit web app.
resource "azurerm_service_plan" "ecommerce" {
  resource_group_name = azurerm_resource_group.ecommerce.name
  location            = azurerm_resource_group.ecommerce.location
  name                = "asp-${var.prefix}-${var.environment}"
  os_type             = "Linux"
  sku_name            = "B1"
  tags                = var.tags
}

#------------------------------------------------------------------------
#                           App Service
#------------------------------------------------------------------------
# Linux Web App deployed from ZIP package and integrated with the VNet subnet.
resource "azurerm_linux_web_app" "ecommerce" {
  resource_group_name       = azurerm_resource_group.ecommerce.name
  location                  = azurerm_resource_group.ecommerce.location
  service_plan_id           = azurerm_service_plan.ecommerce.id
  virtual_network_subnet_id = azurerm_subnet.app_integration.id

  name            = lower("app-${var.prefix}-${var.environment}-${substr(md5(var.subscription_id), 0, 5)}")
  https_only      = true
  zip_deploy_file = data.archive_file.streamlit_app.output_path

  site_config {
    always_on              = false
    vnet_route_all_enabled = true

    application_stack {
      python_version = "3.11"
    }

    # Starts Streamlit on the App Service expected bind address and port.
    app_command_line = "python -m streamlit run main.py --server.port 8000 --server.address 0.0.0.0"
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.ecommerce_app.id]
  }

  # Runtime app configuration and identity-based connection settings.
  app_settings = {
    WEBSITES_PORT                  = "8000"
    SCM_DO_BUILD_DURING_DEPLOYMENT = "true"
    BLOB_ACCOUNT_NAME              = azurerm_storage_account.ecommerce.name
    BLOB_CONTAINER_NAME            = azurerm_storage_container.ecommerce.name
    SQL_SERVER                     = azurerm_mssql_server.ecommerce.fully_qualified_domain_name
    SQL_DATABASE                   = azurerm_mssql_database.ecommerce.name
    SQL_AUTH_MODE                  = "entra-mi"
    SQL_MANAGED_IDENTITY_CLIENT_ID = azurerm_user_assigned_identity.ecommerce_app.client_id
    AZURE_CLIENT_ID                = azurerm_user_assigned_identity.ecommerce_app.client_id
    WEBSITE_DNS_SERVER             = "168.63.129.16"
  }

  tags = var.tags

  depends_on = [
    azurerm_private_endpoint.sql,
    azurerm_private_dns_zone_virtual_network_link.sql,
    azurerm_private_endpoint.storage_blob,
    azurerm_private_dns_zone_virtual_network_link.storage_blob,
  ]
}

#------------------------------------------------------------------------
#                       Private DNS + Private Endpoints
#------------------------------------------------------------------------
# Private DNS zone for Azure SQL private endpoint resolution.
resource "azurerm_private_dns_zone" "sql" {
  resource_group_name = azurerm_resource_group.ecommerce.name
  name                = "privatelink.database.windows.net"
}

# Private DNS zone for Blob private endpoint resolution.
resource "azurerm_private_dns_zone" "storage_blob" {
  resource_group_name = azurerm_resource_group.ecommerce.name
  name                = "privatelink.blob.core.windows.net"
}

# Links SQL private DNS zone to the application virtual network.
resource "azurerm_private_dns_zone_virtual_network_link" "sql" {
  resource_group_name   = azurerm_resource_group.ecommerce.name
  virtual_network_id    = azurerm_virtual_network.ecommerce.id
  private_dns_zone_name = azurerm_private_dns_zone.sql.name
  name                  = "pdns-link-sql"
}

# Links Blob private DNS zone to the application virtual network.
resource "azurerm_private_dns_zone_virtual_network_link" "storage_blob" {
  resource_group_name   = azurerm_resource_group.ecommerce.name
  virtual_network_id    = azurerm_virtual_network.ecommerce.id
  private_dns_zone_name = azurerm_private_dns_zone.storage_blob.name
  name                  = "pdns-link-storage-blob"
}

# Private endpoint for Azure SQL Server.
resource "azurerm_private_endpoint" "sql" {
  location                      = azurerm_resource_group.ecommerce.location
  resource_group_name           = azurerm_resource_group.ecommerce.name
  subnet_id                     = azurerm_subnet.private_endpoints.id
  name                          = "pep-sql-${var.prefix}-${var.environment}"
  custom_network_interface_name = "nic-pep-sql-${var.prefix}-${var.environment}"

  private_service_connection {
    name                           = "psc-sql"
    private_connection_resource_id = azurerm_mssql_server.ecommerce.id
    subresource_names              = ["sqlServer"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "pdnszg-sql"
    private_dns_zone_ids = [azurerm_private_dns_zone.sql.id]
  }
}

# Private endpoint for Azure Blob service in the storage account.
resource "azurerm_private_endpoint" "storage_blob" {
  resource_group_name           = azurerm_resource_group.ecommerce.name
  location                      = azurerm_resource_group.ecommerce.location
  subnet_id                     = azurerm_subnet.private_endpoints.id
  name                          = "pep-stblob-${var.prefix}-${var.environment}"
  custom_network_interface_name = "nic-pep-stblob-${var.prefix}-${var.environment}"

  private_service_connection {
    name                           = "psc-storage-blob"
    private_connection_resource_id = azurerm_storage_account.ecommerce.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "pdnszg-storage-blob"
    private_dns_zone_ids = [azurerm_private_dns_zone.storage_blob.id]
  }
}
