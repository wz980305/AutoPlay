'use strict';
'require view';
'require form';
'require rpc';
'require uci';
'require fs';
'require dom';
'require poll';
'require ui';

// Tesla-only box: the LAN (100.96.0.1/24), the settings port, the Tesla connectivity checks and the car's
// Bluetooth audio are constants of the package, not options. This page keeps the seven uci options and shows the
// status; iPhones are added on the AutoPlay settings page (tesla_only_box_delta.md D15, settings_onboarding_audit S13).
var callServiceList = rpc.declare({
	object: 'service',
	method: 'list',
	params: [ 'name' ],
	expect: { '': {} }
});

function running(services) {
	var instances = (services && services.autoplay && services.autoplay.instances) || {};
	return Object.keys(instances).some(function(name) { return instances[name].running; });
}

return view.extend({
	load: function() {
		return Promise.all([
			L.resolveDefault(callServiceList('autoplay'), {}),
			uci.load('autoplay')   // read below (viewer port) before the form loads it
		]);
	},

	render: function(data) {
		var host = window.location.hostname;
		var port = '18080';
		var viewer = uci.get('autoplay', 'main', 'viewer_port') || '18443';
		var m, s, o;

		m = new form.Map('autoplay', _('AutoPlay'),
			_('CarPlay in the Tesla\'s web browser. The box\'s Wi-Fi (Network → Wireless) is handed to the iPhone over Bluetooth; the Tesla joins the same Wi-Fi and opens the CarPlay page.'));

		// Overview: status, the network warning and the two things people come here for, at the top of every tab.
		s = m.section(form.NamedSection, 'main', 'autoplay', _('Overview'));
		s.anonymous = true;

		o = s.option(form.DummyValue, '_status', _('Status'));
		o.rawhtml = true;
		o.cfgvalue = function() {
			return running(data[0])
				? '<b style="color:green">' + _('Running') + '</b>'
				: '<b style="color:red">' + _('Not running') + '</b>';
		};

		o = s.option(form.DummyValue, '_network_warning', _('Network warning'));
		o.renderWidget = function() {
			return E('div', { 'id': 'autoplay-network-warning', 'role': 'status', 'style': 'color:#b45309' });
		};

		o = s.option(form.DummyValue, '_links', _('Open'));
		o.rawhtml = true;
		o.cfgvalue = function() {
			return '<a class="btn cbi-button cbi-button-action" target="_blank" href="http://' + host + ':' + port + '/">' +
				_('Add iPhone') + '</a> ' +
				'<a class="btn cbi-button" target="_blank" href="https://' + host + ':' + viewer + '/">' +
				_('CarPlay screen') + '</a>';
		};

		s = m.section(form.NamedSection, 'main', 'autoplay');
		s.tab('network', _('Network'));
		s.tab('iphone', _('iPhone'));
		s.tab('reach', _('Own address'));
		s.tab('update', _('Program update'));

		o = s.taboption('network', form.Flag, 'enabled', _('Enable'));
		o.rmempty = false;

		o = s.taboption('network', form.DummyValue, '_lan', _('Addresses'));
		o.rawhtml = true;
		o.cfgvalue = function() {
			return _('The box\'s LAN is %s (set at install: a Tesla\'s browser opens no private address). The first access point under Network → Wireless is handed to the iPhone, 5 GHz first; the Tesla sees 5 GHz channels 36–48 and 149–165 only (CN: 149). In the Tesla\'s Wi-Fi settings turn on "Remain connected in Drive", else the picture stops out of Park. Settings page: %s').format(
				'100.96.0.1/24', 'http://' + host + ':' + port + '/');
		};

		o = s.taboption('network', form.Value, 'viewer_port', _('CarPlay screen port'));
		o.datatype = 'port';
		o.placeholder = '18443';
		o.description = _('The HTTPS port of the CarPlay page. Empty is 18443, or the port an older install saved; a change takes about a minute and interrupts CarPlay briefly. It must differ from 18080, 80, 443 and 7000.');

		o = s.taboption('network', form.DummyValue, '_debug', _('Diagnostics'));
		o.cfgvalue = function() { return _('Download diagnostics from the AutoPlay settings page. Saving changes here restarts the service and interrupts CarPlay briefly.'); };

		o = s.taboption('iphone', form.DummyValue, '_iphone', _('Adding an iPhone'));
		o.rawhtml = true;
		o.cfgvalue = function() {
			return _('Open the settings page on the Tesla or another device (not on the iPhone being added: it must stay in Settings → Bluetooth) and tap "Add iPhone". Pair the iPhone with the Tesla over Bluetooth as well and pick it as the media source: music, calls and Siri go over the car\'s own Bluetooth; the CarPlay page shows the screen and plays navigation prompts.') +
				' <a class="btn cbi-button cbi-button-action" target="_blank" href="http://' + host + ':' + port + '/">' + _('Add iPhone') + '</a>';
		};

		// A trade-off: a released iPhone stays cool near a box left on; a page opened later waits ~7 s.
		o = s.taboption('iphone', form.Value, 'idle_release', _('Release the iPhone after (seconds)'),
			_('Without any page showing the picture for this long, wireless CarPlay ends and the iPhone stops sending its screen; opening the page invites it again (about 7 s). 0: never end it.'));
		o.datatype = 'uinteger';
		o.placeholder = '300';

		// A public name with a Let's Encrypt certificate, obtained by DNS-01 over the SIM (nothing has to reach the
		// box). Two providers: a free DuckDNS sub-domain, or a Tencent Cloud (DNSPod) domain.
		o = s.taboption('reach', form.ListValue, 'dns_provider', _('DNS provider'));
		o.value('duckdns', _('DuckDNS'));
		o.value('dnspod', _('Tencent Cloud (DNSPod)'));
		o.default = 'duckdns';
		o.rmempty = false;
		o.description = _('Which DNS service owns the name below. Without any name the Tesla opens https://autoplay.lan:18443/ with the box\'s own certificate; whether its warning page offers "continue" is not verified.');

		o = s.taboption('reach', form.Value, 'duckdns_domain', _('DuckDNS sub-domain'),
			_('Sign up for free at duckdns.org, add a sub-domain and enter it with the token shown there. The name becomes that name (e.g. mycar.duckdns.org): AutoPlay points it at this box and obtains a free Let\'s Encrypt certificate, renewed automatically over the SIM, so the Tesla opens https://mycar.duckdns.org:18443/ without a warning.'));
		o.datatype = 'and(hostname,maxlength(63))';
		o.placeholder = 'mycar';
		o.depends('dns_provider', 'duckdns');

		o = s.taboption('reach', form.Value, 'duckdns_token', _('DuckDNS token'));
		o.password = true;
		o.depends('dns_provider', 'duckdns');

		o = s.taboption('reach', form.Value, 'own_domain', _('Own domain (DNSPod)'),
			_('A full domain you manage in Tencent Cloud DNS (DNSPod), e.g. car.example.com. AutoPlay obtains the Let\'s Encrypt certificate with a DNS-01 challenge through the DNSPod API and answers the name locally for the Tesla, so no public A record is required. The Tesla opens https://car.example.com:18443/ without a warning.'));
		o.placeholder = 'car.example.com';
		o.depends('dns_provider', 'dnspod');

		o = s.taboption('reach', form.Value, 'dnspod_id', _('DNSPod API ID'),
			_('In the DNSPod console (console.dnspod.cn) → Security settings → API Token → create a token; the ID is the number shown there.'));
		o.datatype = 'uinteger';
		o.depends('dns_provider', 'dnspod');

		o = s.taboption('reach', form.Value, 'dnspod_token', _('DNSPod API token'));
		o.password = true;
		o.depends('dns_provider', 'dnspod');

		o = s.taboption('reach', form.DummyValue, '_certificate', _('Certificate'));
		o.renderWidget = function() {
			return E('div', { 'id': 'autoplay-certificate' }, _('Loading…'));
		};

		// Online update (update.py): the daily check and an update run apart from the service, by /usr/libexec/autoplay-update.
		o = s.taboption('update', form.DummyValue, '_update', _('Program update'));
		o.renderWidget = function() {
			return E('div', { 'id': 'autoplay-update' }, _('Loading…'));
		};

		o = s.taboption('update', form.Flag, 'update_check', _('Check for a new version daily'),
			_('Only shows that there is one; nothing is installed until you click "Update now". Before updating, the iPhones, certificates and settings are backed up; a version that does not start is replaced by the previous one.'));
		o.rmempty = false;
		o.default = '1';

		o = s.taboption('update', form.Value, 'update_mirror', _('Download mirror'),
			_('Tried when GitHub cannot be reached. Releases are signed, so a mirror cannot change what is installed. Empty: the built-in mirror; "none": GitHub only.'));
		o.placeholder = 'https://ghfast.top/';

		return m.render().then(function(node) {
			var warning = node.querySelector('#autoplay-network-warning');
			var certificate = node.querySelector('#autoplay-certificate');
			function updateWarning() {
				return L.resolveDefault(fs.read('/var/run/autoplay/network-status.json'), '').then(function(raw) {
					var state;
					try { state = JSON.parse(raw); } catch (e) { state = {}; }
					warning.textContent = Date.now() / 1000 - state.checked_at < 45
						? state.warning || '' : _('Network check unavailable (service starting or stopped).');
				});
			}
			function updateCertificate() {
				return L.resolveDefault(fs.read('/opt/autoplay/state/own-domain.json'), '').then(function(raw) {
					var own;
					try { own = JSON.parse(raw) || {}; } catch (e) { own = {}; }
					if (!own.name)
						certificate.textContent = _('No own name set.');
					else
						certificate.textContent = own.name + ': ' + ({
							ready: _('certificate installed'), issuing: _('obtaining the certificate (a few minutes online)'),
							renewing: _('renewing the certificate'), retry: _('not obtained yet: check the SIM and the DNS provider credentials; retried every hour')
						}[own.phase] || _('waiting for the internet')) + (own.record == 'failed' ? '; ' + _('DNS record update failed, retrying') : '');
				});
			}
			poll.add(updateWarning, 10);
			poll.add(updateCertificate, 30);

			var box = node.querySelector('#autoplay-update');
			function readJson(path) {
				return L.resolveDefault(fs.read(path), '').then(function(raw) {
					try { return JSON.parse(raw) || {}; } catch (e) { return {}; }
				});
			}
			function run(action) {
				return fs.exec('/usr/libexec/autoplay-update', [ action ]).then(function(res) {
					if (res.stdout && action == 'start')
						ui.addNotification(null, E('p', res.stdout.trim()), 'info');
					return updateProgram();
				});
			}
			function line(title, text) {
				return E('p', {}, [ E('strong', {}, title), text ? ' ' + text : '' ]);
			}
			function updateProgram() {
				return Promise.all([
					readJson('/opt/autoplay/state/update-check.json'),
					readJson('/opt/autoplay/state/update-status.json')
				]).then(function(data) {
					var found = data[0], progress = data[1], now = Date.now() / 1000, items = [];
					var busy = progress.phase && progress.phase != 'done' && progress.phase != 'failed' && now - progress.at < 1200;
					if (busy) {
						items.push(line(_('Updating:'), progress.message));
						items.push(E('p', {}, _('About 2–5 minutes; CarPlay is interrupted meanwhile.')));
						return dom.content(box, items);
					}
					// A failure no longer matters once a later check finds the box up to date (updated by hand, say).
					var settled = progress.phase == 'failed' && found.latest && !found.available && !found.error
						&& found.checked_at > progress.at;
					if ((progress.phase == 'done' || progress.phase == 'failed') && now - progress.at < 86400 && !settled)
						items.push(line(progress.phase == 'done' ? _('Last update:') : _('Last update did not finish:'), progress.message));
					if (found.error)
						items.push(line(_('Checking for updates failed:'), found.error));
					else if (found.available) {
						items.push(line(_('New version %s').format(found.latest), _('(installed: %s)').format(found.current || _('an older version'))));
						if (found.notes)
							items.push(E('pre', { 'style': 'white-space:pre-wrap' }, found.notes));
						if (!found.online)
							items.push(E('p', {}, (found.reason ? found.reason + '：' : '') + _('This version changes the system: reinstall as the installation guide describes.')));
					}
					else if (found.latest)
						items.push(line(_('Up to date:'), found.latest));
					var buttons = [ E('button', { 'class': 'btn cbi-button', 'click': ui.createHandlerFn(this, run, 'check') }, _('Check now')) ];
					if (found.available && found.online && !found.error)
						buttons.push(' ', E('button', {
							'class': 'btn cbi-button cbi-button-action',
							'click': ui.createHandlerFn(this, function() {
								if (confirm(_('Update AutoPlay now? CarPlay is interrupted for a few minutes.')))
									return run('start');
							})
						}, _('Update now')));
					items.push(E('p', {}, buttons));
					if (found.checked_at)
						items.push(E('p', { 'class': 'cbi-value-description' }, _('Last checked: %s').format(new Date(found.checked_at * 1000).toLocaleString())));
					return dom.content(box, items);
				});
			}
			poll.add(updateProgram, 5);
			return Promise.all([ updateWarning(), updateCertificate(), updateProgram() ]).then(function() { return node; });
		});
	}
});
