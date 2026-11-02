# AutoPlay for OpenWrt 25.12 (apk): wireless CarPlay in a Tesla's browser on the ZTE F50. A GPL-3.0 hard fork of
# DashPlay (yizhixiaoheigou/DashPlay, openwrt-dashplay). Architecture-independent: the program bundle attached to each
# AutoPlay release (Python, the receiver's jars and the web player; box/scripts/build-bundle.sh builds it, since the
# receiver needs a JDK and Gradle, which the SDK does not have). The SDK downloads it and checks PKG_HASH;
# scripts/bump-autoplay.sh moves this package to another release, and scripts/build-packages.sh can build from a
# local bundle instead.
include $(TOPDIR)/rules.mk

PKG_NAME:=autoplay
PKG_VERSION:=1.1.0
PKG_RELEASE:=1
PKG_LICENSE:=GPL-3.0-only
PKG_SOURCE:=autoplay-bundle-$(PKG_VERSION).tar
# The fork's own releases (set the owner when AutoPlay publishes; the DashPlay bundles carry the old layout).
PKG_SOURCE_URL:=https://github.com/yizhixiaoheigou/AutoPlay/releases/download/v$(PKG_VERSION)/
# scripts/bump-autoplay.sh sets the hash of the release bundle; a local bundle (build-packages.sh) overrides it.
PKG_HASH:=skip

include $(INCLUDE_DIR)/package.mk

define Package/autoplay
  SECTION:=utils
  CATEGORY:=Utilities
  TITLE:=AutoPlay: wireless CarPlay in the Tesla's web browser
  PKGARCH:=all
  # The DashPlay packages this fork replaces: apk refuses to install both (update.py removes them first).
  CONFLICTS:=dashplay
  # Runtime dependencies only (EXTRA_DEPENDS): the SDK would otherwise build them from source.
  # Wireless CarPlay needs BlueZ and a Bluetooth adapter: not a hard dependency, since the ZTE F50 runs its
  # own BlueZ root (board_zte_f50.py --setup) and kernel packages must match the board's kernel.
  # curl: acme.sh, for the optional own name's certificate (duckdns_domain); BusyBox/uclient wget will not do.
  EXTRA_DEPENDS:=python3 (>=3.11), ip-full (>=6.0), iw (>=5.0), openssl-util (>=3.0), curl (>=8.0), autoplay-jre (>=21)
endef

define Package/autoplay/description
  Receives wireless CarPlay from an iPhone (Bluetooth + Wi-Fi) and shows it, with sound and touch, in the
  car's web browser on the router's network. The MFi identity is not included: put it in
  /opt/autoplay/identity/offline-mfi/ yourself.
endef

define Package/autoplay/conffiles
/etc/config/autoplay
endef

define Build/Prepare
	mkdir -p $(PKG_BUILD_DIR)/bundle
	tar -xf $(DL_DIR)/$(PKG_SOURCE) -C $(PKG_BUILD_DIR)/bundle
endef

define Build/Compile
endef

# state/ and identity/ are created by postinst and never owned by the package, so an upgrade or removal
# keeps pairings, certificates and the MFi identity.
define Package/autoplay/install
	$(INSTALL_DIR) $(1)/opt/autoplay $(1)/etc/init.d $(1)/etc/config $(1)/usr/libexec $(1)/etc/uci-defaults \
		$(1)/etc/hotplug.d/iface $(1)/etc/hotplug.d/ntp
	cd $(PKG_BUILD_DIR)/bundle && tar -cf - --exclude=./state --exclude=./identity . | tar -xf - -C $(1)/opt/autoplay
	$(INSTALL_BIN) ./files/autoplay.init $(1)/etc/init.d/autoplay
	# Tesla constants at install time: LAN 100.96.0.1/24, old options and DNS records dropped (D1, D2, D4).
	$(INSTALL_BIN) ./files/90-autoplay-tesla $(1)/etc/uci-defaults/90-autoplay-tesla
	# WAN up / NTP synced: retry the DuckDNS record and the certificate at once (reliability_audit #6).
	$(INSTALL_BIN) ./files/hotplug-iface $(1)/etc/hotplug.d/iface/90-autoplay
	$(INSTALL_BIN) ./files/hotplug-ntp $(1)/etc/hotplug.d/ntp/90-autoplay
	# Online update: LuCI's check / start command (update.py launch runs the update as a procd service of its own).
	$(INSTALL_BIN) ./files/autoplay-update $(1)/usr/libexec/autoplay-update
	$(INSTALL_CONF) ./files/autoplay.config $(1)/etc/config/autoplay
endef

define Package/autoplay/postinst
#!/bin/sh
[ -n "$$IPKG_INSTROOT" ] && exit 0
# Transition from DashPlay (the same program under its old name): its state (pairings, certificates, the
# Bluetooth link keys and address), identity, uci section and private BlueZ root move over once; nothing is
# copied twice and nothing of a fresh AutoPlay install is overwritten.
mkdir -p /opt/autoplay
for name in state identity; do
	if [ -d /opt/dashplay/$$name ] && [ ! -e /opt/autoplay/$$name ]; then
		mv /opt/dashplay/$$name /opt/autoplay/$$name && echo "autoplay: moved /opt/dashplay/$$name"
	fi
done
if [ -d /opt/dashplay-bluez ] && [ ! -e /opt/autoplay-bluez ]; then
	mv /opt/dashplay-bluez /opt/autoplay-bluez && echo "autoplay: moved the private BlueZ root"
fi
if [ -f /etc/config/dashplay ] && [ -z "$$(uci -q get autoplay.main.duckdns_domain)$$(uci -q get autoplay.main.viewer_port)" ]; then
	for option in enabled viewer_port idle_release duckdns_domain duckdns_token update_check update_mirror; do
		value=$$(uci -q get dashplay.main.$$option) && uci set autoplay.main.$$option="$$value"
	done
	uci commit autoplay && echo "autoplay: settings copied from /etc/config/dashplay"
fi
mkdir -p /opt/autoplay/state/receiver /opt/autoplay/identity/offline-mfi
chmod 700 /opt/autoplay/state /opt/autoplay/state/receiver /opt/autoplay/identity /opt/autoplay/identity/offline-mfi
# ZTE F50 (MU300 OpenWrt): the system's boot scripts, faster and without dropping CarPlay right after it came up
# (mu300_boot.py; it changes only the exact originals, keeps them, and "mu300_boot.py revert" puts them back)
if [ -d /opt/mu300 ]; then python3 /opt/autoplay/mu300_boot.py apply; fi
# The AppCDS archive now, not at the first clean exit the car never gives the JVM (reliability_audit #19). Best
# effort: needs the identity files and about a minute; a failure changes nothing.
if [ -s /opt/autoplay/identity/offline-mfi/identity.pk8 ] && [ -x /usr/lib/autoplay-jre/bin/java ]; then
	printf '{"ssid": "prime", "passphrase": "prime-cds"}\n' > /tmp/autoplay-prime.json
	/etc/init.d/autoplay stop
	PYTHONDONTWRITEBYTECODE=1 python3 /opt/autoplay/run-receiver.py --root /opt/autoplay --bind 127.0.0.1 --interface lo \
		--channel 36 --hotspot /tmp/autoplay-prime.json --java /usr/lib/autoplay-jre/bin/java --no-wireless --prime-cds || true
	rm -f /tmp/autoplay-prime.json
fi
/etc/init.d/autoplay enable
/etc/init.d/autoplay restart
exit 0
endef

define Package/autoplay/prerm
#!/bin/sh
[ -n "$$IPKG_INSTROOT" ] && exit 0
/etc/init.d/autoplay stop
/etc/init.d/autoplay disable
# Files the running program made beside the packaged ones; state/ and identity/ stay.
rm -f /opt/autoplay/playport/web/dist/receiver-access.js /opt/autoplay/playport/web/dist/receiver-access.json
find /opt/autoplay -name __pycache__ -type d -prune -exec rm -rf {} +
# Records older releases kept for the own name (the service's own ones are restored by its stop).
changed=
for section in dashplay dashplay6; do
	[ "$$(uci -q get dhcp.$$section)" = domain ] && uci delete dhcp.$$section && changed=1
done
for entry in $$(uci -q get dhcp.@dnsmasq[0].rebind_domain); do
	case "$$entry" in /*.duckdns.org/|/dashplay.lan/|/autoplay.lan/) uci -q del_list dhcp.@dnsmasq[0].rebind_domain="$$entry" && changed=1 ;; esac
done
if [ -n "$$changed" ]; then
	uci commit dhcp || exit 1
	# Reloading a stopped dnsmasq can start it and wait indefinitely for netifd/procd locks.
	# Python is still installed while prerm runs; OpenWrt busybox need not include timeout.
	python3 - <<'PY'
import json, subprocess
try:
    result = subprocess.run(['ubus', '-t', '5', 'call', 'service', 'list', '{"name":"dnsmasq"}'],
                            capture_output=True, text=True, timeout=6, check=True)
    instances = json.loads(result.stdout).get('dnsmasq', {}).get('instances', {})
    if any(instance.get('running') is True for instance in instances.values()):
        subprocess.run(['/etc/init.d/dnsmasq', 'reload'], timeout=15, check=True)
except (OSError, ValueError, subprocess.SubprocessError):
    print('AutoPlay DNS records removed from configuration; DNS reload unavailable, apply on next service restart.')
PY
fi
# The LAN stays at 100.96.0.1/24 (set by uci-defaults at install): put it back by hand if you want the old one.
exit 0
endef

$(eval $(call BuildPackage,autoplay))
