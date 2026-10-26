"""System boundary for the helpers the receiver spawns (phone-presence.py, pairing_window.py).

get_platform() returns the OpenWrt adapter: the F50 is the only target, and the helpers only need its
boot_id(). The Debian/Armbian adapter is never imported from here, so a box without platform_debian.py
keeps inviting iPhones (code_inventory_trimming.md 2.1: phone-presence fails closed on any import error).
"""


def get_platform(interface="", **paths):
    from platform_openwrt import OpenWrtPlatform
    return OpenWrtPlatform(interface, **paths)
