#!/usr/local/bin/python3

import datetime
import json
import logging
import optparse
import os
import random
import re
import string
import sys
import time
import unicodedata
import urllib.parse
from itertools import count

import json5
import requests
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import JavascriptException
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

if __name__ != "__main__":
    from pyvirtualdisplay import Display

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)


class RenfeChecker:
    SEARCH_URL = "https://venta.renfe.com/vol/buscarTren.do?Idioma=es&Pais=ES"
    DWR_ENDPOINT = "https://venta.renfe.com/vol/dwr/call/plaincall/"
    SYSTEM_ID_URL = f"{DWR_ENDPOINT}__System.generateId.dwr"
    UPDATE_SESSION_URL = f"{DWR_ENDPOINT}buyEnlacesManager.actualizaObjetosSesion.dwr"
    TRAIN_LIST_URL = f"{DWR_ENDPOINT}trainEnlacesManager.getTrainsList.dwr"

    def __init__(self, display=True):
        if display:
            self._display = Display(visible=0, size=(800, 600))
            self._display.start()
        else:
            self._display = None

        options = Options()
        options.set_preference("dom.webnotifications.enabled", False)
        options.set_preference("media.autoplay.default", 5)
        self.driver = webdriver.Firefox(options=options)
        self.driver.set_page_load_timeout(60)
        self._wait = WebDriverWait(self.driver, 30)
        self._station_lookup = self._load_station_lookup()
        #self.driver.maximize_window()
        self.driver.get("https://www.renfe.com")

    STATION_ALIASES = {
        "MADRID-PUERTA DE ATOCHA": "MADRID PTA. ATOCHA - ALMUDENA GRANDES",
        "SEVILLA-SANTA JUSTA": "SEVILLA-SANTA JUSTA",
        "SEVILLA-SAN BERNARDO": "SEVILLA-SAN BERNARDO",
        "SEVILLA-VIRGEN DEL ROCIO": "SEVILLA-VIRGEN DEL ROCÍO",
        "BARCELONA-SANTS": "BARCELONA-SANTS",
        "VALENCIA JOAQUIN SOROLLA": "VALENCIA JOAQUÍN SOROLLA",
        "ALICANTE/ALACANT": "Alicante/Alacant",
        "MALAGA MARIA ZAMBRANO": "MÁLAGA MARÍA ZAMBRANO",
    }

    def _normalize_station(self, station):
        if station is None:
            return ""
        key = station.strip().upper()
        mapped = self.STATION_ALIASES.get(key, station.strip())
        return mapped.strip()

    def _normalize_station_key(self, station):
        normalized = unicodedata.normalize("NFKD", station or "")
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        normalized = normalized.upper()
        return re.sub(r"[^A-Z0-9]", "", normalized)

    def _load_station_lookup(self):
        stations_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "stations.json"))
        with open(stations_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError("stations.json must be a JSON object")

        lookup = {}
        for station_name, station_data in raw.items():
            if not isinstance(station_data, dict):
                continue
            station_code = str(station_data.get("cdgoEstacion") or "").strip()
            key = self._normalize_station_key(station_name)
            if key == "":
                continue
            lookup[key] = {"name": station_name, "code": station_code}
        return lookup

    def _resolve_station_metadata(self, station):
        normalized_name = self._normalize_station(station)
        key = self._normalize_station_key(normalized_name)
        if key == "":
            return None
        return self._station_lookup.get(key)

    @staticmethod
    def _create_search_id():
        return "_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(4))

    @staticmethod
    def _tokenify(number):
        token_chars = "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ*$"
        token = []
        remainder = number
        while remainder > 0:
            token.append(token_chars[remainder & 0x3F])
            remainder //= 64
        return "".join(token)

    @classmethod
    def _create_script_session_id(cls, dwr_token):
        now_token = cls._tokenify(int(datetime.datetime.now().timestamp() * 1000))
        random_token = cls._tokenify(int(random.random() * 1e16))
        return f"{dwr_token}/{now_token}-{random_token}"

    @staticmethod
    def _extract_dwr_token(response_text):
        match = re.search(r'r\.handleCallback\("[^"]+","[^"]+","([^"]+)"\)', response_text)
        if match:
            return match.group(1)
        raise ValueError("Could not extract DWR token")

    @staticmethod
    def _extract_train_list(response_text):
        match = re.search(r"r\.handleCallback\([^,]+,\s*[^,]+,\s*(\{.*\})\);", response_text, re.DOTALL)
        if match is None:
            raise ValueError("Could not parse DWR train list")
        return json5.loads(match.group(1))

    def _create_search_payload(self, origin, destination, dat_go, dat_ret, plaza_h):
        return {
            "tipoBusqueda": "autocomplete",
            "currenLocation": "menuBusqueda",
            "vengoderenfecom": "SI",
            "desOrigen": origin["name"],
            "desDestino": destination["name"],
            "cdgoOrigen": origin["code"],
            "cdgoDestino": destination["code"],
            "idiomaBusqueda": "ES",
            "FechaIdaSel": dat_go,
            "FechaVueltaSel": dat_ret or "",
            "_fechaIdaVisual": dat_go,
            "_fechaVueltaVisual": dat_ret or "",
            "adultos_": "1",
            "ninos_": "0",
            "ninosMenores": "0",
            "codPromocional": "",
            "plazaH": "true" if plaza_h else "false",
            "sinEnlace": "false",
            "asistencia": "false",
            "franjaHoraI": "",
            "franjaHoraV": "",
            "Idioma": "es",
            "Pais": "ES",
        }

    @staticmethod
    def _create_search_cookie(origin, destination):
        search = {
            "origen": {"code": origin["code"], "name": origin["name"]},
            "destino": {"code": destination["code"], "name": destination["name"]},
            "pasajerosAdultos": 1,
            "pasajerosNinos": 0,
            "pasajerosSpChild": 0,
        }
        return {"name": "Search", "value": str(search), "domain": ".renfe.com", "path": "/"}

    @staticmethod
    def _create_generate_id_payload(search_id, batch_id):
        page = f"page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D{search_id}\n" if search_id else "page=%2Fvol%2FbuscarTrenEnlaces.do\n"
        return (
            "callCount=1\n"
            "c0-scriptName=__System\n"
            "c0-methodName=generateId\n"
            "c0-id=0\n"
            f"batchId={next(batch_id)}\n"
            "instanceId=0\n"
            f"{page}"
            "scriptSessionId=\n"
            "windowName=\n"
        )

    @staticmethod
    def _create_update_session_payload(search_id, script_session_id, batch_id):
        return (
            "callCount=1\n"
            "windowName=\n"
            "c0-scriptName=buyEnlacesManager\n"
            "c0-methodName=actualizaObjetosSesion\n"
            "c0-id=0\n"
            f"c0-e1=string:{search_id}\n"
            "c0-e2=string:\n"
            "c0-param0=array:[reference:c0-e1,reference:c0-e2]\n"
            f"batchId={next(batch_id)}\n"
            "instanceId=0\n"
            f"page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D{search_id}\n"
            f"scriptSessionId={script_session_id}\n"
        )

    @staticmethod
    def _create_get_train_list_payload(dat_go, dat_ret, script_session_id, search_id, batch_id, plaza_h):
        departure_date = dat_go or ""
        return_date = dat_ret or ""
        trayecto = "I" if not dat_ret else "IV"
        return (
            "callCount=1\n"
            "windowName=\n"
            "c0-scriptName=trainEnlacesManager\n"
            "c0-methodName=getTrainsList\n"
            "c0-id=0\n"
            "c0-e1=string:false\n"
            "c0-e2=string:false\n"
            f"c0-e3=string:{'true' if plaza_h else 'false'}\n"
            "c0-e4=string:\n"
            "c0-e5=string:\n"
            "c0-e6=string:\n"
            "c0-e7=string:\n"
            f"c0-e8=string:{urllib.parse.quote_plus(departure_date)}\n"
            f"c0-e9=string:{urllib.parse.quote_plus(return_date)}\n"
            "c0-e10=string:1\n"
            "c0-e11=string:0\n"
            "c0-e12=string:0\n"
            f"c0-e13=string:{trayecto}\n"
            "c0-e14=string:\n"
            "c0-param0=Object_Object:{atendo:reference:c0-e1, sinEnlace:reference:c0-e2, "
            "plazaH:reference:c0-e3, tipoFranjaI:reference:c0-e4, tipoFranjaV:reference:c0-e5, "
            "horaFranjaIda:reference:c0-e6, horaFranjaVuelta:reference:c0-e7, fechaSalida:reference"
            ":c0-e8, fechaVuelta:reference:c0-e9, adultos:reference:c0-e10, ninos:reference:c0-e11,"
            " ninosMenores:reference:c0-e12, trayecto:reference:c0-e13, idaVuelta:reference:c0-e14}\n"
            f"batchId={next(batch_id)}\n"
            "instanceId=0\n"
            f"page=%2Fvol%2FbuscarTrenEnlaces.do%3Fc%3D{search_id}\n"
            f"scriptSessionId={script_session_id}\n"
        )

    @staticmethod
    def _dwr_base_available(train):
        reason = str(train.get("razonNoDisponible") or "")
        fare = train.get("tarifaMinima")
        return (not bool(train.get("completo"))) and reason in ("", "8") and fare not in (None, "", "NaN")

    def _is_dwr_train_available(self, train, plaza_h):
        plaza_h_only = bool(train.get("soloPlazaH"))
        base_available = self._dwr_base_available(train)
        if plaza_h:
            return base_available and plaza_h_only
        return base_available and (not plaza_h_only)

    def _parse_dwr_trains(self, payload, plaza_h):
        if not isinstance(payload, dict):
            return []
        outbound = []
        train_groups = payload.get("listadoTrenes") or []
        if not isinstance(train_groups, list) or len(train_groups) == 0:
            return []

        for train_group in train_groups:
            train_list = train_group.get("listviajeViewEnlaceBean") or []
            if not isinstance(train_list, list):
                continue
            for train in train_list:
                departure = self._parse_time(str(train.get("horaSalida") or ""))
                arrival = self._parse_time(str(train.get("horaLlegada") or ""))
                duration_minutes = train.get("duracionViajeTotalEnMinutos") or 0
                try:
                    duration_minutes = int(duration_minutes)
                except (TypeError, ValueError):
                    duration_minutes = 0
                fare = train.get("tarifaMinima")
                price = self._extract_price(str(fare)) if fare not in (None, "") else ""
                train_type = train.get("tipoTrenUno") or train.get("tipoTren") or "N/A"
                transfer = int(train.get("numTrenes") or 1) > 1
                plaza_h_only = bool(train.get("soloPlazaH"))
                outbound.append(
                    {
                        "SALIDA": departure,
                        "LLEGADA": arrival,
                        "TIPO": train_type,
                        "PRECIO": price,
                        "DURACION": float(duration_minutes) / 60.0 if duration_minutes > 0 else 0,
                        "CLASE": "",
                        "TARIFA": str(train.get("descTarifaMinima") or ""),
                        "DISPONIBLE": self._is_dwr_train_available(train, plaza_h),
                        "PLAZA_H_ONLY": plaza_h_only,
                        "TRANSFER": transfer,
                        "TRANSFER_TIME": "",
                    }
                )
        return outbound

    def close(self):
        self.driver.quit()
        if self._display is not None:
            self._display.stop()

    def check_trip(self, orig, dest, dat_go, dat_ret=None, plaza_h=False):
        try:
            dwr_trains = self._check_trip_dwr(orig, dest, dat_go, dat_ret, plaza_h)
            if dwr_trains is not None:
                if len(dwr_trains) == 0:
                    logger.info("DWR returned no trains for %s -> %s (%s)", orig, dest, dat_go)
                    return False, None
                logger.info("DWR returned %d trains for %s -> %s (%s)", len(dwr_trains), orig, dest, dat_go)
                return True, dwr_trains
        except Exception:
            logger.exception("DWR lookup failed for %s -> %s (%s). Falling back to Selenium.", orig, dest, dat_go)

        return self._check_trip_selenium(orig, dest, dat_go, dat_ret, plaza_h)

    def _check_trip_dwr(self, orig, dest, dat_go, dat_ret=None, plaza_h=False):
        origin_meta = self._resolve_station_metadata(orig)
        destination_meta = self._resolve_station_metadata(dest)
        if origin_meta is None or destination_meta is None:
            logger.warning("Could not resolve station metadata for DWR query: %s -> %s", orig, dest)
            return None
        if origin_meta["code"] == "" or destination_meta["code"] == "":
            logger.warning("Missing station code for DWR query: %s -> %s", orig, dest)
            return None

        search_id = self._create_search_id()
        batch_id = count()
        session = requests.Session()
        session.headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Connection": "keep-alive",
        }

        cookie = self._create_search_cookie(origin_meta, destination_meta)
        session.cookies.set(**cookie)

        search_payload = self._create_search_payload(origin_meta, destination_meta, dat_go, dat_ret, plaza_h)
        response = session.post(self.SEARCH_URL, data=search_payload, allow_redirects=True, timeout=30)
        response.raise_for_status()

        generate_payload = self._create_generate_id_payload(search_id, batch_id)
        session.post(self.SYSTEM_ID_URL, data=generate_payload, timeout=30).raise_for_status()
        generate_payload = self._create_generate_id_payload(search_id, batch_id)
        token_response = session.post(self.SYSTEM_ID_URL, data=generate_payload, timeout=30)
        token_response.raise_for_status()

        dwr_token = self._extract_dwr_token(token_response.text)
        session.cookies.set("DWRSESSIONID", dwr_token, path="/vol", domain="venta.renfe.com")
        script_session_id = self._create_script_session_id(dwr_token)

        update_payload = self._create_update_session_payload(search_id, script_session_id, batch_id)
        session.post(self.UPDATE_SESSION_URL, data=update_payload, timeout=30).raise_for_status()

        train_payload = self._create_get_train_list_payload(
            dat_go,
            dat_ret,
            script_session_id,
            search_id,
            batch_id,
            plaza_h,
        )
        trains_response = session.post(self.TRAIN_LIST_URL, data=train_payload, timeout=30)
        trains_response.raise_for_status()

        trains_raw = self._extract_train_list(trains_response.text)
        return self._parse_dwr_trains(trains_raw, plaza_h)

    def _check_trip_selenium(self, orig, dest, dat_go, dat_ret=None, plaza_h=False):
        try:
            self.driver.get("https://www.renfe.com")
            self._wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            self._checkTrains(orig, dest, dat_go, dat_ret, plaza_h)
            if self._areTrainsAvailable():
                return True, self._getTrainsDF()
            return False, None
        except Exception:
            logger.exception(
                "Error checking trip %s -> %s (%s, %s)",
                orig,
                dest,
                dat_go,
                dat_ret,
            )
            self._dump_debug_files()
            return False, None

    def _dump_debug_files(self):
        try:
            self.driver.save_screenshot("/data/debug.png")
            with open("/data/debug.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
        except Exception:
            logger.exception("Could not write debug artifacts to /data")

    def _get_search_action_url(self):
        action = self.driver.execute_script(
            """
            const form = document.querySelector("form[action*='buscarTren.do']");
            if (form && form.action) {
                return form.action;
            }
            const host = document.querySelector("rf-header-topbar-search-integration");
            if (host) {
                return host.getAttribute("url-search-ticket") || null;
            }
            return null;
            """
        )
        return action or "https://venta.renfe.com/vol/buscarTren.do?Idioma=es&Pais=ES"

    def _post_search_payload(self, action_url, payload):
        self.driver.execute_script(
            """
            const actionUrl = arguments[0];
            const payload = arguments[1];

            const form = document.createElement("form");
            form.method = "POST";
            form.action = actionUrl;
            form.style.display = "none";

            Object.keys(payload).forEach((k) => {
                const input = document.createElement("input");
                input.type = "hidden";
                input.name = k;
                input.value = payload[k];
                form.appendChild(input);
            });

            document.body.appendChild(form);
            form.submit();
            """,
            action_url,
            payload,
        )

    def _submit_payload_to_dom_form(self, payload, plaza_h=False):
        return bool(
            self.driver.execute_script(
                """
                const payload = arguments[0];
                const plazaH = arguments[1];
                const form = document.querySelector("form[action*='buscarTren.do']");
                if (!form) {
                    return false;
                }

                for (const [key, rawValue] of Object.entries(payload)) {
                    const value = rawValue == null ? "" : String(rawValue);
                    let field = form.elements.namedItem(key);

                    if (field && typeof field.length === "number" && field.length > 0 && !field.tagName) {
                        field = field[0];
                    }
                    if (!field || ((field.tagName || "").toLowerCase() !== "input")) {
                        field = form.querySelector(`input[name="${key}"]`);
                    }
                    if (!field) {
                        field = document.createElement("input");
                        field.type = "hidden";
                        field.name = key;
                        form.appendChild(field);
                    }
                    field.value = value;
                    field.setAttribute("value", value);
                }

                if (plazaH) {
                    const checkbox = document.querySelector('input[type="checkbox"][name="plazaH"], input[type="checkbox"][aria-label*="Plaza H"], input[type="checkbox"][aria-label*="plaza h"]');
                    if (checkbox) {
                        checkbox.checked = true;
                        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
                    }
                }

                const submitButton = form.querySelector("button[type='submit'], input[type='submit']");
                if (submitButton) {
                    submitButton.disabled = false;
                }
                form.submit();
                return true;
                """,
                payload,
                plaza_h,
            )
        )

    def _submit_new_search_form(self, orig, dest, dat_go, dat_ret, plaza_h=False):
        orig_norm = self._normalize_station(orig)
        dest_norm = self._normalize_station(dest)
        ret_date = dat_ret if dat_ret else ""

        # Build direct search URL with query parameters
        # This bypasses the Shadow DOM form submission issue entirely
        from urllib.parse import quote
        params = {
            "Idioma": "es",
            "Pais": "ES",
            "desOrigen": orig_norm,
            "desDestino": dest_norm,
            "FechaIdaSel": dat_go,
            "FechaVueltaSel": ret_date,
            "adultos_": "1",
            "ninos_": "0",
            "plazaH": "true" if plaza_h else "false",
            "tipoBusqueda": "autocomplete",
        }
        query_string = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
        search_url = f"https://venta.renfe.com/vol/buscarTren.do?{query_string}"

        logger.debug("🌐 Direct navigation to search URL: %s", search_url)
        self.driver.get(search_url)

        try:
            # Wait for results page to load
            self._wait.until(
                lambda d: (
                    "buscartren.do" in d.current_url.lower()
                    or "venta.renfe.com" in d.current_url.lower()
                )
            )
            self._wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            logger.debug("✅ Results page loaded: %s", self.driver.current_url)
            return True
        except TimeoutException:
            logger.warning("❌ Timeout waiting for results page after direct navigation")
            # Fallback: try legacy form submission methods
            return self._legacy_submit_search_form(orig, dest, dat_go, dat_ret, plaza_h)

    def _legacy_submit_search_form(self, orig, dest, dat_go, dat_ret, plaza_h=False):
        """Fallback method using form submission for old Renfe DOM."""
        logger.debug("🔄 Falling back to legacy form submission")
        orig_norm = self._normalize_station(orig)
        dest_norm = self._normalize_station(dest)
        ret_date = dat_ret if dat_ret else ""
        payload = {
            "tipoBusqueda": "autocomplete",
            "currenLocation": "menuBusqueda",
            "vengoderenfecom": "SI",
            "desOrigen": orig_norm,
            "desDestino": dest_norm,
            "cdgoOrigen": "",
            "cdgoDestino": "",
            "idiomaBusqueda": "ES",
            "FechaIdaSel": dat_go,
            "FechaVueltaSel": ret_date,
            "_fechaIdaVisual": dat_go,
            "_fechaVueltaVisual": ret_date,
            "minPriceDeparture": "false",
            "minPriceReturn": "false",
            "adultos_": "1",
            "ninos_": "0",
            "ninosMenores": "0",
            "codPromocional": "",
            "plazaH": "true" if plaza_h else "false",
            "sinEnlace": "false",
            "conMascota": "false",
            "conBicicleta": "false",
            "asistencia": "false",
            "franjaHoraI": "",
            "franjaHoraV": "",
            "Idioma": "es",
            "Pais": "ES",
        }

        submitted = False
        for attempt in range(3):
            try:
                if self._submit_payload_to_dom_form(payload, plaza_h=plaza_h):
                    submitted = True
                    break
            except (StaleElementReferenceException, JavascriptException, WebDriverException) as ex:
                logger.debug("Retrying DOM submit after transient failure (%d/3): %s", attempt + 1, str(ex))
            time.sleep(0.5)

        if not submitted:
            action_url = self._get_search_action_url()
            self._post_search_payload(action_url, payload)

        try:
            self._wait.until(
                lambda d: (
                    "buscartren.do" in d.current_url.lower()
                    or "venta.renfe.com" in d.current_url.lower()
                )
            )
            self._wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
            return True
        except TimeoutException:
            logger.warning("Legacy search submit timeout for %s -> %s (%s)", orig, dest, dat_go)
            return False

    def _checkTrains(self, orig, dest, dat_go, dat_ret, plaza_h=False):
        if self._submit_new_search_form(orig, dest, dat_go, dat_ret, plaza_h):
            return

        # Legacy fallback for old Renfe DOM.
        self._fill_elem("IdDestino", dest)
        self._fill_elem("IdOrigen", orig)
        self._fill_elem("__fechaIdaVisual", dat_go)
        self._fill_elem("__fechaVueltaVisual", dat_ret)
        bt = self.driver.find_element(By.CLASS_NAME, "btn_home")
        bt.click()

    def _parse_time(self, txt):
        value = (txt or "").strip()
        for fmt in ("%H.%M", "%H:%M"):
            try:
                return datetime.datetime.strptime(value, fmt).time()
            except ValueError:
                pass
        raise ValueError("Could not parse time '%s'" % value)

    def _extract_price(self, txt):
        if not txt:
            return ""
        m = re.search(r"\d+[\.,]?\d*", txt)
        if not m:
            return ""
        return float(m.group(0).replace(",", "."))

    def _getTrainsDF(self):
        trayectos = []
        try:
            trenes_container = self.driver.find_element(By.ID, "listaTrenesTBodyIda")
            logger.debug("✅ Trains container found: listaTrenesTBodyIda")
        except NoSuchElementException:
            logger.warning("❌ Trains container not found: listaTrenesTBodyIda")
            return trayectos
        
        # New Renfe HTML: div.row.selectedTren (v2.0+) 
        # Old Renfe HTML fallback: tr.trayectoRow (legacy)
        rows = []
        try:
            rows = trenes_container.find_elements(By.XPATH, ".//div[contains(@class,'row') and contains(@class,'selectedTren')]")
            logger.debug(f"🔍 Found {len(rows)} trains using new selector (div.selectedTren)")
        except:
            logger.debug("ℹ️ New selector failed, trying legacy selector...")
            rows = trenes_container.find_elements(By.XPATH, ".//tr[contains(@class,'trayectoRow')]")
            logger.debug(f"🔍 Found {len(rows)} trains using legacy selector (tr.trayectoRow)")

        for idx, r in enumerate(rows):
            try:
                # New HTML: times are in h5 tags
                time_elems = r.find_elements(By.XPATH, ".//h5[contains(text(),'h')]")
                if len(time_elems) >= 2:
                    sal = time_elems[0].text.replace(" h", "").strip()
                    lle = time_elems[1].text.replace(" h", "").strip()
                    logger.debug(f"  🚂 Train {idx+1}: {sal} → {lle}")
                else:
                    # Fallback to legacy selectors
                    sal = r.find_element(By.XPATH, ".//td[@headers='colSalida']").text
                    lle = r.find_element(By.XPATH, ".//td[@headers='colLlegada']").text
                
                salT = self._parse_time(sal)
                lleT = self._parse_time(lle)
                toSec = lambda x: x.hour * 60 * 60 + x.minute * 60 + x.second
                dur = toSec(lleT) - toSec(salT)
                
                # Detect transfers (transbordos)
                row_aria = r.get_attribute("aria-label") or ""
                has_transfer_aria = "transbordo" in row_aria.lower()
                has_transfer_elem = len(r.find_elements(By.XPATH, ".//span[contains(@class,'enlace-tren')]")) > 0
                transfer_time_elem = r.find_elements(By.XPATH, ".//span[contains(@class,'enlace-tren-min')]")
                transfer_time = ""
                if transfer_time_elem:
                    transfer_time = transfer_time_elem[0].text.strip()
                
                has_transfer = has_transfer_aria or has_transfer_elem
                transfer_marker = "🔄 " if has_transfer else "   "
                
                # Determine availability
                row_text = r.text.lower()
                plaza_h_only = "solo plaza h" in row_text or "sólo plaza h" in row_text
                has_full_train_btn = len(r.find_elements(By.XPATH, ".//span[contains(text(),'Tren Completo')]")) > 0
                disp = not has_full_train_btn and (
                    "completo" not in row_text or plaza_h_only
                )
                
                # Try to get price from new structure
                precio = ""
                clase = ""
                tarifa = ""
                if disp:
                    try:
                        precio_txt = r.find_element(By.XPATH, ".//span[contains(@class,'precio-final')]").text
                        precio = self._extract_price(precio_txt)
                    except:
                        try:
                            precio_txt = r.find_element(By.XPATH, ".//td[@headers='colPrecio']").text
                            precio = self._extract_price(precio_txt)
                        except:
                            precio = ""
                    
                    try:
                        clase = r.find_element(By.XPATH, ".//td[@headers='colClase']").text
                    except:
                        clase = ""
                    
                    try:
                        tarifa = r.find_element(By.XPATH, ".//td[@headers='colTarifa']").text
                    except:
                        tarifa = ""
                
                trayectos.append(
                    {
                        "SALIDA": salT,
                        "LLEGADA": lleT,
                        "TIPO": "MD",  # Default, improve if needed
                        "PRECIO": precio,
                        "DURACION": float(dur) / 3600 if dur > 0 else 0,
                        "CLASE": clase,
                        "TARIFA": tarifa,
                        "DISPONIBLE": disp,
                        "PLAZA_H_ONLY": plaza_h_only,
                        "TRANSFER": has_transfer,
                        "TRANSFER_TIME": transfer_time,
                    }
                )
                transfer_info = f" (Transfer: {transfer_time})" if has_transfer else ""
                disp_marker = "✓" if disp else "✗"
                logger.debug(f"    {transfer_marker}{disp_marker} {sal} → {lle}, Duraciónं: {dur//3600}h{(dur%3600)//60}m, Plaza H: {plaza_h_only}{transfer_info}")
            except Exception as e:
                logger.warning(f"⚠️ Error parsing train {idx+1}: {str(e)}")
                continue
        
        logger.debug(f"✅ Returning {len(trayectos)} trains")
        return trayectos

    def _fill_elem(self, elem, txt):
        try:
            el = self.driver.find_element(By.ID, elem)
            el.clear()
            if txt is not None:
                el.send_keys(txt)
        except Exception:
            self._dump_debug_files()
            raise


    def _areTrainsAvailable(self):
        """
        Wait for trains to load after search. Tries both new HTML structure and legacy.
        Returns True if trains/results are visible, False if "no trains available" message.
        """
        try:
            # Wait up to 15 seconds for trains container to appear with content
            logger.debug("⏳ Waiting for trains container to load (up to 15s)...")
            
            # Try to detect presence with timeout
            start_time = time.time()
            timeout = 15
            
            while (time.time() - start_time) < timeout:
                try:
                    # Check for new HTML structure: div.row.selectedTren inside listaTrenesTBodyIda
                    trains_container = self.driver.find_element(By.ID, "listaTrenesTBodyIda")
                    trains = trains_container.find_elements(By.XPATH, ".//div[contains(@class,'row') and contains(@class,'selectedTren')]")
                    
                    if len(trains) > 0:
                        logger.debug(f"✅ Trains container loaded with {len(trains)} trains")
                        return True
                    else:
                        logger.debug(f"ℹ️ Container exists but empty, retrying... ({int(time.time() - start_time)}s)")
                        time.sleep(0.5)
                        continue
                except NoSuchElementException:
                    logger.debug(f"ℹ️ Container not found yet, retrying... ({int(time.time() - start_time)}s)")
                    time.sleep(0.5)
                    continue
            
            # Timeout reached - check for error message
            logger.warning(f"⏱️ Timeout waiting for trains (after {timeout}s)")
            
        except Exception as e:
            logger.warning(f"⚠️ Error waiting for trains: {str(e)}")

        # Fallback: check for "no trains available" message
        try:
            nodata = self.driver.find_element(By.ID, "tab-mensaje_contenido")
            msg = nodata.text.lower()
            if "no se encuentra disponible" in msg:
                logger.warning(f"❌ No trains available: {msg}")
                return False
            else:
                logger.info(f"ℹ️ Message displayed: {msg}")
                return True
        except NoSuchElementException:
            logger.debug("ℹ️ No error message found either")
            return False


        rows = self.driver.find_elements(By.XPATH, "//tr[contains(@class,'trayectoRow')]")
        return len(rows) > 0


def parse_arguments(argv):
    parser = optparse.OptionParser()
    parser.add_option("--origen","-o",help="Origen",default = None,dest ="origen")
    parser.add_option("--destino","-d",help="Destino",default = None,dest ="destino")
    parser.add_option("--fecha","-f",help="Fecha viaje",default = None,dest="fecha")
    options,args = parser.parse_args(argv)
    if options.origen is None or options.destino is None or options.fecha is None:
        print("Bad parameters")
        parser.print_help()
        exit(1)
    return options


def printRes(aux,ori,des,fec):
    print("Results for=> origin: "+ori+", dest: "+des+", date: "+fec)
    if aux[0]:
        print(aux[1])
    else:
        print("NO RESULTS")

def main(ori,des,fec):
    rf = RenfeChecker(False)
    aux = rf.check_trip(ori,des,fec)
    printRes(aux, ori, des, fec)
    aux = rf.check_trip(des,ori,fec)
    printRes(aux, des, ori, fec)
    rf.close()


if __name__ == "__main__":
    op = parse_arguments(sys.argv)
    main(op.origen,op.destino,op.fecha)
