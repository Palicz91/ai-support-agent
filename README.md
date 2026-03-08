# Supabase Support Agent

An AI-powered Telegram bot that answers support questions by querying your Supabase database. Built with Gemini AI, FastAPI, and Supabase.

**Built by [SpiniX](https://spinix.so)** — originally created to handle internal customer support for a gamified restaurant retention platform.

## What it does

Your team asks a question in Telegram → the bot queries your database → Gemini AI interprets the results → sends back a clear answer.

```
You: "What's going on with Acme Corp's account?"
Bot: "Acme Corp is an active customer since Jan 2025. They have 2 projects,
     340 transactions in the last 30 days. Their subscription is active
     (Pro plan, renews March 15)."
```

**Features:**
- Natural language queries against your Supabase database
- Image/screenshot support (send a screenshot, bot analyzes it)
- Predefined query tools + dynamic SQL fallback (read-only)
- Conversation memory (30-min sliding window)
- Auto-escalation to a Telegram channel when confidence is low
- Full interaction logging for prompt iteration
- Error code lookup table

## Architecture

```
Telegram Bot → FastAPI (Cloud Run) → Gemini AI → Supabase (read-only)
                                         ↓
                                   Function Calling
                                   (predefined queries +
                                    dynamic SQL fallback)
```

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/supabase-support-agent.git
cd supabase-support-agent
cp .env.example .env
# Edit .env with your credentials
```

### 2. Run the SQL migrations

Run these in your Supabase SQL Editor:

```bash
# Creates: agent_logs, chat_history, error_codes tables
001_support_agent_tables.sql

# Creates: run_readonly_query() function for dynamic SQL
002_dynamic_query_function.sql
```

### 3. Configure your schema

Edit `gemini_service.py`:
- Update `SYSTEM_PROMPT` with your database schema
- Update `TOOL_DECLARATIONS` with your query tools

Edit `database.py`:
- Replace the example queries with ones that match your tables

### 4. Create a Telegram bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot`, follow the prompts
3. Save the bot token

### 5. Get a Gemini API key

Go to [Google AI Studio](https://aistudio.google.com/apikey) and create an API key.

### 6. Deploy to Cloud Run

```bash
# Enable APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com

# Deploy
gcloud run deploy support-agent \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --min-instances 0 \
  --max-instances 3

# Set env vars
gcloud run services update support-agent \
  --region us-central1 \
  --update-env-vars "TELEGRAM_BOT_TOKEN=xxx,GEMINI_API_KEY=xxx,SUPABASE_URL=xxx,SUPABASE_SERVICE_KEY=xxx"

# Set webhook
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://your-cloud-run-url.run.app/webhook"}'
```

### 7. Test

Message your bot on Telegram. Send `/start` to see the welcome message.

## Project structure

```
├── main.py                         # FastAPI app, Telegram webhook, image handling
├── database.py                     # Supabase queries, chat history, logging
├── gemini_service.py               # Gemini AI, function calling, system prompt
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Cloud Run container
├── .env.example                    # Environment variables template
├── 001_support_agent_tables.sql    # DB migration: agent tables
└── 002_dynamic_query_function.sql  # DB migration: dynamic query function
```

## How to customize for your app

### 1. Define your queries (database.py)

Each query is an async method that returns a dict. Example:

```python
async def lookup_customer(self, search_term: str) -> dict:
    result = self.client.table("customers").select(
        "id, name, email, plan, created_at"
    ).or_(
        f"name.ilike.%{search_term}%,"
        f"email.ilike.%{search_term}%"
    ).execute()
    return {"query": "lookup_customer", "results": result.data}
```

### 2. Register tools (gemini_service.py)

Add a tool declaration so Gemini knows when to call your query:

```python
{"name": "lookup_customer", "description": "Search for a customer by name or email.", "parameters": {"type": "object", "properties": {"search_term": {"type": "string", "description": "Customer name or email"}}, "required": ["search_term"]}},
```

And add it to the `func_map` in `_execute_function_call`.

### 3. Write the system prompt (gemini_service.py)

Tell the AI about your database schema, key relationships, and how to investigate issues. The more specific you are, the better the answers.

### 4. Populate error codes (optional)

Insert rows into the `error_codes` table so the bot can look up error messages:

```sql
INSERT INTO error_codes (code, component, source, trigger_condition, user_message, internal_description, severity, suggested_fix)
VALUES ('ERR_AUTH_001', 'LoginForm', 'frontend', 'Invalid credentials', 'Login failed', 'User entered wrong password 3+ times', 'medium', 'Reset password via dashboard');
```

## Dynamic SQL fallback

If none of the predefined tools can answer a question, the bot generates a read-only `SELECT` query. Safety measures:

- Only `SELECT` statements allowed
- Mutation keywords blocked (INSERT, UPDATE, DELETE, DROP, etc.)
- SQL comments blocked
- Sensitive columns blocked (access_token, refresh_token, etc.)
- Runs via a Postgres function with `SECURITY DEFINER` (revoked from anon/authenticated roles)

## Environment variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_ESCALATION_CHAT_ID` | Chat ID for escalation messages (optional) |
| `GEMINI_API_KEY` | Google AI API key |
| `SUPABASE_URL` | Supabase project URL (https://xxx.supabase.co) |
| `SUPABASE_SERVICE_KEY` | Supabase service_role key |

## Cost

With Google Cloud credits: **$0/month**. Without credits:
- Cloud Run: ~$0 (free tier covers low traffic)
- Gemini 2.5 Flash: ~$0.01 per support query
- Gemini 2.5 Pro: ~$0.10 per support query (better reasoning)
- Supabase: existing plan

## License

MIT
