"""Exercise POST framing through the real handler without binding a host network port."""
from email.message import Message
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/onecloud'))
from settings_page import MAX_BODY, SettingsPage


class PostFramingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        state = Path(tmp.name) / 'state'; state.mkdir()
        self.page = SettingsPage(state, lambda: {}, lambda _: None, lambda: [])
        self.page.apply = Mock(return_value='saved')
        with patch('settings_page.ThreadingHTTPServer') as server, patch('settings_page.threading.Thread'):
            self.page.start(0)
        self.handler_class = server.call_args.args[1]

    def request(self, length='0', body=b'', transfer=None, path='/pair'):
        handler = self.handler_class.__new__(self.handler_class)
        handler.headers = Message()
        for value in length if isinstance(length, list) else [length]:
            handler.headers.add_header('Content-Length', value)
        if transfer:
            handler.headers.add_header('Transfer-Encoding', transfer)
        handler.path = path
        handler._allowed = lambda: True
        handler._send = Mock()
        handler.rfile = Mock(wraps=io.BytesIO(body))
        handler.do_POST()
        return handler

    def test_negative_nonnumeric_duplicate_and_chunked_lengths_are_rejected_before_read(self):
        for value, transfer in [('-1', None), ('abc', None), (['1', '2'], None), ('0', 'chunked')]:
            with self.subTest(value=value, transfer=transfer):
                handler = self.request(value, transfer=transfer)
                self.assertEqual(handler._send.call_args.args[0], 400)
                handler.rfile.read.assert_not_called()
        self.page.apply.assert_not_called()

    def test_oversized_and_incomplete_bodies_are_rejected(self):
        handler = self.request(str(MAX_BODY + 1))
        self.assertEqual(handler._send.call_args.args[0], 413)
        handler.rfile.read.assert_not_called()
        handler = self.request('10', b'bad')
        self.assertEqual(handler._send.call_args.args[0], 400)
        self.page.apply.assert_not_called()

    def test_valid_form_reaches_the_nonce_check_and_normal_action_route(self):
        body = b'nonce=test&action=stop'
        handler = self.request(str(len(body)), body)
        self.page.apply.assert_called_once_with('/pair', {'nonce': 'test', 'action': 'stop'})
        self.assertEqual(handler._send.call_args.args[0], 303)
        self.assertEqual(handler.timeout, 10)

    def test_invalid_utf8_does_not_execute_an_action(self):
        handler = self.request('1', b'\xff')
        self.assertEqual(handler._send.call_args.args[0], 400)
        self.page.apply.assert_not_called()


class WhereAResultGoesTests(unittest.TestCase):
    """1.6.0: what the reset could not do comes back over the reset page, where the words were typed; everything else
    goes to the page, an update's to its category."""

    def setUp(self):
        PostFramingTests.setUp(self)

    request = PostFramingTests.request

    def location(self, path, result):
        self.page.apply = Mock(side_effect=result) if isinstance(result, Exception) else Mock(return_value=result)
        handler = self.request('7', b'nonce=x', path=path)
        self.assertEqual(handler._send.call_args.args[0], 303)
        return handler._send.call_args.kwargs['extra']['Location']

    def test_the_reset_s_error_returns_to_the_reset_page(self):
        import urllib.parse
        where = self.location('/reset', ValueError('确认词不正确：请输入「重置」。'))
        self.assertTrue(where.startswith('/reset?m='), where)
        self.assertEqual(urllib.parse.parse_qs(where.partition('?')[2])['m'], ['错误：确认词不正确：请输入「重置」。'])
        self.assertTrue(self.location('/reset', '已恢复出厂设置：盒子正在重新启动，之后请重新添加 iPhone。').startswith('/?m='))
        self.assertTrue(self.location('/pair', ValueError('无法添加 iPhone：CarPlay 正在使用中，请先断开。')).startswith('/?m='))
        self.assertTrue(self.location('/update', ValueError('页面已过期：请再试一次。')).endswith('#update'))
