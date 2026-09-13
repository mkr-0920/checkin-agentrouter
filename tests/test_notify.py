import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import dotenv
import httpx
import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.notify import TELEGRAM_TEXT_LIMIT, NotificationKit, format_telegram_message


@pytest.fixture
def notification_kit(monkeypatch):
	monkeypatch.setenv('FEISHU_WEBHOOK', 'https://open.feishu.cn/open-apis/bot/v2/hook/test-token')
	monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
	monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
	monkeypatch.delenv('CHECKIN_PROXY_URL', raising=False)
	return NotificationKit()


@pytest.fixture
def telegram_kit(monkeypatch):
	monkeypatch.delenv('FEISHU_WEBHOOK', raising=False)
	monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123456:test-token')
	monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001234567890')
	monkeypatch.delenv('CHECKIN_PROXY_URL', raising=False)
	return NotificationKit()


@pytest.fixture
def mock_httpx_client():
	with patch('httpx.Client') as mock_client_class:
		mock_response = MagicMock()
		mock_response.status_code = 200
		mock_response.json.return_value = {'code': 0}
		mock_client = MagicMock()
		mock_client.post.return_value = mock_response
		mock_client_class.return_value.__enter__.return_value = mock_client
		yield mock_client, mock_response


@pytest.fixture
def mock_httpx_client_class():
	with patch('httpx.Client') as mock_client_class:
		mock_response = MagicMock()
		mock_response.status_code = 200
		mock_response.json.return_value = {'ok': True}
		mock_client_class.return_value.__enter__.return_value.post.return_value = mock_response
		yield mock_client_class


def test_send_feishu(mock_httpx_client, notification_kit):
	mock_client, _ = mock_httpx_client

	notification_kit.send_feishu('测试标题', '测试内容')

	mock_client.post.assert_called_once()
	args = mock_client.post.call_args[0]
	kwargs = mock_client.post.call_args[1]
	assert args == ('https://open.feishu.cn/open-apis/bot/v2/hook/test-token',)
	assert kwargs['json']['msg_type'] == 'interactive'
	assert kwargs['json']['card']['header']['title']['content'] == '测试标题'
	assert kwargs['json']['card']['elements'][0]['content'] == '测试内容'


def test_http_response_error(notification_kit):
	response = httpx.Response(500, text='server error')

	with patch('httpx.Client') as mock_client_class:
		mock_client = MagicMock()
		mock_client.post.return_value = response
		mock_client_class.return_value.__enter__.return_value = mock_client

		with pytest.raises(RuntimeError, match='Feishu request failed: HTTP 500'):
			notification_kit.send_feishu('测试', '测试')


def test_http_json_error(notification_kit):
	response = httpx.Response(200, json={'errcode': 40001, 'errmsg': 'invalid token'})

	with patch('httpx.Client') as mock_client_class:
		mock_client = MagicMock()
		mock_client.post.return_value = response
		mock_client_class.return_value.__enter__.return_value = mock_client

		with pytest.raises(RuntimeError, match='Feishu request failed: invalid token'):
			notification_kit.send_feishu('测试', '测试')


def test_missing_feishu_config(monkeypatch):
	monkeypatch.delenv('FEISHU_WEBHOOK', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='FEISHU_WEBHOOK not configured'):
		kit.send_feishu('测试', '测试')


def test_push_message_uses_feishu(notification_kit, monkeypatch):
	send_feishu = MagicMock()
	send_telegram = MagicMock()
	monkeypatch.setattr(notification_kit, 'send_feishu', send_feishu)
	monkeypatch.setattr(notification_kit, 'send_telegram', send_telegram)

	notification_kit.push_message('测试标题', '测试内容')

	send_feishu.assert_called_once_with('测试标题', '测试内容')
	send_telegram.assert_not_called()


def test_send_telegram(mock_httpx_client, telegram_kit):
	mock_client, _ = mock_httpx_client

	telegram_kit.send_telegram('测试标题', '测试内容')

	mock_client.post.assert_called_once()
	args = mock_client.post.call_args[0]
	kwargs = mock_client.post.call_args[1]
	assert args == ('https://api.telegram.org/bot123456:test-token/sendMessage',)
	assert kwargs['json']['chat_id'] == '-1001234567890'
	assert kwargs['json']['parse_mode'] == 'HTML'
	assert kwargs['json']['text'] == '<b>测试标题</b>\n\n测试内容'


def test_send_telegram_renders_code_block_as_pre(mock_httpx_client, telegram_kit):
	mock_client, _ = mock_httpx_client

	telegram_kit.send_telegram('测试标题', '余额：\n```text\n✅ main  $6.80\n```')

	text = mock_client.post.call_args[1]['json']['text']
	assert '<pre>✅ main  $6.80</pre>' in text
	assert '```' not in text


def test_send_telegram_escapes_html(mock_httpx_client, telegram_kit):
	mock_client, _ = mock_httpx_client

	telegram_kit.send_telegram('测试标题', 'a < b & c > d')

	text = mock_client.post.call_args[1]['json']['text']
	assert 'a &lt; b &amp; c &gt; d' in text


def test_send_telegram_uses_checkin_proxy(mock_httpx_client_class, telegram_kit, monkeypatch, capsys):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	telegram_kit.send_telegram('测试标题', '测试内容')

	assert mock_httpx_client_class.call_args[1]['proxy'] == 'http://127.0.0.1:7890'
	assert 'Notification proxy enabled: http://127.0.0.1:7890' in capsys.readouterr().out


def test_send_telegram_without_proxy(mock_httpx_client_class, telegram_kit, capsys):
	telegram_kit.send_telegram('测试标题', '测试内容')

	assert mock_httpx_client_class.call_args[1]['proxy'] is None
	assert 'CHECKIN_PROXY_URL not set' in capsys.readouterr().out


def test_send_feishu_does_not_use_proxy(mock_httpx_client_class, notification_kit, monkeypatch):
	monkeypatch.setenv('CHECKIN_PROXY_URL', 'http://127.0.0.1:7890')

	notification_kit.send_feishu('测试标题', '测试内容')

	assert mock_httpx_client_class.call_args[1]['proxy'] is None


def test_send_telegram_reports_api_error(telegram_kit):
	response = httpx.Response(200, json={'ok': False, 'error_code': 400, 'description': 'chat not found'})

	with patch('httpx.Client') as mock_client_class:
		mock_client = MagicMock()
		mock_client.post.return_value = response
		mock_client_class.return_value.__enter__.return_value = mock_client

		with pytest.raises(RuntimeError, match='Telegram request failed: chat not found'):
			telegram_kit.send_telegram('测试', '测试')


def test_http_error_keeps_api_description(telegram_kit):
	response = httpx.Response(401, json={'ok': False, 'error_code': 401, 'description': 'Unauthorized'})

	with patch('httpx.Client') as mock_client_class:
		mock_client = MagicMock()
		mock_client.post.return_value = response
		mock_client_class.return_value.__enter__.return_value = mock_client

		with pytest.raises(RuntimeError, match='Telegram request failed: HTTP 401: Unauthorized'):
			telegram_kit.send_telegram('测试', '测试')


def test_missing_telegram_config(monkeypatch):
	monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
	monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
	kit = NotificationKit()

	with pytest.raises(ValueError, match='TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID not configured'):
		kit.send_telegram('测试', '测试')


def test_format_telegram_message_keeps_short_content():
	assert format_telegram_message('标题', '内容') == '<b>标题</b>\n\n内容'


def test_format_telegram_message_truncates_long_content():
	text = format_telegram_message('标题', '```text\n' + 'x' * 5000 + '\n```')

	assert len(text) <= TELEGRAM_TEXT_LIMIT
	assert text.endswith('…</pre>')


def test_push_message_sends_to_every_configured_channel(monkeypatch):
	monkeypatch.setenv('FEISHU_WEBHOOK', 'https://example.com/feishu')
	monkeypatch.setenv('TELEGRAM_BOT_TOKEN', '123456:test-token')
	monkeypatch.setenv('TELEGRAM_CHAT_ID', '-1001234567890')
	kit = NotificationKit()
	send_feishu = MagicMock()
	send_telegram = MagicMock()
	monkeypatch.setattr(kit, 'send_feishu', send_feishu)
	monkeypatch.setattr(kit, 'send_telegram', send_telegram)

	kit.push_message('测试标题', '测试内容')

	send_feishu.assert_called_once_with('测试标题', '测试内容')
	send_telegram.assert_called_once_with('测试标题', '测试内容')


def test_push_message_keeps_other_channel_when_one_fails(telegram_kit, monkeypatch):
	send_feishu = MagicMock(side_effect=RuntimeError('Feishu request failed: HTTP 500'))
	send_telegram = MagicMock()
	monkeypatch.setattr(telegram_kit, 'feishu_webhook', 'https://example.com/feishu')
	monkeypatch.setattr(telegram_kit, 'send_feishu', send_feishu)
	monkeypatch.setattr(telegram_kit, 'send_telegram', send_telegram)

	telegram_kit.push_message('测试标题', '测试内容')

	send_telegram.assert_called_once_with('测试标题', '测试内容')


def test_push_message_without_channel_config(monkeypatch, capsys):
	monkeypatch.delenv('FEISHU_WEBHOOK', raising=False)
	monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
	monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)
	kit = NotificationKit()

	kit.push_message('测试标题', '测试内容')

	assert 'No notification channel configured' in capsys.readouterr().out


def test_checkin_loads_dotenv_before_notification_singleton(tmp_path, monkeypatch):
	env_file = tmp_path / '.env'
	env_file.write_text(
		'FEISHU_WEBHOOK=https://example.com/feishu\n'
		'TELEGRAM_BOT_TOKEN=123456:test-token\n'
		'TELEGRAM_CHAT_ID=-1001234567890\n',
		encoding='utf-8',
	)
	monkeypatch.delenv('FEISHU_WEBHOOK', raising=False)
	monkeypatch.delenv('TELEGRAM_BOT_TOKEN', raising=False)
	monkeypatch.delenv('TELEGRAM_CHAT_ID', raising=False)

	# checkin.py 的 load_dotenv() 按调用文件所在目录定位 .env，这里让它读取临时配置文件
	real_load_dotenv = dotenv.load_dotenv
	monkeypatch.setattr(dotenv, 'load_dotenv', lambda *args, **kwargs: real_load_dotenv(env_file))

	for module_name in ['checkin', 'utils.notify']:
		sys.modules.pop(module_name, None)

	checkin = importlib.import_module('checkin')

	assert checkin.notify.feishu_webhook == 'https://example.com/feishu'
	assert checkin.notify.telegram_bot_token == '123456:test-token'
	assert checkin.notify.telegram_chat_id == '-1001234567890'
