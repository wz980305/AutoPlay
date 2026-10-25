"""The Tesla's connectivity checks and the answers the box gives them.

Extracted from setup_wizard.py (DashPlay) so that tesla_openwrt.py and the settings page stop importing the
Debian wizard (code_inventory_trimming.md section 2; tesla_only_box_delta.md Q3: keep all 7 names).
"""

# F2, Tesla drive 2026-10-15: connman alone is insufficient. The China car asked for the .cn connman name and the
# next three; the others (2026-10-16, from a user's working fix) are the overseas firmware's connman name, baidu.com
# and the Chromium/Android check, answered in case a car or browser asks for them.
CONNMAN_NAMES = ("connman.vn.cloud.tesla.cn", "connman.vn.tesla.services")
TESLA_CHECK_NAMES = (CONNMAN_NAMES[0], "www.baidu.cn", "www.qq.com", "www.tesla.cn",
                     CONNMAN_NAMES[1], "www.baidu.com", "connectivitycheck.gstatic.com")
# The real connman servers' reply (2026-10-16: .services 200 with this body; .cn a 403 that still carries the
# status header, so ConnMan reads only the header). X-Cache is copied from them.
CONNMAN_BODY = b"<html>\n<head>\n</head>\n<body>\n</body>\n</html>\n\n"
CONNMAN_HEADERS = {"X-ConnMan-Status": "online", "X-Cache": "Hit from cloudfront"}


def check_name(host):
    name = host.split(":", 1)[0].lower().rstrip(".")
    return name if name in TESLA_CHECK_NAMES else None


def check_response(host, path="/"):
    """(status, body, headers) for a connectivity check, or None when host is not a check name."""
    name = check_name(host)
    if name in CONNMAN_NAMES:
        return 200, CONNMAN_BODY, dict(CONNMAN_HEADERS)
    if name == "connectivitycheck.gstatic.com" and path.split("?")[0] in ("/generate_204", "/gen_204"):
        return 204, b"", {}
    if name:
        return 200, b"<html><body>online</body></html>\n", {}
    return None
