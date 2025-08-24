# Shopify Order Notifier

## Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Fill in the variables inside `.env` with your own tokens and database credentials.

`docker-compose.yml` reads these variables and spins up a local Postgres instance for development. The defaults in `.env.example` are placeholders and should be changed for real deployments.
