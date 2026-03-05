output "web_app_url" {
  description = "Public URL for the Streamlit app."
  value       = "https://${azurerm_linux_web_app.ecommerce.default_hostname}"
}
