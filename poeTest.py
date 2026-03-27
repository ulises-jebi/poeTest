"""
========================================================================
 PLANET IGS-4215-8UP2T2S - PoE CLI Tool (poeTest)
 Monitoreo y control de puertos PoE
========================================================================
 Requisitos:
   pip install pysnmp==4.4.12 pyasn1==0.4.8 pyasn1-modules==0.2.8
   pip install requests

 Uso:
   poeTest help
========================================================================
"""

from pysnmp.hlapi import (
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity, getCmd, nextCmd,
)
import requests
import re
import sys
import os
import time
import csv
from datetime import datetime, timedelta


SWITCH_CONFIG = {
    "host":       "192.168.1.90",
    "snmp_port":  161,
    "community":  "public",
    "timeout":    5,
    "retries":    2,
    "web_user":   "admin",
    "web_pass":   "JebiPoe1!",
}

LOG_FILE = "poe_log.csv"

PRIORITY_MAP   = {0: "Critical", 1: "High", 2: "Low"}
PD_TYPE_MAP    = {0: "Standard", 1: "Legacy", 2: "Force"}
INLINE_MAP     = {0: "End-Span", 1: "Mid-Span", 3: "BT"}
POE_MODE_MAP   = {0: "Disable", 1: "Enable", 2: "Schedule"}
PSE_STATUS_MAP = {1: "ON", 2: "OFF", 3: "FAULTY"}

SYSTEM_OIDS = {
    "sysDescr":  "1.3.6.1.2.1.1.1.0",
    "sysName":   "1.3.6.1.2.1.1.5.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
}

POE_MAIN_OIDS = {
    "pethMainPsePower":            "1.3.6.1.2.1.105.1.3.1.1.2",
    "pethMainPseOperStatus":       "1.3.6.1.2.1.105.1.3.1.1.3",
    "pethMainPseConsumptionPower": "1.3.6.1.2.1.105.1.3.1.1.4",
}


# ==============================================================
# SNMP CLIENT
# ==============================================================
class SNMPClient:
    def __init__(self, config):
        self.engine = SnmpEngine()
        self.community = CommunityData(config["community"], mpModel=1)
        self.transport = UdpTransportTarget(
            (config["host"], config["snmp_port"]),
            timeout=config["timeout"], retries=config["retries"],
        )
        self.context = ContextData()

    def get(self, oid):
        err_ind, err_st, _, var_binds = next(
            getCmd(self.engine, self.community, self.transport,
                   self.context, ObjectType(ObjectIdentity(oid))))
        if err_ind:
            raise ConnectionError("SNMP: " + str(err_ind))
        if err_st:
            raise RuntimeError("SNMP: " + err_st.prettyPrint())
        return var_binds[0][1]

    def walk(self, oid):
        results = []
        for (err_ind, err_st, _, var_binds) in nextCmd(
            self.engine, self.community, self.transport,
            self.context, ObjectType(ObjectIdentity(oid)),
            lexicographicMode=False,
        ):
            if err_ind or err_st:
                break
            for vb in var_binds:
                results.append((str(vb[0]), vb[1]))
        return results

    def test(self):
        try:
            return self.get(SYSTEM_OIDS["sysDescr"]) is not None
        except Exception:
            return False

    def get_system_info(self):
        info = {}
        for name, oid in SYSTEM_OIDS.items():
            try:
                val = self.get(oid)
                if name == "sysUpTime":
                    info[name] = str(timedelta(seconds=int(val) / 100))
                else:
                    info[name] = str(val)
            except Exception as e:
                info[name] = "ERROR: " + str(e)
        return info

    def get_poe_general(self):
        result = {}
        for name, base_oid in POE_MAIN_OIDS.items():
            try:
                rows = self.walk(base_oid)
                if rows:
                    val = int(rows[0][1])
                    if name == "pethMainPseOperStatus":
                        result[name] = PSE_STATUS_MAP.get(val, str(val))
                    else:
                        result[name] = val
            except Exception:
                result[name] = "N/A"
        return result


# ==============================================================
# WEB CLIENT
# ==============================================================
class WebPoEClient:
    def __init__(self, config):
        self.base_url = "http://" + config["host"]
        self.cgi_url = self.base_url + "/cgi-bin/dispatcher.cgi"
        self.user = config["web_user"]
        self.password = config["web_pass"]
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/146.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
            "Connection": "keep-alive",
        })
        self._logged_in = False

    def login(self):
        try:
            resp = self.session.post(
                self.cgi_url + "?cmd=1",
                data={"username": self.user, "password": self.password, "login": "1"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": self.base_url,
                    "Referer": self.cgi_url + "?cmd=0",
                },
                timeout=10, allow_redirects=True,
            )
            hid = self.session.cookies.get("hid")
            if hid:
                resp_poe = self.session.get(
                    self.cgi_url + "?cmd=9216",
                    headers={"Referer": self.cgi_url + "?cmd=9"},
                    timeout=10,
                )
                if resp_poe.status_code == 200 and "poeDelivering" in resp_poe.text:
                    self._logged_in = True
                    return True
            if not self._logged_in:
                set_cookie = resp.headers.get("Set-Cookie", "")
                hid_match = re.search("hid=([0-9a-fA-F]+)", set_cookie)
                if hid_match:
                    self.session.cookies.set("hid", hid_match.group(1))
                    self._logged_in = True
                    return True
            return False
        except Exception as e:
            print("  Error login: " + str(e))
            return False

    def _ensure_login(self):
        if not self._logged_in:
            if not self.login():
                raise ConnectionError("No se pudo hacer login web")

    def _extract_js_array(self, html, var_name):
        pattern = "var " + var_name + " = new Array\\(([^)]+)\\)"
        m = re.search(pattern, html)
        if m:
            return [v.strip() for v in m.group(1).split(",")]
        return []

    def _extract_js_var(self, html, var_name):
        pattern = "var " + var_name + " = ([^;\\n]+)"
        m = re.search(pattern, html)
        if m:
            return m.group(1).strip()
        return None

    def _get_poe_page(self):
        self._ensure_login()
        resp = self.session.get(
            self.cgi_url + "?cmd=9216",
            headers={"Referer": self.cgi_url + "?cmd=9"},
            timeout=10,
        )
        if resp.status_code == 200 and "poeDelivering" in resp.text:
            return resp.text
        self._logged_in = False
        self._ensure_login()
        resp = self.session.get(
            self.cgi_url + "?cmd=9216",
            headers={"Referer": self.cgi_url + "?cmd=9"},
            timeout=10,
        )
        if resp.status_code == 200 and "poeDelivering" in resp.text:
            return resp.text
        return None

    def fetch_poe_data(self):
        html = self._get_poe_page()
        if not html:
            return None

        data = {
            "numPorts":     int(self._extract_js_var(html, "numPorts") or 8),
            "powerBudget":  int(self._extract_js_var(html, "powerBudget") or 0),
            "poeAdmin":     int(self._extract_js_var(html, "poeAdmin") or 0),
            "poeMode":      int(self._extract_js_var(html, "poeMode") or 0),
            "maxBudget":    int(self._extract_js_var(html, "MaxBudget") or 0),
            "temperature0": self._extract_js_var(html, "poeTemperature0"),
            "temperature1": self._extract_js_var(html, "poeTemperature1"),
        }

        arrays = {}
        for name in ["poeDelivering", "poeConsumption", "poeAllocation",
                      "poeEnabled", "poePriority", "poeClass",
                      "poeInline", "poePDType", "poeExtend", "poeProfile"]:
            arrays[name] = self._extract_js_array(html, name)

        ports = []
        for i in range(data["numPorts"]):
            port = {
                "port":        i + 1,
                "enabled":     POE_MODE_MAP.get(int(arrays["poeEnabled"][i]), "?") if i < len(arrays["poeEnabled"]) else "?",
                "current_mA":  int(arrays["poeDelivering"][i]) if i < len(arrays["poeDelivering"]) else 0,
                "power_W":     int(arrays["poeConsumption"][i]) / 10 if i < len(arrays["poeConsumption"]) else 0,
                "max_W":       int(arrays["poeAllocation"][i]) / 10 if i < len(arrays["poeAllocation"]) else 0,
                "priority":    PRIORITY_MAP.get(int(arrays["poePriority"][i]), "?") if i < len(arrays["poePriority"]) else "?",
                "pd_class":    int(arrays["poeClass"][i]) if i < len(arrays["poeClass"]) else 0,
                "inline_mode": INLINE_MAP.get(int(arrays["poeInline"][i]), "?") if i < len(arrays["poeInline"]) else "?",
                "pd_type":     PD_TYPE_MAP.get(int(arrays["poePDType"][i]), "?") if i < len(arrays["poePDType"]) else "?",
                "extend":      "On" if i < len(arrays["poeExtend"]) and arrays["poeExtend"][i] == "1" else "Off",
            }
            if port["pd_class"] == 255:
                port["pd_class"] = "--"
            ports.append(port)

        data["ports"] = ports
        return data

    def set_port_state(self, port_number, enable):
        if port_number < 1 or port_number > 8:
            print("  Port" + str(port_number) + ": Error - puerto invalido")
            return False
        try:
            html = self._get_poe_page()
            if not html:
                print("  Port" + str(port_number) + ": Error - no se pudo leer estado")
                return False

            idx = port_number - 1
            poe_enabled    = self._extract_js_array(html, "poeEnabled")
            poe_priority   = self._extract_js_array(html, "poePriority")
            poe_allocation = self._extract_js_array(html, "poeAllocation")
            poe_inline     = self._extract_js_array(html, "poeInline")
            poe_pd_type    = self._extract_js_array(html, "poePDType")
            poe_extend     = self._extract_js_array(html, "poeExtend")
            poe_profile    = self._extract_js_array(html, "poeProfile")

            old_val = poe_enabled[idx] if idx < len(poe_enabled) else "?"
            new_val = "1" if enable else "0"
            old_str = POE_MODE_MAP.get(int(old_val), old_val)
            new_str = "Enable" if enable else "Disable"
            poe_enabled[idx] = new_val

            payload = {
                "cmd":         "9217",
                "enAdmin":     self._extract_js_var(html, "poeAdmin") or "0",
                "poeMode":     self._extract_js_var(html, "poeMode") or "1",
                "opt":         self._extract_js_var(html, "OTP_config") or "150",
                "powerbudget": self._extract_js_var(html, "powerBudget") or "240",
            }

            for i in range(len(poe_enabled)):
                payload["poe_en_" + str(i)]         = poe_enabled[i]
                payload["poe_profile_" + str(i)]    = poe_profile[i] if i < len(poe_profile) else "0"
                payload["poe_inline_" + str(i)]     = poe_inline[i] if i < len(poe_inline) else "3"
                payload["poe_pd_type_" + str(i)]    = poe_pd_type[i] if i < len(poe_pd_type) else "0"
                payload["poe_extend_" + str(i)]     = poe_extend[i] if i < len(poe_extend) else "0"
                payload["poe_priority_" + str(i)]   = poe_priority[i] if i < len(poe_priority) else "0"
                alloc_raw = int(poe_allocation[i]) if i < len(poe_allocation) else 950
                payload["poe_allocation_" + str(i)] = str(int(alloc_raw / 10))

            self.session.post(
                self.cgi_url,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": self.base_url,
                    "Referer": self.cgi_url + "?cmd=9216",
                },
                timeout=10, allow_redirects=True,
            )

            time.sleep(1)
            html_check = self._get_poe_page()
            if html_check:
                new_enabled = self._extract_js_array(html_check, "poeEnabled")
                actual = new_enabled[idx] if idx < len(new_enabled) else "?"
                expected = "1" if enable else "0"
                if actual == expected:
                    print("  Port" + str(port_number) + ": " + old_str + " -> " + new_str + " : OK")
                    return True
                else:
                    print("  Port" + str(port_number) + ": " + old_str + " -> " + new_str + " : FAIL")
                    return False
            print("  Port" + str(port_number) + ": " + old_str + " -> " + new_str + " : OK")
            return True
        except Exception as e:
            print("  Port" + str(port_number) + ": Error - " + str(e))
            return False

    def restart_port(self, port_number, wait=5):
        print("  Port" + str(port_number) + ": Restart (espera " + str(wait) + "s)...")
        if self.set_port_state(port_number, False):
            time.sleep(wait)
            return self.set_port_state(port_number, True)
        return False


# ==============================================================
# DISPLAY
# ==============================================================
def header(title):
    print("")
    print("=" * 72)
    print("  " + title)
    print("=" * 72)


def show_dict(data):
    mx = max(len(str(k)) for k in data) if data else 0
    for k, v in data.items():
        pad = " " * (mx - len(str(k)) + 2)
        print("  " + str(k) + pad + ": " + str(v))


def power_bar(consumed, total, width=40):
    if total <= 0:
        return
    pct = min((consumed / total) * 100, 100)
    filled = int(width * pct / 100)
    bar = "X" * filled + "." * (width - filled)
    print("  [" + bar + "] " + "{:.1f}".format(pct) + "%")
    print("  " + str(consumed) + "W de " + str(total) + "W usados")


def show_port_table(ports, compact=False):
    if not ports:
        print("  (sin datos)")
        return

    if compact:
        print("  Port  Estado       mA   Watts")
        print("  " + "-" * 30)
        for p in ports:
            ind = ">" if p["current_mA"] > 0 else " "
            line = " " + ind
            line += str(p["port"]).ljust(6)
            line += str(p["enabled"]).ljust(9)
            line += str(p["current_mA"]).rjust(5)
            line += ("%.1f" % p["power_W"]).rjust(7)
            print(line)
        total_ma = sum(p["current_mA"] for p in ports)
        total_w = sum(p["power_W"] for p in ports)
        print("  " + "-" * 30)
        print("  TOTAL".ljust(16) + str(total_ma).rjust(5) + ("%.1f" % total_w).rjust(7))
    else:
        print("  Port  Estado       mA    Watts    Max W Prioridad  PD Type    Inline")
        print("  " + "-" * 70)
        for p in ports:
            active = p["current_mA"] > 0 or p["power_W"] > 0
            ind = ">>>" if active else "   "
            line = ind
            line += str(p["port"]).ljust(6)
            line += str(p["enabled"]).ljust(9)
            line += str(p["current_mA"]).rjust(7)
            line += ("%.1f" % p["power_W"]).rjust(9)
            line += ("%.1f" % p["max_W"]).rjust(9)
            line += " " + str(p["priority"]).ljust(11)
            line += str(p["pd_type"]).ljust(11)
            line += str(p["inline_mode"]).ljust(8)
            print(line)
        print("  " + "-" * 70)


def show_port_detail(port):
    header("Puerto " + str(port["port"]) + " - Detalle")
    show_dict({
        "Estado PoE":     port["enabled"],
        "Corriente":      str(port["current_mA"]) + " mA",
        "Potencia":       str(port["power_W"]) + " W",
        "Max asignado":   str(port["max_W"]) + " W",
        "Prioridad":      port["priority"],
        "PD Type":        port["pd_type"],
        "Inline Mode":    port["inline_mode"],
        "PD Class":       port["pd_class"],
        "Extend Mode":    port["extend"],
        "Alimentando PD": "SI" if port["current_mA"] > 0 else "NO",
    })


# ==============================================================
# COMMANDS
# ==============================================================
def connect():
    snmp = SNMPClient(SWITCH_CONFIG)
    if not snmp.test():
        print("  [ERROR] SNMP no responde")
        sys.exit(1)
    web = WebPoEClient(SWITCH_CONFIG)
    if not web.login():
        print("  [ERROR] Login web fallido")
        sys.exit(1)
    return snmp, web


def cmd_status():
    snmp, web = connect()
    poe_snmp = snmp.get_poe_general()
    nominal = poe_snmp.get("pethMainPsePower", 0)
    consumo = poe_snmp.get("pethMainPseConsumptionPower", 0)
    poe_data = web.fetch_poe_data()
    pct = 0
    if isinstance(nominal, int) and isinstance(consumo, int) and nominal > 0:
        pct = consumo / nominal * 100
    temp0 = poe_data["temperature0"] if poe_data else "?"
    temp1 = poe_data["temperature1"] if poe_data else "?"
    header("PoE Status - " + SWITCH_CONFIG["host"])
    pse = poe_snmp.get("pethMainPseOperStatus", "N/A")
    print("  PSE: " + str(pse) + "  |  Consumo: " + str(consumo) + "W de " + str(nominal)
          + "W usando el " + "%.1f" % pct + "% y Temp: " + str(temp0) + "C / " + str(temp1) + "C")
    if poe_data:
        show_port_table(poe_data["ports"])


def cmd_ports():
    _, web = connect()
    poe_data = web.fetch_poe_data()
    if poe_data:
        header("Puertos PoE - Detalle completos")
        show_port_table(poe_data["ports"], compact=False)


def cmd_port(port_num):
    _, web = connect()
    poe_data = web.fetch_poe_data()
    if poe_data:
        idx = port_num - 1
        if 0 <= idx < len(poe_data["ports"]):
            show_port_detail(poe_data["ports"][idx])
        else:
            print("  Puerto " + str(port_num) + " no existe (rango 1-" + str(poe_data["numPorts"]) + ")")


def cmd_power():
    snmp, web = connect()
    poe_snmp = snmp.get_poe_general()
    nominal = poe_snmp.get("pethMainPsePower", 0)
    consumo = poe_snmp.get("pethMainPseConsumptionPower", 0)
    header("Consumo de Potencia")
    show_dict({
        "PSE Status":       poe_snmp.get("pethMainPseOperStatus", "N/A"),
        "Potencia nominal": str(nominal) + " W",
        "Consumo total":    str(consumo) + " W",
    })
    if isinstance(nominal, int) and isinstance(consumo, int):
        power_bar(consumo, nominal)
    poe_data = web.fetch_poe_data()
    if poe_data:
        print("")
        print("  Port      mA    Watts")
        print("  " + "-" * 24)
        for p in poe_data["ports"]:
            ind = ">" if p["power_W"] > 0 else " "
            line = " " + ind + str(p["port"]).ljust(7)
            line += str(p["current_mA"]).rjust(7)
            line += ("%.1f" % p["power_W"]).rjust(9)
            print(line)
        total_w = sum(p["power_W"] for p in poe_data["ports"])
        total_ma = sum(p["current_mA"] for p in poe_data["ports"])
        print("  " + "-" * 24)
        print("  Total".ljust(9) + str(total_ma).rjust(7) + ("%.1f" % total_w).rjust(9))


def cmd_system():
    snmp, web = connect()
    header("Informacion del Sistema")
    show_dict(snmp.get_system_info())
    poe_data = web.fetch_poe_data()
    if poe_data:
        print("")
        show_dict({
            "Puertos PoE":    poe_data["numPorts"],
            "Power Budget":   str(poe_data["powerBudget"]) + " W",
            "Max Budget":     str(poe_data["maxBudget"]) + " W",
            "Admin":          "Enabled" if poe_data["poeAdmin"] == 0 else "Disabled",
            "Modo":           "Consumption" if poe_data["poeMode"] == 1 else "Allocation",
            "Temperatura 0":  str(poe_data["temperature0"]) + " C",
            "Temperatura 1":  str(poe_data["temperature1"]) + " C",
        })


def cmd_watch(interval=5):
    snmp, web = connect()
    print("  Monitoreando cada " + str(interval) + "s... (Ctrl+C para detener)")
    try:
        while True:
            os.system("cls" if os.name == "nt" else "clear")
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            poe_snmp = snmp.get_poe_general()
            nominal = poe_snmp.get("pethMainPsePower", 0)
            consumo = poe_snmp.get("pethMainPseConsumptionPower", 0)
            pct = 0
            if isinstance(nominal, int) and isinstance(consumo, int) and nominal > 0:
                pct = consumo / nominal * 100
            poe_data = web.fetch_poe_data()
            temp0 = poe_data["temperature0"] if poe_data else "?"
            temp1 = poe_data["temperature1"] if poe_data else "?"
            header("PoE Watch - " + SWITCH_CONFIG["host"] + "  |  " + now)
            pse = poe_snmp.get("pethMainPseOperStatus", "?")
            print("  PSE: " + str(pse) + "  |  Consumo: " + str(consumo) + "W de " + str(nominal)
                  + "W usando el " + "%.1f" % pct + "% y Temp: " + str(temp0) + "C / " + str(temp1) + "C")
            print("  Refresh: " + str(interval) + "s  |  Ctrl+C = salir")
            if poe_data:
                show_port_table(poe_data["ports"])
            time.sleep(interval)
    except KeyboardInterrupt:
        print("")
        print("  Monitoreo detenido.")


def cmd_csv():
    snmp, web = connect()
    poe_snmp = snmp.get_poe_general()
    poe_data = web.fetch_poe_data()
    if not poe_data:
        print("  Error obteniendo datos")
        return
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = "poe_export_" + now + ".csv"
    with open(filename, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "total_W", "budget_W", "temp0_C", "temp1_C"])
        w.writerow([now,
                     poe_snmp.get("pethMainPseConsumptionPower", 0),
                     poe_snmp.get("pethMainPsePower", 0),
                     poe_data["temperature0"],
                     poe_data["temperature1"]])
        w.writerow([])
        w.writerow(["port", "enabled", "current_mA", "power_W", "max_W",
                     "priority", "pd_type", "inline_mode", "pd_class", "extend"])
        for p in poe_data["ports"]:
            w.writerow([p["port"], p["enabled"], p["current_mA"],
                        p["power_W"], p["max_W"], p["priority"],
                        p["pd_type"], p["inline_mode"], p["pd_class"], p["extend"]])
    print("  Exportado: " + filename)


def cmd_log():
    snmp, web = connect()
    poe_snmp = snmp.get_poe_general()
    poe_data = web.fetch_poe_data()
    if not poe_data:
        print("  Error obteniendo datos")
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.exists(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            cols = ["timestamp", "total_W", "budget_W", "temp0", "temp1"]
            for i in range(poe_data["numPorts"]):
                cols.extend(["p" + str(i + 1) + "_mA", "p" + str(i + 1) + "_W"])
            w.writerow(cols)
        row = [now,
               poe_snmp.get("pethMainPseConsumptionPower", 0),
               poe_snmp.get("pethMainPsePower", 0),
               poe_data["temperature0"],
               poe_data["temperature1"]]
        for p in poe_data["ports"]:
            row.extend([p["current_mA"], p["power_W"]])
        w.writerow(row)
    print("  Registrado en " + LOG_FILE + ": " + now)


def cmd_help():
    print("")
    print("  PLANET IGS-4215-8UP2T2S - PoE CLI Tool (poeTest)")
    print("  Switch: " + SWITCH_CONFIG["host"])
    print("")
    print("  LECTURA (-r):")
    print("    poeTest -r status              Resumen rapido")
    print("    poeTest -r ports               Tabla detallada de puertos")
    print("    poeTest -r Port3               Detalle del puerto 3")
    print("    poeTest -r power               Solo datos de potencia")
    print("    poeTest -r system              Info del sistema")
    print("    poeTest -r watch               Refresh cada 5 segundos")
    print("    poeTest -r watch,10            Refresh cada 10 segundos")
    print("    poeTest -r csv                 Exportar snapshot a CSV")
    print("    poeTest -r log                 Agregar linea al log continuo")
    print("")
    print("  ESCRITURA (-w):")
    print("    poeTest -w Port3,1             Habilitar puerto 3")
    print("    poeTest -w Port3,0             Deshabilitar puerto 3")
    print("    poeTest -w Port3,r             Reiniciar puerto 3 (off/on 5s)")
    print("    poeTest -w Port3,r,10          Reiniciar puerto 3, espera 10s")
    print("    poeTest -w Port1,1 Port5,0     Multiples puertos a la vez")
    print("    poeTest -w Port1,r Port2,r     Reiniciar multiples puertos")
    print("")
    print("  FORMATO -w:")
    print("    Port[1-8],[0|1|r]              0=disable, 1=enable, r=restart")
    print("    Port[1-8],r,[seg]              restart con espera personalizada")
    print("")
    print("  AYUDA:")
    print("    poeTest help")
    print("")
    print("  EJEMPLOS:")
    print("    poeTest -r status")
    print("    poeTest -r watch,3")
    print("    poeTest -w Port1,1")
    print("    poeTest -w Port5,0 Port6,0")
    print("    poeTest -w Port3,r,15")
    print("")


# ==============================================================
# MAIN
# ==============================================================
def main():
    if len(sys.argv) < 2:
        cmd_help()
        return

    arg1 = sys.argv[1].lower()

    if arg1 in ("help", "-h", "--help", "?"):
        cmd_help()
        return

    if arg1 not in ("-r", "-w"):
        print("  [ERROR] Bandera requerida: -r (lectura) o -w (escritura)")
        print("  Usa 'poeTest help' para ver los comandos disponibles")
        return

    flag = arg1

    if flag == "-r":
        if len(sys.argv) < 3:
            print("  [ERROR] Falta el comando despues de -r")
            print("  Usa 'poeTest help' para ver los comandos disponibles")
            return

        cmd = sys.argv[2].lower()
        args = sys.argv[3:]
        read_cmds = ["status", "ports", "power", "system", "csv", "log"]

        # Verificar si es PortN
        port_match = re.match("port(\\d+)", cmd)

        if port_match:
            port_num = int(port_match.group(1))
            if port_num < 1 or port_num > 8:
                print("  [ERROR] Puerto " + str(port_num) + " fuera de rango (1-8)")
                return
            cmd_port(port_num)
            return
        elif cmd.startswith("watch"):
            parts = cmd.split(",")
            interval = int(parts[1]) if len(parts) > 1 else 5
            cmd_watch(interval)
            return
        elif cmd not in read_cmds:
            print("  [ERROR] '" + cmd + "' no es un comando de lectura")
            print("  Comandos -r: " + ", ".join(read_cmds) + ", Port[1-8], watch[,seg]")
            return

        if cmd == "status":
            cmd_status()
        elif cmd == "ports":
            cmd_ports()
        elif cmd == "power":
            cmd_power()
        elif cmd == "system":
            cmd_system()
        elif cmd == "csv":
            cmd_csv()
        elif cmd == "log":
            cmd_log()

    elif flag == "-w":
        args = sys.argv[2:]

        if not args:
            print("  [ERROR] Falta el parametro de puerto")
            print("  Formato: poeTest -w Port[1-8],[0|1|r]")
            print("  Ejemplo: poeTest -w Port3,1")
            return

        _, web = connect()

        for arg in args:
            arg_upper = arg.upper()
            match = re.match("PORT(\\d+),(.+)", arg_upper)

            if not match:
                print("  [ERROR] Formato invalido: '" + arg + "'")
                print("  Formato: Port[1-8],[0|1|r]  Ejemplo: Port3,1")
                return

            port_num = int(match.group(1))
            action_str = match.group(2)

            if port_num < 1 or port_num > 8:
                print("  [ERROR] Puerto " + str(port_num) + " fuera de rango (1-8)")
                return

            if action_str == "1":
                web.set_port_state(port_num, True)
            elif action_str == "0":
                web.set_port_state(port_num, False)
            elif action_str.startswith("R"):
                parts = action_str.split(",")
                wait = int(parts[1]) if len(parts) > 1 else 5
                web.restart_port(port_num, wait)
            else:
                print("  [ERROR] Accion invalida: '" + action_str + "' en '" + arg + "'")
                print("  Acciones: 0=disable, 1=enable, r=restart")
                return

        print("")


if __name__ == "__main__":
    main()
