import importlib.util
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from telebot.async_telebot import AsyncTeleBot


SOURCE = Path(__file__).resolve().parents[1] / "bot.py"


class BotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        original_cwd = Path.cwd()
        os.chdir(self.temp.name)
        self.addCleanup(os.chdir, original_cwd)

        # The command extension is absent from this checkout; it is not under test.
        commands = ModuleType("commands")
        commands.process_command = AsyncMock()
        spec = importlib.util.spec_from_file_location("bot_under_test", SOURCE)
        self.app = importlib.util.module_from_spec(spec)
        client = AsyncTeleBot("123456:TEST")
        with patch.dict(sys.modules, {"commands": commands}), patch(
            "telebot.async_telebot.AsyncTeleBot", return_value=client
        ):
            spec.loader.exec_module(self.app)
        self.app.bot = MagicMock(spec=AsyncTeleBot)
        self.app.bot.get_business_connection.return_value = SimpleNamespace(user_chat_id=100)
        self.app.ADMIN_IDS = [100]

    def save(self, message_id=1, chat_id=200, user_id=300, **kwargs):
        self.app.save_msg(
            chat_id, message_id, user_id, "Sender <&>",
            kwargs.pop("content_type", "text"), kwargs.pop("content", "original"),
            **kwargs,
        )

    def row(self, message_id=1, chat_id=200):
        with sqlite3.connect("bot_data.db") as conn:
            return conn.execute(
                "SELECT content, edited_at, deleted_at FROM messages "
                "WHERE chat_id=? AND message_id=?", (chat_id, message_id)
            ).fetchone()

    def event(self, **kwargs):
        return SimpleNamespace(
            business_connection_id="connection", chat=SimpleNamespace(id=200), **kwargs
        )

    async def test_photo_download_failure_still_archives_recoverable_file_id(self):
        msg = self.event(
            message_id=1, text=None, caption="caption", content_type="photo",
            from_user=SimpleNamespace(id=300, first_name="Sender", username="sender"),
            photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large")],
            reply_to_message=None,
        )
        with patch.object(self.app, "download_media", AsyncMock(side_effect=OSError("offline"))) as download:
            await self.app.handle_message(msg)
        download.assert_awaited_once_with("large", "jpg")
        self.assertEqual(
            self.app.get_msg(200, 1),
            (300, "Sender", "photo", "caption", "large", "caption", None),
        )
        self.assertEqual(self.app.get_all_users(), [300])

    async def test_edit_is_chat_scoped_and_preserves_archive_when_notifications_blocked(self):
        self.save()
        self.save(chat_id=201)
        with patch.object(self.app, "send_reminder_if_unsubscribed", AsyncMock(return_value=False)):
            await self.app.handle_edit(self.event(message_id=1, text="updated"))
        self.assertEqual(self.row()[0], "updated")
        self.assertIsNotNone(self.row()[1])
        self.assertEqual(self.row(chat_id=201), ("original", None, None))
        self.app.bot.send_message.assert_not_awaited()

    async def test_edit_of_owners_message_updates_archive_without_notifying(self):
        self.save(user_id=100)
        await self.app.handle_edit(self.event(message_id=1, text="updated"))
        self.assertEqual(self.row()[0], "updated")
        self.app.bot.send_message.assert_not_awaited()

    async def test_missing_and_unchanged_edits_have_no_side_effects(self):
        self.save()
        await self.app.handle_edit(self.event(message_id=999, text="updated"))
        await self.app.handle_edit(self.event(message_id=1, text="original"))
        self.assertEqual(self.row(), ("original", None, None))
        self.app.bot.send_message.assert_not_awaited()

    async def test_deleted_text_notifies_owner_with_escaped_content_and_marks_only_its_chat(self):
        self.app.update_user(100, "Owner", "owner")
        self.save(content="<script>&")
        self.save(chat_id=201)
        await self.app.handle_delete(self.event(message_ids=[999, 1]))
        self.assertIsNotNone(self.row()[2])
        self.assertEqual(self.row(chat_id=201), ("original", None, None))
        self.app.bot.send_message.assert_awaited_once()
        args = self.app.bot.send_message.await_args.args
        self.assertEqual(args[0], 100)
        self.assertIn("&lt;script&gt;&amp;", args[1])
        self.assertIn("Sender &lt;&amp;&gt;", args[1])
        self.assertNotIn("<script>", args[1])

    async def test_deleted_photo_prefers_saved_bytes_over_telegram_file_id(self):
        photo = Path("saved_media/photo.jpg")
        photo.write_bytes(b"saved photo")
        self.save(content_type="photo", file_id="remote", local_path=str(photo), caption="<caption>")
        sent = []

        async def capture(owner_id, media, **kwargs):
            sent.append((owner_id, media.read(), kwargs))

        self.app.bot.send_photo.side_effect = capture
        await self.app.handle_delete(self.event(message_ids=[1]))
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][:2], (100, b"saved photo"))
        self.assertIn("&lt;caption&gt;", sent[0][2]["caption"])
        self.assertIsNotNone(self.row()[2])
        self.assertTrue(photo.exists())

    async def test_deleted_photo_falls_back_to_file_id_when_local_file_is_missing(self):
        self.save(content_type="photo", file_id="remote", local_path="missing.jpg")
        await self.app.handle_delete(self.event(message_ids=[1]))
        self.app.bot.send_photo.assert_awaited_once()
        self.assertEqual(self.app.bot.send_photo.await_args.args, (100, "remote"))
        self.assertIsNotNone(self.row()[2])

    async def test_deleted_messages_are_marked_without_sending_when_subscription_blocks(self):
        self.save(content_type="photo", file_id="remote")
        with patch.object(self.app, "send_reminder_if_unsubscribed", AsyncMock(return_value=False)):
            await self.app.handle_delete(self.event(message_ids=[1]))
        self.assertIsNotNone(self.row()[2])
        self.app.bot.send_photo.assert_not_awaited()
        self.app.bot.send_message.assert_not_awaited()

    async def test_safe_send_rejects_users_who_have_not_started_bot(self):
        result = await self.app.safe_send_message(300, "notification")
        self.assertIsNone(result)
        self.app.bot.send_message.assert_not_awaited()
        self.app.bot.get_chat_member.assert_not_awaited()

    async def test_subscription_api_failure_fails_closed_and_throttles_reminders(self):
        self.app.update_user(300, "Sender", "sender")
        self.app.set_setting("required_channel", "@required")
        self.app.bot.get_chat_member.side_effect = RuntimeError("offline")
        with patch.object(self.app.time, "time", return_value=10000):
            for _ in range(2):
                self.assertIsNone(await self.app.safe_send_message(300, "private notification"))
        self.assertEqual(self.app.bot.get_chat_member.await_count, 2)
        self.app.bot.get_chat_member.assert_awaited_with("@required", 300)
        self.app.bot.send_message.assert_awaited_once()
        self.assertNotIn("private notification", self.app.bot.send_message.await_args.args[1])

    async def test_safe_send_allows_subscribed_user_and_preserves_options_and_result(self):
        self.app.update_user(300, "Sender", "sender")
        self.app.set_setting("required_channel", "required")
        self.app.bot.get_chat_member.return_value = SimpleNamespace(status="member")
        result = await self.app.safe_send_message(300, "notification", disable_notification=True)
        self.assertIs(result, self.app.bot.send_message.return_value)
        self.app.bot.send_message.assert_awaited_once_with(
            300, "notification", parse_mode="HTML", disable_notification=True
        )

    async def test_safe_send_only_swallows_cannot_initiate_conversation_error(self):
        self.app.update_user(300, "Sender", "sender")
        self.app.bot.send_message.side_effect = RuntimeError("can't initiate conversation")
        self.assertIsNone(await self.app.safe_send_message(300, "notification"))
        self.app.bot.send_message.side_effect = RuntimeError("rate limited")
        with self.assertRaisesRegex(RuntimeError, "rate limited"):
            await self.app.safe_send_message(300, "notification")

    async def test_unauthorized_admin_cannot_clear_messages_or_change_settings(self):
        self.save()
        self.app.set_state(300, "waiting_welcome_text")
        msg = SimpleNamespace(from_user=SimpleNamespace(id=300), text="replacement")
        await self.app.confirm_clear(msg)
        await self.app.handle_admin_input(msg)
        self.assertEqual(self.row(), ("original", None, None))
        self.assertEqual(self.app.get_setting("welcome_text"), "")
        self.app.bot.reply_to.assert_not_awaited()
        self.app.bot.send_message.assert_not_awaited()

    async def test_forged_admin_callback_is_rejected_before_action(self):
        call = SimpleNamespace(id="callback", data="admin_broadcast", from_user=SimpleNamespace(id=300))
        await self.app.admin_callback(call)
        self.app.bot.answer_callback_query.assert_awaited_once_with("callback", "Нет доступа", show_alert=True)
        self.assertIsNone(self.app.get_state(300))
        self.app.bot.edit_message_text.assert_not_awaited()

    async def test_authorized_clear_deletes_messages_but_preserves_users_and_settings(self):
        self.save()
        self.app.update_user(300, "Sender", "sender")
        self.app.set_setting("welcome_text", "configured")
        await self.app.confirm_clear(SimpleNamespace(from_user=SimpleNamespace(id=100)))
        self.assertIsNone(self.row())
        self.assertEqual(self.app.get_all_users(), [300])
        self.assertEqual(self.app.get_setting("welcome_text"), "configured")
        self.app.bot.reply_to.assert_awaited_once()

    async def test_startup_schedules_cleanup_and_polls_business_updates(self):
        with patch.object(self.app, "cleanup_old_files", AsyncMock()) as cleanup:
            await self.app.main()
            # Let the scheduled cleanup coroutine finish before loop teardown.
            import asyncio
            await asyncio.sleep(0)
        cleanup.assert_awaited_once()
        self.app.bot.infinity_polling.assert_awaited_once_with(allowed_updates=[
            "business_message", "edited_business_message", "deleted_business_messages",
            "message", "callback_query",
        ])


if __name__ == "__main__":
    unittest.main()
