# Data sources provide read-only context and generate the app artifact for deployment.

# Current Azure client context (subscription, tenant, and identity metadata).
data "azurerm_client_config" "current" {}

# Packages the Streamlit app files into a ZIP consumed by zip deploy.
data "archive_file" "streamlit_app" {
  type        = "zip"
  output_path = "${path.module}/streamlit-app.zip"

  # Main Streamlit application entrypoint.
  source {
    content  = file("${path.module}/main.py")
    filename = "main.py"
  }

  # Python dependencies installed during App Service build/deploy.
  source {
    content  = file("${path.module}/requirements.txt")
    filename = "requirements.txt"
  }

  # Streamlit runtime settings (for example, upload size limits).
  source {
    content  = file("${path.module}/.streamlit/config.toml")
    filename = ".streamlit/config.toml"
  }
}
