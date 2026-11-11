# Runs one explorer candidate with hostap's own helpers (issue #79).
#
# The host (src/explorer/adapter.py) translates a model.Candidate into a plan: hostapd
# parameters per AP link, wpa_supplicant connect arguments and the ordered actions. The
# plan is copied into the container as explorer_plan.json next to this file before the
# guest boots (the UML guest sees the container's files, apart from /tmp).
#
# Outcomes, read back by the host from this test's log:
# - an action that hostapd/wpa_supplicant refuses, or a setup that doesn't come up,
#   logs "EXPLORER-REJECTED ..." and fails the test (P3 REJECTED); when the adapter
#   itself refuses (e.g. removing a link twice), the reason starts with "adapter:";
# - traffic, link and rekey results are observations, logged through the same helpers
#   hostap's EHT tests use, so explorer.signatures reads them; they never fail the test.
#
# Helpers and line numbers are tests/hwsim/test_eht.py at the pinned commit 43ee60e1.
# Not part of hostap. The Dockerfile copies this next to test_eht.py.

import json
import logging
import os
import time

# Not "import test_eht": run-tests.py collects every module-level name starting with test_.
import test_eht as _eht
from hwsim import HWSimRadio
from utils import check_owe_capab, check_sae_capab
from wpasupplicant import WpaSupplicant

logger = logging.getLogger()

PLAN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "explorer_plan.json")
BEACON_INTERVAL_S = 0.1024  # hostapd default beacon_int 100 TU


class Rejected(Exception):
    """hostapd or wpa_supplicant refused a setup step or an action."""


def _reject(where, reason):
    logger.info("EXPLORER-REJECTED %s: %s" % (where, reason))
    raise Rejected("%s: %s" % (where, reason))


class _Run:
    def __init__(self, plan, wpas, hapds):
        self.plan = plan
        self.wpas = wpas
        self.hapds = hapds          # link_id -> hostapd for that affiliated AP
        self.removed = set()        # link IDs removed by link_remove
        self.associated = False

    # --- observations (never fail the test) -----------------------------------

    def links(self):
        """Same reads as _eht_verify_links() (test_eht.py:58-65), without asserting values;
        they log "valid_links=..." / "active_links=...". Returns the active-links bitmap.
        _eht_get_links_bitmap() calls an undefined logger_info when the debugfs file is
        missing (test_eht.py:39), so a failed read is logged, never raised."""
        active = 0
        for name, read in (("valid_links", _eht._eht_valid_links),
                           ("active_links", _eht._eht_active_links)):
            try:
                value = read(self.wpas)
            except Exception as e:
                logger.info("EXPLORER-LINKS-UNREADABLE %s: %s" % (name, e))
                value = 0
            if name == "active_links":
                active = value
        return active

    def observe(self, after):
        logger.info("EXPLORER-OBSERVE after %s (%s)" %
                    (after, "associated" if self.associated else "not associated"))
        time.sleep(0.1)
        active = self.links()
        # Same line as eht_verify_wifi_version() (test_eht.py:25-27), without asserting;
        # logged when not associated too, so the record ends with the final state.
        logger.info("station status: " + str(self.wpas.get_status()))
        for link_id in sorted(self.hapds):
            if self.associated:
                if link_id in self.removed or not active & (1 << link_id):
                    continue
                expected = True
            else:
                # After a disconnect or the last link's removal, traffic should fail, as
                # hostap's test checks after removing the last link (test_eht.py:1424-1425).
                expected = False
            try:
                _eht.traffic_test(self.wpas, self.hapds[link_id], success=expected)
            except Exception as e:
                logger.info("EXPLORER-TRAFFIC-%s link %d: %s" %
                            ("FAILED" if expected else "UNEXPECTED", link_id, e))

    def wait_event(self, events, timeout, what):
        ev = self.wpas.wait_event(events, timeout=timeout)
        if ev is None:
            logger.info("EXPLORER-NO-EVENT %s within %.1f s" % (what, timeout))
        return ev

    # --- actions ---------------------------------------------------------------

    def associate(self, index, step):
        sta = self.plan["sta"]
        if sta["sae_groups"]:
            self.wpas.set("sae_groups", sta["sae_groups"])
        try:
            self.wpas.connect(self.plan["ssid"], **sta["connect"])
        except Exception as e:
            _reject("actions[%d] associate" % index, e)
        self.associated = True

    def link_remove(self, index, step):
        link_id = step["link_id"]
        if link_id in self.removed:
            _reject("actions[%d] link_remove" % index, "adapter: link %d already removed" % link_id)
        try:
            self.hapds[link_id].link_remove(step["count"])   # hostapd.py:296-298
        except Exception as e:
            _reject("actions[%d] link_remove" % index, e)
        self.removed.add(link_id)
        # Removal takes effect after <count> beacon intervals; hostap's test waits
        # 0.6 s for count 4 and 3 s for count 20 (test_eht.py:1400-1421).
        self.wait_event(["CTRL-EVENT-LINK-RECONFIG", "CTRL-EVENT-DISCONNECTED"],
                        step["count"] * BEACON_INTERVAL_S + 1.0, "link removal")
        if all(link in self.removed for link in self.hapds):
            time.sleep(1.0)
            self.associated = False

    def rekey_gtk_now(self, index, step):
        remaining = [link for link in sorted(self.hapds) if link not in self.removed]
        if not remaining:
            _reject("actions[%d] rekey_gtk_now" % index, "adapter: no AP link left")
        # hostap's test sends REKEY_GTK to link 0's AP (test_eht.py:1406-1411).
        if "OK" not in self.hapds[remaining[0]].request("REKEY_GTK"):
            _reject("actions[%d] rekey_gtk_now" % index, "REKEY_GTK failed")
        self.wait_event(["MLO RSN: Group rekeying completed"], 2, "GTK rekey")

    def sta_disconnect_reconnect(self, index, step):
        command = step["command"]
        if "OK" not in self.wpas.request(command):
            _reject("actions[%d] %s" % (index, command), "%s failed" % command)
        if command == "DISCONNECT":
            # test_eht.py:557-558
            self.wait_event(["CTRL-EVENT-DISCONNECTED"], 5, "disconnect")
            self.associated = False
        else:
            ev = self.wait_event(["CTRL-EVENT-CONNECTED"], 15, "reconnect")
            self.associated = ev is not None

    def settle(self):
        """Interval-driven rekeys, observed as hostap's rekey tests do."""
        ap = self.plan["ap_shared"]
        if self.associated and ap.get("wpa_ptk_rekey"):
            # test_eht.py:932-945: wait for one PTK rekey, then traffic.
            self.wait_event(["WPA: Key negotiation completed"],
                            int(ap["wpa_ptk_rekey"]) + 5, "PTK rekey")
            self.observe("PTK rekey")
        if self.associated and ap.get("wpa_group_rekey"):
            # test_eht.py:975-987: wait for two GTK rekeys, traffic after each.
            for i in range(2):
                self.wait_event(["MLO RSN: Group rekeying completed"],
                                int(ap["wpa_group_rekey"]) + 5, "GTK rekey %d" % (i + 1))
                self.observe("GTK rekey %d" % (i + 1))


def test_explorer_candidate(dev, apdev):
    """Explorer candidate from explorer_plan.json (adapter, not a hostap test)"""
    with open(PLAN_FILE) as f:
        plan = json.load(f)
    logger.info("EXPLORER-PLAN " + json.dumps(plan, sort_keys=True))

    with HWSimRadio(use_mlo=True) as (hapd_radio, hapd_iface), \
        HWSimRadio(use_mlo=True) as (wpas_radio, wpas_iface):

        wpas = WpaSupplicant(global_iface='/tmp/wpas-wlan5')
        wpas.interface_add(wpas_iface)
        if plan["needs_sae"]:
            check_sae_capab(wpas)
        if plan["needs_owe"]:
            check_owe_capab(wpas)

        hapds = {}
        for link in plan["ap_links"]:
            try:
                hapds[link["link_id"]] = _eht.eht_mld_enable_ap(hapd_iface, link["link_id"],
                                                                link["params"])
            except Exception as e:
                _reject("AP link %d setup" % link["link_id"], e)

        run = _Run(plan, wpas, hapds)
        try:
            for index, step in enumerate(plan["actions"]):
                logger.info("EXPLORER-ACTION %d %s" % (index, json.dumps(step, sort_keys=True)))
                getattr(run, step["action"])(index, step)
                run.observe("actions[%d] %s" % (index, step["action"]))
            run.settle()
            logger.info("EXPLORER-DONE")
        finally:
            if plan["sta"]["sae_groups"]:
                wpas.set("sae_groups", "")
