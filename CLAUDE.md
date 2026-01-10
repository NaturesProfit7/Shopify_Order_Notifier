# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Language Preference
**All responses should be in Russian (Все ответы на русском языке).**

## Commands

### Development
- **Run application**: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
- **Run with Docker**: `docker-compose up --build`
- **Run tests**: `pytest` (runs from project root with `pytest.ini` config)
- **Run specific test file**: `pytest tests/test_specific_file.py`
- **Database migrations**: `alembic upgrade head` (apply migrations)
- **Create new migration**: `alembic revision --autogenerate -m "description"`

### Testing and Quality
The project uses pytest for testing with configuration in `pytest.ini`. Tests are located in the `tests/` directory and various test files in the root directory. Run tests with `pytest` from the project root.

## Architecture Overview

### Core Components
This is a **Shopify Order Notifier** - a FastAPI application that receives Shopify webhooks for new orders and sends notifications via Telegram bot with PDF invoices and VCF contact files.

**Main Application Flow:**
1. **Webhook Reception** (`app/main.py`): Receives Shopify `orders/create` webhooks with HMAC validation
2. **Order Processing**: Extracts customer data using address logic to handle billing vs shipping addresses
3. **Telegram Notifications**: Sends order details to managers with inline keyboards for order management
4. **File Generation**: Creates PDF invoices and VCF contact files on-demand

### Key Architecture Patterns

**Bot Management**: 
- Uses singleton pattern `TelegramBot` class in `app/bot/main.py`
- Integrates with FastAPI lifecycle for coordinated startup/shutdown
- Supports both polling and webhook modes

**Address Resolution Logic**:
- Implements smart contact detection in `app/services/address_utils.py`
- Handles cases where billing and shipping addresses differ
- Extracts correct contact person and phone number for Ukrainian market

**Order State Management**:
- SQLAlchemy models with `OrderStatus` enum: NEW → WAITING_PAYMENT → PAID/CANCELLED  
- Status history tracking with user attribution
- Reminder system with scheduled jobs

**Service Layer Organization**:
- `app/services/`: Core business logic (Shopify API, PDF generation, phone utils, etc.)
- `app/bot/services/`: Telegram-specific services (message builders, UI components)
- `app/bot/routers/`: Telegram handler organization by feature area

### Database Structure
- **PostgreSQL** with SQLAlchemy ORM
- **Main entities**: `Order` (with status tracking), `OrderStatusHistory`
- **Migrations**: Alembic-managed, located in `alembic/versions/`
- **Key features**: JSONB storage for raw Shopify data, timezone-aware timestamps

### Telegram Bot Architecture
**Router Structure** (registration order matters for handlers):
1. `management.py` - FSM states for comments/reminders (highest priority)
2. `orders.py` - Order-specific actions (status changes, file generation)  
3. `navigation.py` - General list navigation
4. `commands.py` - Basic commands
5. `webhook.py` - Webhook-only close buttons (lowest priority)

**Scheduler System**:
- Hourly NEW order reminders (10:00-22:00 Kyiv time)
- Daily payment reminders (10:30 Kyiv time)
- Individual reminder system (every 5 minutes)

### Configuration
- **Environment**: Variables in `.env` (see `.env.example` for template)
- **Docker**: Multi-service setup with PostgreSQL container
- **Timezone**: Europe/Kyiv (handles Ukraine timezone changes)
- **Localization**: Ukrainian language for user-facing content

### Security Features
- **HMAC validation** for Shopify webhooks
- **Telegram user whitelist** via `TELEGRAM_ALLOWED_USER_IDS`
- **No file persistence** - PDFs/VCFs generated on-demand and not stored
- **Environment-based secrets** management

## Development Notes

### Phone Number Handling
The application includes specialized Ukrainian phone number normalization in `app/services/phone_utils.py` that handles various input formats and converts them to E.164 format (`+380XXXXXXXXX`).

### Address Logic
The system implements sophisticated address handling to determine the correct contact person when billing and shipping addresses differ - see `get_delivery_and_contact_info()` in `app/services/address_utils.py`.

### Idempotency
Webhook processing includes idempotency checking via `app/state.py` to prevent duplicate order processing using in-memory tracking.

### Message Templates
Telegram messages use structured templates with emojis and formatting defined in `app/bot/services/message_builder.py`. Status changes are tracked with visual indicators.

### Testing Structure
Tests are organized both in a dedicated `tests/` directory and as standalone test files in the project root, focusing on specific functionality areas like address logic, phone utilities, and webhook handling.