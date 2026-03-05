# Ecommerce Data Catalog - Architecture Journey (Simple View)

## Context
This project started as a simple public challenge: easy to launch, easy to understand, but with more exposure than we want in a production-like scenario.

## What Was Improved
We kept the app simple for users, but improved the backend design.

Main updates:
- Infrastructure is managed with Infrastructure as Code (IaC) using Terraform.
- The web app stays public for users.
- Database and Blob Storage are now private.
- Service-to-service communication happens through private paths.
- Managed Identity is used instead of hardcoded credentials.

## Before vs Now
Before:
- app, database, and storage were more public-facing,
- less isolation between application and data layers.

Now:
- users still access the app through a public URL,
- SQL and Blob are protected behind private endpoints,
- only approved Azure resources can connect to backend services,
- access is controlled through identity and permissions.

## How It Works Today
1. A user opens the web app.
2. The user submits product data and an image.
3. The app saves product data in SQL through a private connection.
4. The app saves image files in a private Blob container.
5. The app reads images securely from Blob to display the catalog.

In short: public user experience, private data communication.

## What Can Still Be Improved
The project was upgraded a lot, but there are still important next steps.

### Terraform Improvement: Use Reusable Modules
- Split the Terraform code into modules (for example: network, data layer, app layer, and security).

Why this matters:
- less duplicated code,
- easier promotion across environments (dev, test, prod),
- safer and faster changes,
- clearer ownership and easier maintenance.

### Application Improvement: Better Code Structure
- Break `main.py` into modules (for example: `ui`, `validators`, `services`, `config`).
- Create service classes/functions for SQL and Blob operations to keep UI code simpler.
- Add automated tests for image validation and data persistence flows.
- Add CI quality gates (lint, tests, and security checks) before deployment.
- Improve user error messages for uploads (for example: unsupported format vs corrupted image).

## Final Message
This is no longer only a simple public challenge setup.
It is now a safer and more realistic cloud architecture, with clear room for continuous improvement.
