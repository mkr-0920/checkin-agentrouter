import json
from types import SimpleNamespace

import pytest

import checkin
from utils.browser import BrowserLoginSettings
from utils.config import AccountConfig, AppConfig, ProviderConfig
from utils.profiles import (
	get_profile_auth_type,
	is_profile_verified,
	mark_profile_verified,
)


def test_linuxdo_profile_requires_login():
	connect_login = SimpleNamespace(
		url='https://connect.linux.do/login',
		is_closed=lambda: False,
	)
	discourse_login = SimpleNamespace(
		url='https://linux.do/session/new',
		is_closed=lambda: False,
	)
	closed_page = SimpleNamespace(url='about:blank', is_closed=lambda: True)
	callback_page = SimpleNamespace(
		url='https://agentrouter.org/oauth/linuxdo?code=code&state=state',
		is_closed=lambda: False,
	)

	assert checkin._linuxdo_profile_requires_login(connect_login) is True
	assert checkin._linuxdo_profile_requires_login(discourse_login) is True
	assert checkin._linuxdo_profile_requires_login(closed_page) is False
	assert checkin._linuxdo_profile_requires_login(callback_page) is False


@pytest.mark.asyncio
async def test_build_linuxdo_oauth_authorize_url():
	class FakePage:
		async def evaluate(self, script):
			return {'clientId': 'KZUecGfhhDZMVnv8UtEdhOhf9sNOhqVX', 'state': 'test-state-123'}

	page = FakePage()
	url = await checkin.build_linuxdo_oauth_authorize_url(page, 'test-account')

	assert url is not None
	assert 'https://connect.linux.do/oauth2/authorize?' in url
	assert 'response_type=code' in url
	assert 'client_id=KZUecGfhhDZMVnv8UtEdhOhf9sNOhqVX' in url
	assert 'state=test-state-123' in url


@pytest.mark.asyncio
async def test_setup_linuxdo_browser_profile_resets_and_uses_visible_profile(monkeypatch, tmp_path):
	profile_dir = tmp_path / 'agentrouter' / 'profile_linuxdo'
	profile_dir.mkdir(parents=True)
	settings_seen = {}

	def fake_load_browser_login_settings(account_name, provider_name, *, persist_profile, browser_profile, reset_profile):
		settings_seen['load'] = (account_name, provider_name, persist_profile, browser_profile, reset_profile)
		return BrowserLoginSettings(
			headless=True,
			humanize=True,
			wait_timeout_ms=60_000,
			profile_dir=profile_dir,
			cloakbrowser_binary_path=None,
			persist_profile=True,
			browser_profile='profile_linuxdo',
		)

	async def fake_perform_direct_linuxdo_login(account_name, provider_name, provider_config, settings, *, use_proxy):
		settings_seen['login'] = (account_name, provider_name, provider_config.name, settings.headless, use_proxy)
		return checkin.BrowserLoginResult(cookies={'auth.session-token': 'token-123'})

	monkeypatch.setattr(checkin, 'load_browser_login_settings', fake_load_browser_login_settings)
	monkeypatch.setattr(checkin, 'perform_direct_linuxdo_login', fake_perform_direct_linuxdo_login)

	provider = ProviderConfig(name='agentrouter', domain='https://agentrouter.org', use_proxy=True)
	result = await checkin.setup_linuxdo_browser_profile('profile_linuxdo', provider, 'agentrouter')

	assert result == checkin.BrowserLoginResult(cookies={'auth.session-token': 'token-123'})
	assert settings_seen['load'] == ('profile_linuxdo', 'agentrouter', True, 'profile_linuxdo', True)
	assert settings_seen['login'] == ('profile_linuxdo', 'agentrouter', 'agentrouter', False, True)


@pytest.mark.asyncio
async def test_direct_linuxdo_login_detects_session_token(monkeypatch, tmp_path):
	class FakeContext:
		def __init__(self):
			self.cookies_calls = 0
			self.closed = False
			self.page = FakePage()
			self.pages = [self.page]

		async def new_page(self):
			return self.page

		async def clear_cookies(self, **kwargs):
			pass

		async def cookies(self, url=None):
			return [
				{'name': 'session', 'value': 'new-session'},
				{'name': 'auth.session-token', 'value': 'linuxdo-token-xyz'},
				{'name': 'cf_clearance', 'value': 'cf-ok'},
			]

		async def close(self):
			self.closed = True

	class FakePage:
		def __init__(self):
			self.urls = []
			self.url = 'about:blank'
			self.init_scripts = []

		async def goto(self, url, **kwargs):
			self.urls.append((url, kwargs))
			self.url = url

		async def add_init_script(self, script):
			self.init_scripts.append(script)

		def is_closed(self):
			return False

	context = FakeContext()
	calls = {}

	async def fake_launch_login_context(settings, *, use_proxy):
		calls['launch'] = (settings.profile_dir, use_proxy)
		return context

	async def fake_prepare_browser_page(page):
		calls['prepared'] = page

	async def fake_navigate_login_page(page, url, timeout, *, provider, account_name):
		page.url = 'https://agentrouter.org/login'

	async def fake_build_linuxdo_oauth_authorize_url(page, account_name):
		return 'https://connect.linux.do/oauth2/authorize?response_type=code'

	async def fake_wait_for_session_cookie(page, timeout_ms, *, cookie_url=None, previous_value=None):
		return True

	async def fake_verify_browser_login(page, console_url, timeout_ms):
		return {'id': 634072, 'username': 'mkr', 'quota': 500000}

	async def fake_sleep(seconds):
		calls['sleep'] = seconds
		context.page.url = 'https://agentrouter.org/console'

	async def fake_click_linuxdo_login_entry(page, timeout, *, provider, account_name):
		calls['click_linuxdo'] = True
		return True

	monkeypatch.setattr(checkin, 'launch_login_context', fake_launch_login_context)
	monkeypatch.setattr(checkin, 'prepare_browser_page', fake_prepare_browser_page)
	monkeypatch.setattr(checkin, 'navigate_login_page', fake_navigate_login_page)
	monkeypatch.setattr(checkin, 'click_linuxdo_login_entry', fake_click_linuxdo_login_entry)
	monkeypatch.setattr(checkin, 'build_linuxdo_oauth_authorize_url', fake_build_linuxdo_oauth_authorize_url)
	monkeypatch.setattr(checkin, 'wait_for_session_cookie', fake_wait_for_session_cookie, raising=False)
	monkeypatch.setattr(checkin, 'verify_browser_login', fake_verify_browser_login)
	monkeypatch.setattr(checkin.asyncio, 'sleep', fake_sleep)

	settings = BrowserLoginSettings(
		headless=False,
		humanize=True,
		wait_timeout_ms=60_000,
		profile_dir=tmp_path / 'agentrouter' / 'profile_linuxdo',
		cloakbrowser_binary_path=None,
		persist_profile=True,
		browser_profile='profile_linuxdo',
	)
	provider = ProviderConfig(name='agentrouter', domain='https://agentrouter.org', use_proxy=True)

	result = await checkin.perform_direct_linuxdo_login('profile_linuxdo', 'agentrouter', provider, settings, use_proxy=True)

	assert result is not None
	assert result.api_user == '634072'
	assert result.cookies['auth.session-token'] == 'linuxdo-token-xyz'
	assert calls['launch'] == (settings.profile_dir, True)
	assert context.closed is True


@pytest.mark.asyncio
async def test_profile_add_command_with_type_linuxdo(monkeypatch, tmp_path):
	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(tmp_path))
	env_file = tmp_path / '.env'
	env_file.write_text('AGENTROUTER_ACCOUNTS=[]\n')
	monkeypatch.setenv('CHECKIN_ENV_FILE', str(env_file))
	provider = ProviderConfig(name='agentrouter', domain='https://agentrouter.org')

	calls = {}

	async def fake_setup_linuxdo_browser_profile(profile_name, provider_config, provider_name):
		calls['setup_linuxdo'] = (profile_name, provider_name)
		return checkin.BrowserLoginResult(cookies={'auth.session-token': 'token'}, api_user='634072')

	monkeypatch.setattr(
		checkin,
		'AppConfig',
		type('FakeAppConfig', (), {'load_from_env': staticmethod(lambda: AppConfig({'agentrouter': provider}))}),
	)
	monkeypatch.setattr(checkin, 'setup_linuxdo_browser_profile', fake_setup_linuxdo_browser_profile)

	exit_code = await checkin.run_profile_add('agentrouter', 'mkr_linuxdo', auth_type='linuxdo')

	assert exit_code == 0
	assert calls['setup_linuxdo'] == ('mkr_linuxdo', 'agentrouter')
	assert is_profile_verified('agentrouter', 'mkr_linuxdo', profile_root=tmp_path)
	assert get_profile_auth_type('agentrouter', 'mkr_linuxdo', profile_root=tmp_path) == 'linuxdo'
	assert 'AGENTROUTER_ACCOUNTS=["mkr_linuxdo"]' in env_file.read_text()


@pytest.mark.asyncio
async def test_check_in_account_dispatches_to_linuxdo_when_configured(monkeypatch, tmp_path):
	profile_root = tmp_path / 'profiles'
	profile_dir = profile_root / 'agentrouter' / 'mkr_linuxdo'
	profile_dir.mkdir(parents=True)
	mark_profile_verified(
		'agentrouter',
		'mkr_linuxdo',
		json.dumps({'status': 'valid', 'auth_type': 'linuxdo'}),
		profile_root=profile_root,
	)

	account = AccountConfig(
		name='mkr_linuxdo',
		provider='agentrouter',
		cookies=None,
		api_user=None,
		github_browser=True,
		browser_profile='mkr_linuxdo',
	)
	provider = ProviderConfig(name='agentrouter', domain='https://agentrouter.org', use_proxy=True)
	app_config = AppConfig(providers={'agentrouter': provider})
	calls = {}

	async def fake_login_with_linuxdo_browser(account_arg, account_name, provider_config, provider_name):
		calls['linuxdo_login'] = (account_arg.browser_profile, account_name, provider_name)
		return checkin.BrowserLoginResult(
			cookies={'session': 'linuxdo-session'},
			api_user='634072',
			user_profile={'id': 634072, 'quota': 25_000_000, 'used_quota': 0},
		)

	def fake_run_user_info_request(cookies, account_arg, account_name, provider_config, **kwargs):
		return {'success': True, 'quota': 50.0, 'used_quota': 0.0}

	monkeypatch.setenv('CHECKIN_BROWSER_PROFILE_DIR', str(profile_root))
	monkeypatch.setattr(checkin, 'login_with_linuxdo_browser', fake_login_with_linuxdo_browser)
	monkeypatch.setattr(checkin, 'run_user_info_request', fake_run_user_info_request)
	monkeypatch.setattr(checkin, 'load_last_session', lambda account_name: None)
	monkeypatch.setattr(checkin, 'save_last_session', lambda account_name, cookies, api_user: None)

	result = await checkin.check_in_account(account, 0, app_config)

	assert result[0] is True
	assert calls['linuxdo_login'] == ('mkr_linuxdo', 'mkr_linuxdo', 'agentrouter')
	assert result[2]['success'] is True
	assert result[2]['quota'] == 50.0


@pytest.mark.asyncio
async def test_confirm_linuxdo_oauth_clicks_approve_button():
	from utils.browser import confirm_linuxdo_oauth

	class FakeButton:
		def __init__(self):
			self.clicked = False

		async def is_visible(self):
			return True

		async def click(self, *, timeout):
			self.clicked = timeout

	class FakeLocator:
		def __init__(self, button):
			self.first = button

	class FakePage:
		def __init__(self):
			self.url = 'https://connect.linux.do/oauth2/authorize?response_type=code'
			self.button = FakeButton()

		def locator(self, selector):
			return FakeLocator(self.button)

		def is_closed(self):
			return False

	page = FakePage()
	result = await confirm_linuxdo_oauth(page, 10_000)

	assert result is True
	assert page.button.clicked == 10_000


@pytest.mark.asyncio
async def test_click_linuxdo_login_entry(monkeypatch):
	import utils.browser as browser_module

	class FakeButton:
		async def is_visible(self):
			return True

		async def scroll_into_view_if_needed(self):
			pass

		async def click(self, *, timeout):
			return True

	class FakeLocator:
		def __init__(self, count=1):
			self._count = count
			self._btn = FakeButton()

		async def count(self):
			return self._count

		def nth(self, idx):
			return self._btn

	class FakePage:
		def __init__(self):
			self.url = 'https://agentrouter.org/login'

		def locator(self, selector):
			if 'linuxdo' in selector.lower() or 'linux do' in selector.lower():
				return FakeLocator(1)
			return FakeLocator(0)

		def get_by_role(self, role, *, name):
			return SimpleNamespace(first=FakeButton())

	async def fake_wait(page, timeout):
		pass

	async def fake_dismiss(page):
		return 0

	monkeypatch.setattr(browser_module, '_wait_for_login_page_ready', fake_wait)
	monkeypatch.setattr(browser_module, '_dismiss_blocking_overlays', fake_dismiss)

	page = FakePage()
	clicked = await browser_module.click_linuxdo_login_entry(page, 5_000)

	assert clicked is True

