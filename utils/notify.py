import os
import re
from html import escape as escape_html
from typing import Any, Callable, Literal

import httpx

from utils.proxy import get_proxy_server

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CODE_FENCE = re.compile(r'```[^\n]*\n(.*?)```', re.DOTALL)


def format_telegram_message(title: str, content: str) -> str:
	"""把通知文本转成 Telegram HTML，代码块使用等宽字体。"""
	text = escape_html(content)
	text = TELEGRAM_CODE_FENCE.sub(lambda match: f'<pre>{match.group(1).rstrip()}</pre>', text)
	if title:
		text = f'<b>{escape_html(title)}</b>\n\n{text}'
	return _truncate_html(text, TELEGRAM_TEXT_LIMIT)


def _truncate_html(text: str, limit: int) -> str:
	"""按长度截断 HTML，避免留下未闭合的标签或转义字符。"""
	if len(text) <= limit:
		return text

	truncated = text[: limit - 16]  # 预留省略号和收尾标签的空间
	if truncated.rfind('<') > truncated.rfind('>'):
		truncated = truncated[: truncated.rfind('<')]
	if truncated.rfind('&') > truncated.rfind(';'):
		truncated = truncated[: truncated.rfind('&')]

	truncated += '…'
	for tag in ('pre', 'b'):
		unclosed = truncated.count(f'<{tag}>') - truncated.count(f'</{tag}>')
		truncated += f'</{tag}>' * max(unclosed, 0)
	return truncated


def _http_error_detail(response: httpx.Response) -> str:
	"""拼出 HTTP 错误状态和响应体里的描述，Telegram 会把原因放在 description 中。"""
	detail = f'HTTP {response.status_code}'
	try:
		payload = response.json()
	except ValueError:
		return detail

	if isinstance(payload, dict):
		description = payload.get('description') or payload.get('errmsg') or payload.get('message')
		if description:
			return f'{detail}: {description}'
	return detail


class NotificationKit:
	def __init__(self):
		self.feishu_webhook = os.getenv('FEISHU_WEBHOOK')
		self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
		self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

	def _post_json(self, service: str, url: str, data: dict[str, Any], *, proxy: str | None = None) -> httpx.Response:
		with httpx.Client(timeout=30.0, proxy=proxy) as client:
			response = client.post(url, json=data)

		if response.status_code >= 400:
			raise RuntimeError(f'{service} request failed: {_http_error_detail(response)}')

		try:
			payload = response.json()
		except ValueError:
			return response

		if not isinstance(payload, dict):
			return response

		error_msg = payload.get('errmsg') or payload.get('message') or payload.get('msg') or payload.get('error')
		if payload.get('ok') is False:
			raise RuntimeError(f'{service} request failed: {error_msg or payload.get("description") or "ok=false"}')
		if payload.get('errcode') not in (None, 0):
			raise RuntimeError(f'{service} request failed: {error_msg or payload.get("errcode")}')
		if payload.get('StatusCode') not in (None, 0):
			raise RuntimeError(f'{service} request failed: {error_msg or payload.get("StatusCode")}')
		if payload.get('code') not in (None, 0, 200):
			raise RuntimeError(f'{service} request failed: {error_msg or payload.get("code")}')
		if payload.get('ret') not in (None, 0, 1, 200):
			raise RuntimeError(f'{service} request failed: {error_msg or payload.get("ret")}')

		return response

	def send_feishu(self, title: str, content: str):
		if not self.feishu_webhook:
			raise ValueError('FEISHU_WEBHOOK not configured')

		data = {
			'msg_type': 'interactive',
			'card': {
				'elements': [{'tag': 'markdown', 'content': content, 'text_align': 'left'}],
				'header': {'template': 'blue', 'title': {'content': title, 'tag': 'plain_text'}},
			},
		}
		self._post_json('Feishu', self.feishu_webhook, data)

	def send_telegram(self, title: str, content: str):
		if not self.telegram_bot_token or not self.telegram_chat_id:
			raise ValueError('TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID not configured')

		# api.telegram.org 无法直连，Telegram 通知复用签到脚本的 CHECKIN_PROXY_URL
		proxy = get_proxy_server()
		if proxy:
			print(f'[Telegram]: Notification proxy enabled: {proxy}')
		else:
			print('[WARN] Telegram: CHECKIN_PROXY_URL not set, connecting to api.telegram.org directly')

		url = f'https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage'
		data = {
			'chat_id': self.telegram_chat_id,
			'text': format_telegram_message(title, content),
			'parse_mode': 'HTML',
			'link_preview_options': {'is_disabled': True},
		}
		self._post_json('Telegram', url, data, proxy=proxy)

	def _push_channel(self, service: str, send: Callable[[str, str], None], title: str, content: str):
		try:
			send(title, content)
			print(f'[{service}]: Message push successful!')
		except Exception as e:
			print(f'[{service}]: Message push failed! Reason: {str(e)}')

	def push_message(self, title: str, content: str, msg_type: Literal['text'] = 'text'):
		if not (self.feishu_webhook or self.telegram_bot_token or self.telegram_chat_id):
			print('[NOTIFY]: No notification channel configured, message push skipped')
			return

		if self.feishu_webhook:
			self._push_channel('Feishu', self.send_feishu, title, content)
		if self.telegram_bot_token or self.telegram_chat_id:
			self._push_channel('Telegram', self.send_telegram, title, content)


notify = NotificationKit()
