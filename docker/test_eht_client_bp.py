# hostap's EHT MLD tests with the MLD client's beacon protection on.
#
# 802.11be-2024 §12.12.9 and WFA guide Table 4 require beacon protection on an EHT AP
# and an EHT STA using RSN, but these tests at the pinned commit don't set it on the
# client. Each wrapper runs hostap's own test unchanged, adding beacon_prot="1" to the
# connect calls of the MLD client it creates. The dev[] stations keep their settings.
#
# Not part of hostap. The Dockerfile copies this next to test_eht.py, where run-tests.py
# finds it.

# Not "import test_eht": run-tests.py collects every module-level name starting with test_.
import test_eht as _eht
from wpasupplicant import WpaSupplicant


def _with_client_beacon_prot(dev, apdev, test):
    original = WpaSupplicant.connect

    def connect(self, *args, **kwargs):
        if self not in dev:
            kwargs.setdefault("beacon_prot", "1")
        return original(self, *args, **kwargs)

    WpaSupplicant.connect = connect
    try:
        test(dev, apdev)
    finally:
        WpaSupplicant.connect = original


def test_eht_mld_sae_ext_two_links_client_bp(dev, apdev):
    """eht_mld_sae_ext_two_links with client beacon protection"""
    _with_client_beacon_prot(dev, apdev, _eht.test_eht_mld_sae_ext_two_links)


def test_eht_mld_owe_two_links_client_bp(dev, apdev):
    """eht_mld_owe_two_links with client beacon protection"""
    _with_client_beacon_prot(dev, apdev, _eht.test_eht_mld_owe_two_links)


def test_eht_mld_owe_two_links_one_disabled_client_bp(dev, apdev):
    """eht_mld_owe_two_links_one_disabled with client beacon protection"""
    _with_client_beacon_prot(dev, apdev, _eht.test_eht_mld_owe_two_links_one_disabled)


def test_eht_mld_ptk_rekey_client_bp(dev, apdev):
    """eht_mld_ptk_rekey with client beacon protection"""
    _with_client_beacon_prot(dev, apdev, _eht.test_eht_mld_ptk_rekey)


def test_eht_mld_gtk_rekey_client_bp(dev, apdev):
    """eht_mld_gtk_rekey with client beacon protection"""
    _with_client_beacon_prot(dev, apdev, _eht.test_eht_mld_gtk_rekey)


def test_eht_mld_link_removal_client_bp(dev, apdev):
    """eht_mld_link_removal with client beacon protection"""
    _with_client_beacon_prot(dev, apdev, _eht.test_eht_mld_link_removal)
