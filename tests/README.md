# Focused bot tests

Run with the project dependencies installed:

```sh
.venv/bin/python -m unittest discover -v
```

The suite uses the standard library's `unittest` and `IsolatedAsyncioTestCase`.
Every test imports the bot in a fresh temporary working directory, so database
initialization and media writes never touch the checked-in `bot_data.db`.
Telegram calls are mocked, and the client is constructed with a dummy token.
No Telegram credentials or network access are needed.

Coverage focuses on archival and recovery after media failures, chat-scoped
edits/deletions, notification subscription gates, admin authorization, retention
cleanup, and startup polling. The missing `commands.py` extension is stubbed during import;
command processing and live Telegram integration are not covered.
