import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from telebot.types import CallbackQuery, Message


class UserFlowsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        path = Path(__file__).resolve().parents[1] / 'bot.py'
        # The checkout lacks the business-command implementation.
        commands = ModuleType('commands')
        commands.process_command = AsyncMock()
        cwd = os.getcwd()
        try:
            os.chdir(self.directory.name)
            spec = importlib.util.spec_from_file_location('bot_under_test', path)
            self.app = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {'commands': commands}):
                spec.loader.exec_module(self.app)
        finally:
            os.chdir(cwd)
        # Every database operation stays in the disposable fixture directory.
        connect = self.app.sqlite3.connect
        self.db_patch = patch.object(
            self.app.sqlite3, 'connect',
            side_effect=lambda _: connect(str(Path(self.directory.name) / 'bot_data.db')),
        )
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.bot = self.app.bot
        for name in ('send_message', 'send_photo', 'answer_callback_query', 'delete_message'):
            setattr(self.bot, name, AsyncMock())
        self.bot.get_me = AsyncMock(return_value=SimpleNamespace(username='fixture_bot'))
        self.user = self.app.ADMIN_IDS[0]

    def message(self, text, user=None):
        user = user or self.user
        return Message.de_json({
            'message_id': 1, 'date': 1,
            'chat': {'id': user, 'type': 'private'},
            'from': {'id': user, 'is_bot': False, 'first_name': 'Person'},
            'text': text,
            'entities': [{'type': 'bot_command', 'offset': 0, 'length': len(text.split()[0])}]
            if text.startswith('/') else [],
        })

    async def dispatch(self, message):
        for handler in self.bot.message_handlers:
            if await self.bot._test_message_handler(handler, message):
                await handler['function'](message)
                return

    async def test_ad_skip_is_dispatched_and_saves_without_url(self):
        self.app.set_state(self.user, 'waiting_ad_text')
        await self.dispatch(self.message('An ad'))
        self.assertEqual(self.app.get_state(self.user), 'waiting_ad_url')
        await self.dispatch(self.message('/skip'))
        ads = self.app.get_all_ads()
        self.assertEqual([(text, url) for _, text, url in ads], [('An ad', None)])
        self.assertIsNone(self.app.get_state(self.user))
        self.assertNotIn(self.user, self.app.user_giveaway_data)

    async def test_skip_with_bot_suffix_saves_without_url(self):
        self.app.set_state(self.user, 'waiting_ad_text')
        await self.dispatch(self.message('An ad'))
        await self.dispatch(self.message('/skip@fixture_bot'))
        self.assertEqual(self.app.get_all_ads()[0][1:], ('An ad', None))

    async def test_cancel_discards_each_ad_step(self):
        for state in ('waiting_ad_text', 'waiting_ad_url'):
            with self.subTest(state=state):
                self.app.set_state(self.user, state)
                self.app.user_giveaway_data[self.user] = {'ad_text': 'Draft'}
                await self.dispatch(self.message('/cancel'))
                self.assertIsNone(self.app.get_state(self.user))
                self.assertNotIn(self.user, self.app.user_giveaway_data)
                self.assertEqual(self.app.get_all_ads(), [])

    async def test_regular_url_still_saves(self):
        self.app.set_state(self.user, 'waiting_ad_text')
        await self.dispatch(self.message('An ad'))
        await self.dispatch(self.message('https://example.com'))
        self.assertEqual(self.app.get_all_ads()[0][1:], ('An ad', 'https://example.com'))

    async def test_non_admin_cannot_cancel_admin_draft(self):
        self.app.set_state(self.user, 'waiting_ad_url')
        await self.dispatch(self.message('/cancel', user=42))
        self.assertEqual(self.app.get_state(self.user), 'waiting_ad_url')
        self.bot.send_message.assert_not_awaited()

    async def test_skip_outside_url_step_does_not_change_state(self):
        self.app.set_state(self.user, 'waiting_ad_text')
        await self.dispatch(self.message('/skip'))
        self.assertEqual(self.app.get_state(self.user), 'waiting_ad_text')
        self.assertEqual(self.app.get_all_ads(), [])

    async def test_start_shows_gate_then_welcome(self):
        self.app.set_setting('required_channel', '@fixture_channel')
        self.app.is_subscribed = AsyncMock(return_value=False)
        await self.dispatch(self.message('/start', user=42))
        self.assertIn('подпишитесь', self.bot.send_message.call_args.args[1])
        self.app.is_subscribed.return_value = True
        await self.dispatch(self.message('/start', user=42))
        self.assertIn('Добро пожаловать', self.bot.send_message.call_args.args[1])
        self.assertEqual(self.app.get_all_users(), [42])

    async def subscription(self, subscribed):
        user = 42
        self.app.update_user(user, 'Person', 'person')
        self.app.set_setting('required_channel', '@fixture_channel')
        call = CallbackQuery.de_json({
            'id': 'query', 'chat_instance': 'fixture', 'data': 'check_subscription',
            'from': {'id': user, 'is_bot': False, 'first_name': 'Person'},
            'message': {'message_id': 2, 'date': 1,
                        'chat': {'id': user, 'type': 'private'},
                        'from': {'id': 999, 'is_bot': True, 'first_name': 'Bot'},
                        'text': 'Subscribe'},
        })
        self.app.is_subscribed = AsyncMock(return_value=subscribed)
        await self.app.check_subscription_callback(call)
        return user

    async def test_subscription_success_keeps_human_identity(self):
        user = await self.subscription(True)
        self.assertEqual(self.app.get_all_users(), [user])
        self.app.is_subscribed.assert_awaited_once_with(user, '@fixture_channel')
        self.bot.send_message.assert_awaited_once()
        self.assertIn('Добро пожаловать', self.bot.send_message.call_args.args[1])
        self.bot.answer_callback_query.assert_awaited_once()

    async def test_subscription_still_opens_when_prompt_cannot_be_deleted(self):
        self.bot.delete_message.side_effect = RuntimeError('Fixture deletion failure')
        await self.subscription(True)
        self.bot.send_message.assert_awaited_once()
        self.bot.answer_callback_query.assert_awaited_once()

    async def test_subscription_failure_keeps_prompt(self):
        await self.subscription(False)
        self.bot.send_message.assert_not_awaited()
        self.bot.delete_message.assert_not_awaited()
        self.bot.answer_callback_query.assert_awaited_once_with(
            'query', '❌ Вы ещё не подписаны', show_alert=True,
        )


if __name__ == '__main__':
    unittest.main()
