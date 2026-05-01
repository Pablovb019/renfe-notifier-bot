"""
Conversation flow and user interactions.
"""
import asyncio
import datetime
import difflib
from enum import Enum
import json
import logging
import os
import re
import unicodedata

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ConversationHandler

from telegramcalendarkeyboard import telegramcalendar

from texts import texts as TEXTS
from texts import keyboards as KEYBOARDS

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.DEBUG)

logger = logging.getLogger(__name__)


class ConvStates(Enum):
    OPTION = 1
    STATION = 2
    STATION_GROUP_CHOICE = 3
    DATE = 4
    PLAZA_H = 5
    SEARCH_MODE = 6
    TRAIN_SELECT = 7
    FOLLOWUP_CONFIRM = 8
    FOLLOWUP_LIST_ACTION = 9
    FOLLOWUP_DELETE_SELECT = 10
    ADDITIONAL_QUERY = 11
    EXTEND_DECISION = 12
    RECOVERY_ACTION = 13
    ADDITIONAL_SAME_STATIONS = 14
    ADDITIONAL_SAME_DATE = 15


class RenfeBotConversations:
    STATION_PAGE_SIZE = 8
    TRAIN_PAGE_SIZE = 4

    class Conversation:
        def __init__(self, userid):
            self._userid = userid
            self.reset()

        def reset(self):
            self._origin = None
            self._dest = None
            self._date = None
            self._plaza_h = False
            self._station_target = "origin"
            self._group_station = None
            self._group_city = None
            self._group_candidates = []
            self._mode = None
            self._candidate_trains = []
            self._train_select_mode = None
            self._followup_payload = None
            self._followup_list = []
            self._pending_extension_id = None
            self._min_date = None
            self._max_date = None
            self._station_query = ""
            self._station_matches = []
            self._station_page = 0
            self._station_picker_message_id = None
            self._train_page = 0
            self._train_picker_message_id = None
            self._additional_same_stations = None
            self._skip_date_prompt_once = False
            self._bot_message_ids = []
            self._user_message_ids = []

    def __init__(self, renfebot):
        self._conversations = {}
        self._RB = renfebot
        self._stations, self._station_priorities = self._load_station_catalog()

    # ---------- Generic helpers ----------
    def _start_conv_for_user(self, userid):
        if userid not in self._conversations:
            self._conversations[userid] = self.Conversation(userid)
        self._conversations[userid].reset()
        return self._conversations[userid]

    def _get_conv(self, userid):
        if userid not in self._conversations:
            self._conversations[userid] = self.Conversation(userid)
        return self._conversations[userid]

    def _track_user_message(self, update, conv):
        if update.message is not None:
            conv._user_message_ids.append(update.message.message_id)

    async def _bot_send(self, bot, userid, conv, text, reply_markup=None, parse_mode=None):
        msg = await bot.send_message(chat_id=userid,
                                     text=text,
                                     reply_markup=reply_markup,
                                     parse_mode=parse_mode)
        if msg is not None:
            conv._bot_message_ids.append(msg.message_id)
        return msg

    async def _cleanup_chat_best_effort(self, bot, userid, conv):
        ids = conv._bot_message_ids + conv._user_message_ids
        seen = set()
        for msg_id in reversed(ids):
            if msg_id in seen:
                continue
            seen.add(msg_id)
            try:
                await bot.delete_message(chat_id=userid, message_id=msg_id)
            except Exception as ex:
                logger.debug("Could not delete message %s: %s", msg_id, str(ex))
        conv._bot_message_ids = []
        conv._user_message_ids = []
        conv._station_picker_message_id = None
        conv._train_picker_message_id = None

    def _normalize_yes_no(self, txt):
        if txt is None:
            return None
        normalized = unicodedata.normalize("NFKD", txt.strip().upper())
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        if normalized == "SI":
            return True
        if normalized == "NO":
            return False
        return None

    def _normalize_station(self, station):
        if station is None:
            return ""
        normalized = unicodedata.normalize("NFKD", station)
        normalized = "".join(
            char for char in normalized if not unicodedata.combining(char)
        )
        normalized = normalized.upper()
        return re.sub(r"[^A-Z0-9]", "", normalized)

    def _load_station_catalog(self):
        stations_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "data", "stations.json")
        )
        with open(stations_path, "r", encoding="utf-8") as f:
            raw_catalog = json.load(f)
        if not isinstance(raw_catalog, dict):
            raise ValueError("stations.json must be a JSON object with station names as keys")

        station_priorities = {}

        def parse_priority(station_data):
            raw_prio = None
            if isinstance(station_data, dict):
                raw_prio = station_data.get("nmroPrioridad")
            try:
                return int(raw_prio)
            except (TypeError, ValueError):
                return 999999

        for station_name, station_data in raw_catalog.items():
            station_priorities[station_name] = parse_priority(station_data)

        ordered = [name for name, _ in sorted(raw_catalog.items(), key=lambda item: (station_priorities[item[0]], item[0]))]
        return ordered, station_priorities

    # ---------- Station resolution ----------
    def _station_catalog(self):
        return self._stations

    def _station_priority(self, station_name):
        return self._station_priorities.get(station_name, 999999)

    def _resolve_station(self, station):
        normalized_input = self._normalize_station(station)
        if normalized_input == "":
            return None
        normalized_station_lookup = {
            self._normalize_station(st): st for st in self._station_catalog()
        }
        return normalized_station_lookup.get(normalized_input)

    def _suggest_stations(self, station):
        stations = self._station_catalog()
        station_text = station or ""
        normalized_input = self._normalize_station(station_text)
        tokens = []
        for token in re.split(r"[^\w]+", station_text):
            if token:
                normalized_token = self._normalize_station(token)
                if len(normalized_token) >= 3:
                    tokens.append(normalized_token)

        scored = []
        for st in stations:
            st_norm = self._normalize_station(st)
            token_matches = sum(1 for tok in tokens if tok in st_norm)
            contains_input = normalized_input != "" and (
                normalized_input in st_norm or st_norm in normalized_input
            )
            if token_matches == 0 and not contains_input:
                continue
            similarity = difflib.SequenceMatcher(None, normalized_input, st_norm).ratio()
            score = (token_matches * 10) + similarity
            scored.append((score, st))

        if scored:
            scored.sort(key=lambda item: (-item[0], item[1]))
            ordered = [st for _, st in scored]
            unique_ordered = list(dict.fromkeys(ordered))
            return unique_ordered[:3]

        return difflib.get_close_matches(station_text.upper(), stations, n=3, cutoff=0.45)

    def _is_group_station(self, station_name):
        if not station_name:
            return False
        return bool(re.search(r"\(\s*TODAS\s*\)\s*$", station_name, re.IGNORECASE))

    def _group_city_name(self, group_station_name):
        return re.sub(r"\s*\(\s*TODAS\s*\)\s*$", "", group_station_name, flags=re.IGNORECASE).strip()

    def _group_station_candidates(self, group_station_name):
        city = self._group_city_name(group_station_name)
        city_norm = self._normalize_station(city)
        candidates = []
        for station_name in self._station_catalog():
            if station_name == group_station_name or self._is_group_station(station_name):
                continue
            st_norm = self._normalize_station(station_name)
            if st_norm.startswith(city_norm):
                candidates.append(station_name)
        if candidates:
            return candidates

        for station_name in self._station_catalog():
            if station_name == group_station_name or self._is_group_station(station_name):
                continue
            st_norm = self._normalize_station(station_name)
            if city_norm in st_norm:
                candidates.append(station_name)
        return candidates

    def _group_station_options_message(self, group_station_name, group_city, candidates):
        lines = []
        for idx, station_name in enumerate(candidates, start=1):
            lines.append("{idx}. {station}".format(idx=idx, station=station_name))
        options_text = "\n".join(lines)
        if options_text == "":
            options_text = TEXTS["GROUP_STATION_NO_CONCRETE"]

        return TEXTS["GROUP_STATION_OPTIONS"].format(
            station_group=group_station_name,
            city=group_city,
            count=len(candidates),
            options=options_text,
            all_option_number=len(candidates) + 1,
        )

    # ---------- Station picker (inline) ----------
    def _station_target_label(self, target):
        if target == "origin":
            return TEXTS["STATION_TARGET_ORIGIN"]
        return TEXTS["STATION_TARGET_DESTINATION"]

    def _rank_station_matches(self, query):
        stations = self._station_catalog()
        query = (query or "").strip()
        if query == "":
            return stations

        normalized_query = self._normalize_station(query)
        tokens = []
        for token in re.split(r"[^\w]+", query):
            if token:
                normalized_token = self._normalize_station(token)
                if len(normalized_token) >= 2:
                    tokens.append(normalized_token)

        scored = []
        for station_name in stations:
            station_norm = self._normalize_station(station_name)
            if station_norm == normalized_query:
                scored.append((9999.0, station_name))
                continue

            station_tokens = [self._normalize_station(tok) for tok in re.split(r"[^\w]+", station_name) if tok]
            starts_with = station_norm.startswith(normalized_query)
            word_starts_with = any(tok.startswith(normalized_query) for tok in station_tokens)
            token_matches = sum(1 for token in tokens if token in station_norm)
            contains_query = normalized_query in station_norm
            similarity = difflib.SequenceMatcher(None, normalized_query, station_norm).ratio()
            priority_boost = max(0.0, (1000.0 - float(self._station_priority(station_name))) / 1000.0)

            if not starts_with and not word_starts_with and not contains_query and token_matches == 0 and similarity < 0.30:
                continue

            score = 0.0
            if starts_with:
                score += 8.0
            if word_starts_with:
                score += 5.0
            if contains_query:
                score += 5.0
            score += (token_matches * 2.0)
            score += similarity
            score += priority_boost
            scored.append((score, station_name))

        scored.sort(key=lambda item: (-item[0], self._station_priority(item[1]), item[1]))
        return [station for _, station in scored]

    def _build_station_picker_markup(self, conv):
        matches = conv._station_matches or []
        if len(matches) == 0:
            return InlineKeyboardMarkup(
                [[InlineKeyboardButton(TEXTS["STATION_PICKER_CANCEL"], callback_data="STSEL|C")]]
            )

        page_count = (len(matches) + self.STATION_PAGE_SIZE - 1) // self.STATION_PAGE_SIZE
        conv._station_page = max(0, min(conv._station_page, page_count - 1))
        start = conv._station_page * self.STATION_PAGE_SIZE
        end = min(start + self.STATION_PAGE_SIZE, len(matches))

        rows = []
        for idx in range(start, end):
            rows.append([InlineKeyboardButton(matches[idx], callback_data=f"STSEL|S|{idx}")])

        nav_row = []
        if conv._station_page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data="STSEL|P"))
        nav_row.append(InlineKeyboardButton(f"{conv._station_page + 1}/{page_count}", callback_data="STSEL|I"))
        if conv._station_page < (page_count - 1):
            nav_row.append(InlineKeyboardButton("➡️", callback_data="STSEL|N"))
        rows.append(nav_row)
        rows.append([InlineKeyboardButton(TEXTS["STATION_PICKER_CANCEL"], callback_data="STSEL|C")])
        return InlineKeyboardMarkup(rows)

    def _station_picker_text(self, conv):
        target = self._station_target_label(conv._station_target)
        query = (conv._station_query or "").strip()
        if query == "":
            return TEXTS["STATION_PICKER_PROMPT"].format(target=target)
        if len(conv._station_matches) == 0:
            return TEXTS["STATION_PICKER_EMPTY"].format(target=target, query=query)
        return TEXTS["STATION_PICKER_RESULTS"].format(
            target=target,
            query=query,
            count=len(conv._station_matches),
        )

    async def _render_station_picker(self, bot, userid, conv, force_new=False):
        text = self._station_picker_text(conv)
        markup = self._build_station_picker_markup(conv)

        if conv._station_picker_message_id is not None and not force_new:
            try:
                await bot.edit_message_text(
                    chat_id=userid,
                    message_id=conv._station_picker_message_id,
                    text=text,
                    reply_markup=markup,
                )
                return
            except Exception as ex:
                logger.debug("Could not edit station picker message %s: %s", conv._station_picker_message_id, str(ex))

        msg = await self._bot_send(bot, userid, conv, text, reply_markup=markup)
        conv._station_picker_message_id = msg.message_id if msg is not None else None

    async def _close_station_picker(self, bot, userid, conv):
        if conv._station_picker_message_id is None:
            return
        try:
            await bot.edit_message_reply_markup(
                chat_id=userid,
                message_id=conv._station_picker_message_id,
                reply_markup=None,
            )
        except Exception as ex:
            logger.debug("Could not close station picker message %s: %s", conv._station_picker_message_id, str(ex))
        conv._station_picker_message_id = None

    async def _start_station_picker(self, bot, userid, conv, target):
        conv._station_target = target
        conv._station_query = ""
        conv._station_matches = self._station_catalog()
        conv._station_page = 0
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["STATION_PICKER_HELP"].format(target=self._station_target_label(target)),
            reply_markup=ReplyKeyboardRemove(),
        )
        await self._render_station_picker(bot, userid, conv, force_new=True)
        return ConvStates.STATION

    async def _apply_station_selection(self, bot, userid, conv, selected_station):
        await self._close_station_picker(bot, userid, conv)
        if self._is_group_station(selected_station):
            conv._group_station = selected_station
            conv._group_city = self._group_city_name(selected_station)
            conv._group_candidates = self._group_station_candidates(selected_station)
            await self._bot_send(
                bot,
                userid,
                conv,
                self._group_station_options_message(conv._group_station, conv._group_city, conv._group_candidates),
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConvStates.STATION_GROUP_CHOICE
        return await self._set_station_and_continue(bot, userid, conv, selected_station)

    # ---------- Date and train helpers ----------
    def _add_months(self, source_date, months):
        month = source_date.month - 1 + months
        year = source_date.year + month // 12
        month = month % 12 + 1
        day = min(source_date.day, [31,
                                    29 if year % 4 == 0 and not year % 100 == 0 or year % 400 == 0 else 28,
                                    31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
        return datetime.date(year, month, day)

    def _is_today(self, date_str):
        d = datetime.datetime.strptime(date_str, "%d/%m/%Y").date()
        return d == datetime.date.today()

    async def _fetch_trains(self, conv):
        res = await asyncio.to_thread(
            self._RB._RF.check_trip,
            conv._origin,
            conv._dest,
            conv._date,
            None,
            conv._plaza_h,
        )
        trains = []
        if res[0] and res[1] is not None:
            trains = list(res[1])
        trains.sort(key=lambda t: t["SALIDA"])
        if self._is_today(conv._date):
            now_time = datetime.datetime.now().time()
            trains = [t for t in trains if t["SALIDA"] > now_time]
        return trains

    def _format_train_line(self, idx, train):
        transfer_marker = "🔄 " if train.get("TRANSFER") else "   "
        mark = "✓" if train.get("DISPONIBLE") else "✗"
        dur_hours = int(train.get("DURACION", 0))
        dur_mins = int((train.get("DURACION", 0) - dur_hours) * 60)
        transfer_info = f" ({train.get('TRANSFER_TIME', '')})" if train.get("TRANSFER") else ""
        return "{transfer}{idx}. {dep}-{arr} ({dur}h{min}m) {mark}{transfer_info}".format(
            transfer=transfer_marker,
            idx=idx,
            dep=train["SALIDA"].strftime("%H:%M"),
            arr=train["LLEGADA"].strftime("%H:%M"),
            dur=dur_hours,
            min=dur_mins,
            mark=mark,
            transfer_info=transfer_info,
        )

    def _render_train_options(self, trains, include_all_option=False):
        lines = []
        for idx, train in enumerate(trains, start=1):
            lines.append(self._format_train_line(idx, train))
        if include_all_option:
            lines.append("{idx}. {label}".format(
                idx=len(trains) + 1,
                label=TEXTS["TRAIN_SELECT_ALL_OPTION"]
            ))
        return "\n".join(lines)

    def _train_text_times(self, train):
        return train["SALIDA"].strftime("%H:%M"), train["LLEGADA"].strftime("%H:%M")

    def _train_button_label(self, idx, train):
        dep, arr = self._train_text_times(train)
        mark = "✓" if train.get("DISPONIBLE") else "✗"
        transfer = " 🔄" if train.get("TRANSFER") else ""
        return f"{idx}. {dep}-{arr} {mark}{transfer}"

    def _build_train_picker_markup(self, conv):
        trains = conv._candidate_trains or []
        if len(trains) == 0:
            return InlineKeyboardMarkup([])

        page_count = (len(trains) + self.TRAIN_PAGE_SIZE - 1) // self.TRAIN_PAGE_SIZE
        conv._train_page = max(0, min(conv._train_page, page_count - 1))
        start = conv._train_page * self.TRAIN_PAGE_SIZE
        end = min(start + self.TRAIN_PAGE_SIZE, len(trains))

        rows = []
        for idx in range(start, end):
            rows.append([
                InlineKeyboardButton(
                    self._train_button_label(idx + 1, trains[idx]),
                    callback_data=f"TRSEL|S|{idx}",
                )
            ])

        rows.append([InlineKeyboardButton(TEXTS["TRAIN_SELECT_ALL_OPTION"], callback_data="TRSEL|A")])

        if page_count > 1:
            nav_row = []
            if conv._train_page > 0:
                nav_row.append(InlineKeyboardButton("⬅️", callback_data="TRSEL|P"))
            nav_row.append(InlineKeyboardButton(f"{conv._train_page + 1}/{page_count}", callback_data="TRSEL|I"))
            if conv._train_page < (page_count - 1):
                nav_row.append(InlineKeyboardButton("➡️", callback_data="TRSEL|N"))
            rows.append(nav_row)
        return InlineKeyboardMarkup(rows)

    def _train_picker_text(self, conv):
        total = len(conv._candidate_trains or [])
        if total == 0:
            return TEXTS["TRAIN_PICKER_PROMPT"].format(start=0, end=0, total=0)
        start = (conv._train_page * self.TRAIN_PAGE_SIZE) + 1
        end = min(start + self.TRAIN_PAGE_SIZE - 1, total)
        return TEXTS["TRAIN_PICKER_PROMPT"].format(start=start, end=end, total=total)

    async def _render_train_picker(self, bot, userid, conv, force_new=False):
        text = self._train_picker_text(conv)
        markup = self._build_train_picker_markup(conv)

        if conv._train_picker_message_id is not None and not force_new:
            try:
                await bot.edit_message_text(
                    chat_id=userid,
                    message_id=conv._train_picker_message_id,
                    text=text,
                    reply_markup=markup,
                )
                return
            except Exception as ex:
                logger.debug("Could not edit train picker message %s: %s", conv._train_picker_message_id, str(ex))

        msg = await self._bot_send(bot, userid, conv, text, reply_markup=markup)
        conv._train_picker_message_id = msg.message_id if msg is not None else None

    async def _close_train_picker(self, bot, userid, conv):
        if conv._train_picker_message_id is None:
            return
        try:
            await bot.edit_message_reply_markup(
                chat_id=userid,
                message_id=conv._train_picker_message_id,
                reply_markup=None,
            )
        except Exception as ex:
            logger.debug("Could not close train picker message %s: %s", conv._train_picker_message_id, str(ex))
        conv._train_picker_message_id = None

    async def _start_train_picker(self, bot, userid, conv):
        conv._train_page = 0
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["TRAIN_PICKER_HELP"],
            reply_markup=ReplyKeyboardRemove(),
        )
        await self._render_train_picker(bot, userid, conv, force_new=True)
        return ConvStates.TRAIN_SELECT

    def _set_followup_payload_for_train(self, conv, train):
        dep, arr = self._train_text_times(train)
        conv._followup_payload = {
            "origin": conv._origin,
            "destination": conv._dest,
            "date": conv._date,
            "departure_time": dep,
            "arrival_time": arr,
            "plaza_h": conv._plaza_h,
            "watch_all": False,
        }

    def _set_followup_payload_all(self, conv):
        conv._followup_payload = {
            "origin": conv._origin,
            "destination": conv._dest,
            "date": conv._date,
            "departure_time": None,
            "arrival_time": None,
            "plaza_h": conv._plaza_h,
            "watch_all": True,
        }

    # ---------- Navigation helpers ----------
    async def _prompt_pending_extension_or_menu(self, bot, userid, conv):
        pending = self._RB._DB.get_user_pending_extensions(userid)
        if len(pending) > 0:
            f = pending[0]
            conv._pending_extension_id = f["id"]
            dep = f["departure_time"] if f["departure_time"] else "--:--"
            arr = f["arrival_time"] if f["arrival_time"] else "--:--"
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["FOLLOWUP_EXTEND_PROMPT"].format(
                    date=f["travel_date"],
                    origin=f["origin"],
                    dep_time=dep,
                    destination=f["destination"],
                    arr_time=arr,
                ),
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.EXTEND_DECISION

        conv._pending_extension_id = None
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["OPTION_SELECTION"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["MAIN_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.OPTION

    async def _return_to_main_menu(self, bot, userid, conv):
        await self._cleanup_chat_best_effort(bot, userid, conv)
        return await self._prompt_pending_extension_or_menu(bot, userid, conv)

    async def _prompt_trip_date(self, bot, userid, conv):
        today = datetime.date.today()
        max_date = self._add_months(today, 2)
        conv._min_date = today
        conv._max_date = max_date
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["SELECT_TRIP_DATE"],
            reply_markup=telegramcalendar.create_calendar(min_date=today, max_date=max_date),
        )
        return ConvStates.DATE

    async def _prompt_plaza_h(self, bot, userid, conv, include_selected_data=False):
        if include_selected_data:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["SELECTED_DATA"].format(origin=conv._origin, destination=conv._dest, date=conv._date),
            )
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["ASK_PLAZA_H"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["PLAZA_H_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.PLAZA_H

    async def _prompt_additional_query(self, bot, userid, conv):
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["ASK_ADDITIONAL_QUERY"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.ADDITIONAL_QUERY

    async def _prompt_additional_same_stations(self, bot, userid, conv):
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["ASK_ADDITIONAL_SAME_STATIONS"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.ADDITIONAL_SAME_STATIONS

    async def _prompt_additional_same_date(self, bot, userid, conv):
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["ASK_ADDITIONAL_SAME_DATE"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.ADDITIONAL_SAME_DATE

    async def _prompt_recovery_options(self, bot, userid, conv):
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["RECOVERY_OPTIONS_PROMPT"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["RECOVERY_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.RECOVERY_ACTION

    # ---------- Handlers ----------
    async def handler_start(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        username = update.effective_user.first_name
        if update.effective_user.last_name is not None:
            username += " " + update.effective_user.last_name
        auth = self._RB._DB.get_user_auth(userid, username)
        if auth == 0:
            await update.message.reply_text(TEXTS["NOT_AUTH_REPLY"].format(username=username),
                                            reply_markup=ReplyKeyboardRemove())
            await self._RB.ask_admin_for_access(bot, userid, username)
            return ConversationHandler.END

        conv = self._start_conv_for_user(userid)
        self._track_user_message(update, conv)
        return await self._prompt_pending_extension_or_menu(bot, userid, conv)

    async def handler_cancel(self, update, context):
        return ConversationHandler.END

    async def handler_option(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        text = (update.message.text or "").strip()

        if text == TEXTS["MAIN_OP_SEARCH"]:
            conv._station_target = "origin"
            conv._origin = None
            conv._dest = None
            conv._date = None
            conv._candidate_trains = []
            await self._bot_send(bot, userid, conv, TEXTS["DO_ONETIME_QUERY"], reply_markup=ReplyKeyboardRemove())
            return await self._start_station_picker(bot, userid, conv, "origin")

        if text == TEXTS["MAIN_OP_VIEW_FOLLOWUPS"]:
            followups = self._RB._DB.get_user_followups(userid)
            if len(followups) == 0:
                await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUPS_EMPTY"])
                return await self._return_to_main_menu(bot, userid, conv)

            conv._followup_list = followups
            lines = []
            for idx, f in enumerate(followups, start=1):
                if f["watch_all"]:
                    label = "{idx}. {date} {origin} - {destination} (TODOS)".format(
                        idx=idx, date=f["travel_date"], origin=f["origin"], destination=f["destination"])
                else:
                    label = "{idx}. {date} {origin} ({dep}) - {destination}({arr})".format(
                        idx=idx, date=f["travel_date"], origin=f["origin"],
                        dep=f["departure_time"], destination=f["destination"], arr=f["arrival_time"])
                lines.append(label)
            await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUPS_LIST"].format(items="\n".join(lines)))
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["FOLLOWUPS_DELETE_ASK"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.FOLLOWUP_LIST_ACTION

        await self._bot_send(bot, userid, conv, TEXTS["MAIN_OP_UNKNOWN"])
        return ConvStates.OPTION

    async def handler_followup_list_action(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        answer = self._normalize_yes_no(update.message.text)
        if answer is None:
            await self._bot_send(bot, userid, conv, TEXTS["MAIN_OP_UNKNOWN"])
            return ConvStates.FOLLOWUP_LIST_ACTION
        if not answer:
            return await self._return_to_main_menu(bot, userid, conv)
        await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUPS_DELETE_PROMPT"], reply_markup=ReplyKeyboardRemove())
        return ConvStates.FOLLOWUP_DELETE_SELECT

    async def handler_followup_delete_select(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        txt = (update.message.text or "").strip()
        if not txt.isdigit():
            await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUPS_DELETE_INVALID"])
            return ConvStates.FOLLOWUP_DELETE_SELECT
        idx = int(txt)
        if idx < 1 or idx > len(conv._followup_list):
            await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUPS_DELETE_INVALID"])
            return ConvStates.FOLLOWUP_DELETE_SELECT
        followup_id = conv._followup_list[idx - 1]["id"]
        self._RB._DB.delete_user_followup(userid, followup_id)
        await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUPS_DELETED"])
        return await self._return_to_main_menu(bot, userid, conv)

    async def _set_station_and_continue(self, bot, userid, conv, selected_station):
        if conv._station_target == "origin":
            conv._origin = selected_station
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["STATION_SELECTED"].format(
                    target=self._station_target_label("origin"),
                    station=selected_station,
                ),
                reply_markup=ReplyKeyboardRemove(),
            )
            return await self._start_station_picker(bot, userid, conv, "destination")

        conv._dest = selected_station
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["STATION_SELECTED"].format(
                target=self._station_target_label("destination"),
                station=selected_station,
            ),
            reply_markup=ReplyKeyboardRemove(),
        )
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["SELECTED_TRIP"].format(origin=conv._origin, destination=conv._dest),
            reply_markup=ReplyKeyboardRemove(),
        )
        if conv._skip_date_prompt_once:
            conv._skip_date_prompt_once = False
            if conv._date is not None:
                return await self._prompt_plaza_h(bot, userid, conv, include_selected_data=True)

        return await self._prompt_trip_date(bot, userid, conv)

    async def handler_station(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        station_input = (update.message.text or "").strip()
        if station_input == "":
            return ConvStates.STATION

        resolved_station = self._resolve_station(station_input)

        if resolved_station is not None:
            return await self._apply_station_selection(bot, userid, conv, resolved_station)

        conv._station_query = station_input
        conv._station_matches = self._rank_station_matches(station_input)
        conv._station_page = 0
        if len(conv._station_matches) == 0:
            suggestions = self._suggest_stations(station_input)
            if not suggestions:
                suggestions = self._station_catalog()[:3]
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["INVALID_STATION"].format(
                    station=station_input,
                    suggestions=", ".join(suggestions),
                ),
            )
            conv._station_matches = self._station_catalog()
            conv._station_page = 0
            conv._station_query = ""

        await self._render_station_picker(bot, userid, conv)
        return ConvStates.STATION

    async def handler_station_callback(self, update, context):
        query = update.callback_query
        if query is None:
            return ConvStates.STATION
        await query.answer()

        data = query.data or ""
        if not data.startswith("STSEL|"):
            return ConvStates.STATION

        bot = context.bot
        userid = query.from_user.id
        conv = self._get_conv(userid)
        parts = data.split("|")
        action = parts[1] if len(parts) > 1 else ""

        if action == "P":
            conv._station_page = max(0, conv._station_page - 1)
            await self._render_station_picker(bot, userid, conv)
            return ConvStates.STATION
        if action == "N":
            conv._station_page += 1
            await self._render_station_picker(bot, userid, conv)
            return ConvStates.STATION
        if action == "C":
            await self._close_station_picker(bot, userid, conv)
            return await self._return_to_main_menu(bot, userid, conv)
        if action == "I":
            return ConvStates.STATION

        if action == "S" and len(parts) >= 3 and parts[2].isdigit():
            idx = int(parts[2])
            if idx < 0 or idx >= len(conv._station_matches):
                await self._render_station_picker(bot, userid, conv)
                return ConvStates.STATION
            selected_station = conv._station_matches[idx]
            return await self._apply_station_selection(bot, userid, conv, selected_station)

        await self._render_station_picker(bot, userid, conv)
        return ConvStates.STATION

    async def handler_station_group_choice(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        choice_text = (update.message.text or "").strip()
        if not choice_text.isdigit():
            await self._bot_send(bot, userid, conv, TEXTS["GROUP_STATION_INVALID_OPTION"])
            await self._bot_send(
                bot,
                userid,
                conv,
                self._group_station_options_message(conv._group_station, conv._group_city, conv._group_candidates),
            )
            return ConvStates.STATION_GROUP_CHOICE

        choice = int(choice_text)
        all_option = len(conv._group_candidates) + 1
        if 1 <= choice <= len(conv._group_candidates):
            selected_station = conv._group_candidates[choice - 1]
        elif choice == all_option:
            selected_station = conv._group_station
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["GROUP_STATION_ALL_WARNING"].format(station_group=selected_station),
            )
        else:
            await self._bot_send(bot, userid, conv, TEXTS["GROUP_STATION_INVALID_OPTION"])
            await self._bot_send(
                bot,
                userid,
                conv,
                self._group_station_options_message(conv._group_station, conv._group_city, conv._group_candidates),
            )
            return ConvStates.STATION_GROUP_CHOICE

        conv._group_station = None
        conv._group_city = None
        conv._group_candidates = []
        return await self._set_station_and_continue(bot, userid, conv, selected_station)

    async def handler_date(self, update, context):
        bot = context.bot
        userid = update.callback_query.from_user.id
        conv = self._get_conv(userid)
        selected, date = await telegramcalendar.process_calendar_selection(
            update,
            min_date=conv._min_date,
            max_date=conv._max_date
        )
        if not selected:
            return ConvStates.DATE

        if date.date() < conv._min_date or date.date() > conv._max_date:
            await self._bot_send(bot, userid, conv, TEXTS["INVALID_DATE_RANGE"])
            return await self._prompt_trip_date(bot, userid, conv)

        conv._date = date.strftime("%d/%m/%Y")
        return await self._prompt_plaza_h(bot, userid, conv, include_selected_data=True)

    async def handler_plaza_h(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        txt = (update.message.text or "").strip()
        if txt == TEXTS["MAIN_OP_PLAZA_H_YES"]:
            conv._plaza_h = True
        elif txt == TEXTS["MAIN_OP_PLAZA_H_NO"]:
            conv._plaza_h = False
        else:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["ASK_PLAZA_H"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["PLAZA_H_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.PLAZA_H

        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["ASK_SEARCH_MODE"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["SEARCH_MODE_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.SEARCH_MODE

    async def _send_train_available(self, bot, userid, conv, train):
        dep, arr = self._train_text_times(train)
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["TRAIN_AVAILABLE_MSG"].format(
                date=conv._date,
                origin=conv._origin,
                dep_time=dep,
                destination=conv._dest,
                arr_time=arr,
            ),
        )

    async def _offer_followup_for_train(self, bot, userid, conv, train):
        dep, arr = self._train_text_times(train)
        self._set_followup_payload_for_train(conv, train)
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["TRAIN_NOT_AVAILABLE_MSG"].format(
                date=conv._date,
                origin=conv._origin,
                dep_time=dep,
                destination=conv._dest,
                arr_time=arr,
            ),
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.FOLLOWUP_CONFIRM

    async def _offer_followup_for_all(self, bot, userid, conv):
        self._set_followup_payload_all(conv)
        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["TRAIN_NOT_AVAILABLE_ALL_MSG"].format(
                date=conv._date,
                origin=conv._origin,
                destination=conv._dest,
            ),
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.FOLLOWUP_CONFIRM

    async def handler_search_mode(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        txt = (update.message.text or "").strip()
        mode = None
        if txt == TEXTS["MAIN_OP_MODE_SPECIFIC"]:
            mode = "specific"
        elif txt == TEXTS["MAIN_OP_MODE_FIRST"]:
            mode = "first"
        elif txt == TEXTS["MAIN_OP_MODE_LAST"]:
            mode = "last"
        elif txt == TEXTS["MAIN_OP_MODE_ALL"]:
            mode = "all"
        else:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["ASK_SEARCH_MODE"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["SEARCH_MODE_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.SEARCH_MODE

        conv._mode = mode
        await self._bot_send(bot, userid, conv, TEXTS["WAIT_FOR_TRAINS"])
        trains = await self._fetch_trains(conv)
        conv._candidate_trains = trains

        if len(trains) == 0:
            no_trains_msg = TEXTS["NO_TRAINS_FOUND_PLAZA_H"] if conv._plaza_h else TEXTS["NO_TRAINS_FOUND"]
            await self._bot_send(bot, userid, conv, no_trains_msg.format(
                origin=conv._origin, destination=conv._dest, date=conv._date))
            return await self._prompt_recovery_options(bot, userid, conv)

        if mode == "specific":
            conv._train_select_mode = "specific"
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["TRAIN_SELECT_PROMPT"].format(options=self._render_train_options(trains, include_all_option=False)),
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConvStates.TRAIN_SELECT

        if mode == "all":
            conv._train_select_mode = "all"
            return await self._start_train_picker(bot, userid, conv)

        available = [t for t in trains if t.get("DISPONIBLE")]
        if mode == "first":
            if len(available) > 0:
                selected = min(available, key=lambda x: x["SALIDA"])
                await self._send_train_available(bot, userid, conv, selected)
                return await self._prompt_additional_query(bot, userid, conv)
            selected = min(trains, key=lambda x: x["SALIDA"])
            return await self._offer_followup_for_train(bot, userid, conv, selected)

        if len(available) > 0:
            selected = max(available, key=lambda x: x["SALIDA"])
            await self._send_train_available(bot, userid, conv, selected)
            return await self._prompt_additional_query(bot, userid, conv)
        selected = max(trains, key=lambda x: x["SALIDA"])
        return await self._offer_followup_for_train(bot, userid, conv, selected)

    async def handler_train_select(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        if conv._train_select_mode == "all":
            await self._bot_send(bot, userid, conv, TEXTS["TRAIN_PICKER_USE_BUTTONS"], reply_markup=ReplyKeyboardRemove())
            await self._render_train_picker(bot, userid, conv)
            return ConvStates.TRAIN_SELECT

        txt = (update.message.text or "").strip()
        if not txt.isdigit():
            await self._bot_send(bot, userid, conv, TEXTS["TRAIN_SELECT_INVALID"])
            return ConvStates.TRAIN_SELECT
        choice = int(txt)
        trains = conv._candidate_trains

        if conv._train_select_mode == "specific":
            if choice < 1 or choice > len(trains):
                await self._bot_send(bot, userid, conv, TEXTS["TRAIN_SELECT_INVALID"])
                return ConvStates.TRAIN_SELECT
            train = trains[choice - 1]
            if train.get("DISPONIBLE"):
                await self._send_train_available(bot, userid, conv, train)
                return await self._prompt_additional_query(bot, userid, conv)
            return await self._offer_followup_for_train(bot, userid, conv, train)

        await self._bot_send(bot, userid, conv, TEXTS["TRAIN_PICKER_USE_BUTTONS"], reply_markup=ReplyKeyboardRemove())
        await self._render_train_picker(bot, userid, conv)
        return ConvStates.TRAIN_SELECT

    async def handler_train_select_callback(self, update, context):
        query = update.callback_query
        if query is None:
            return ConvStates.TRAIN_SELECT
        await query.answer()

        data = query.data or ""
        if not data.startswith("TRSEL|"):
            return ConvStates.TRAIN_SELECT

        bot = context.bot
        userid = query.from_user.id
        conv = self._get_conv(userid)
        trains = conv._candidate_trains or []
        parts = data.split("|")
        action = parts[1] if len(parts) > 1 else ""

        if action == "P":
            conv._train_page = max(0, conv._train_page - 1)
            await self._render_train_picker(bot, userid, conv)
            return ConvStates.TRAIN_SELECT
        if action == "N":
            conv._train_page += 1
            await self._render_train_picker(bot, userid, conv)
            return ConvStates.TRAIN_SELECT
        if action == "I":
            return ConvStates.TRAIN_SELECT

        if action == "A":
            await self._close_train_picker(bot, userid, conv)
            available = [t for t in trains if t.get("DISPONIBLE")]
            if len(available) > 0:
                await self._bot_send(
                    bot,
                    userid,
                    conv,
                    TEXTS["TRAIN_SELECT_PROMPT"].format(options=self._render_train_options(trains, include_all_option=False)),
                    reply_markup=ReplyKeyboardRemove(),
                )
                return await self._prompt_additional_query(bot, userid, conv)
            return await self._offer_followup_for_all(bot, userid, conv)

        if action == "S" and len(parts) >= 3 and parts[2].isdigit():
            idx = int(parts[2])
            if idx < 0 or idx >= len(trains):
                await self._render_train_picker(bot, userid, conv)
                return ConvStates.TRAIN_SELECT
            await self._close_train_picker(bot, userid, conv)
            train = trains[idx]
            if train.get("DISPONIBLE"):
                await self._send_train_available(bot, userid, conv, train)
                return await self._prompt_additional_query(bot, userid, conv)
            return await self._offer_followup_for_train(bot, userid, conv, train)

        await self._render_train_picker(bot, userid, conv)
        return ConvStates.TRAIN_SELECT

    async def handler_followup_confirm(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        answer = self._normalize_yes_no(update.message.text)
        if answer is None:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["ASK_FOLLOWUP_CONFIRM"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.FOLLOWUP_CONFIRM
        if not answer:
            return await self._prompt_recovery_options(bot, userid, conv)

        payload = conv._followup_payload
        ok, _ = self._RB._DB.create_followup(
            userid=userid,
            origin=payload["origin"],
            destination=payload["destination"],
            travel_date=payload["date"],
            departure_time=payload["departure_time"],
            arrival_time=payload["arrival_time"],
            plaza_h=payload["plaza_h"],
            watch_all=payload["watch_all"],
        )
        if not ok:
            await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUP_NOT_EXTENDED_MSG"])
            return await self._prompt_recovery_options(bot, userid, conv)

        if payload["watch_all"]:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["FOLLOWUP_CREATED_ALL_MSG"].format(
                    date=payload["date"],
                    origin=payload["origin"],
                    destination=payload["destination"],
                ),
            )
        else:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["FOLLOWUP_CREATED_MSG"].format(
                    date=payload["date"],
                    origin=payload["origin"],
                    dep_time=payload["departure_time"],
                    destination=payload["destination"],
                    arr_time=payload["arrival_time"],
                ),
            )
        return await self._return_to_main_menu(bot, userid, conv)

    async def handler_additional_query(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        answer = self._normalize_yes_no(update.message.text)
        if answer is None:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["ASK_ADDITIONAL_QUERY"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.ADDITIONAL_QUERY

        if answer:
            conv._origin = None
            conv._dest = None
            return await self._start_station_picker(bot, userid, conv, "origin")

        return await self._return_to_main_menu(bot, userid, conv)

    async def handler_recovery_action(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        option = (update.message.text or "").strip()

        if option == TEXTS["RECOVERY_OP_RETRY_MODE"]:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["ASK_SEARCH_MODE"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["SEARCH_MODE_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.SEARCH_MODE

        if option == TEXTS["RECOVERY_OP_CHANGE_DATE"]:
            today = datetime.date.today()
            max_date = self._add_months(today, 2)
            conv._min_date = today
            conv._max_date = max_date
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["SELECT_TRIP_DATE"],
                reply_markup=telegramcalendar.create_calendar(
                    year=today.year,
                    month=today.month,
                    min_date=today,
                    max_date=max_date,
                ),
            )
            return ConvStates.DATE

        if option == TEXTS["RECOVERY_OP_MAIN_MENU"]:
            return await self._return_to_main_menu(bot, userid, conv)

        await self._bot_send(
            bot,
            userid,
            conv,
            TEXTS["RECOVERY_INVALID_OPTION"],
            reply_markup=ReplyKeyboardMarkup(KEYBOARDS["RECOVERY_OPTIONS"], one_time_keyboard=True),
        )
        return ConvStates.RECOVERY_ACTION

    async def handler_extend_decision(self, update, context):
        bot = context.bot
        userid = update.effective_user.id
        conv = self._get_conv(userid)
        self._track_user_message(update, conv)
        answer = self._normalize_yes_no(update.message.text)
        if answer is None:
            await self._bot_send(
                bot,
                userid,
                conv,
                TEXTS["MAIN_OP_UNKNOWN"],
                reply_markup=ReplyKeyboardMarkup(KEYBOARDS["YES_NO_OPTIONS"], one_time_keyboard=True),
            )
            return ConvStates.EXTEND_DECISION

        pending = self._RB._DB.get_user_pending_extensions(userid)
        if len(pending) == 0:
            await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUP_NO_PENDING"])
            return await self._return_to_main_menu(bot, userid, conv)

        followup_id = pending[0]["id"]
        if answer:
            if self._RB._DB.extend_followup(followup_id):
                await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUP_EXTENDED_MSG"])
            else:
                self._RB._DB.delete_followup(followup_id)
                await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUP_NOT_EXTENDED_MSG"])
        else:
            self._RB._DB.delete_followup(followup_id)
            await self._bot_send(bot, userid, conv, TEXTS["FOLLOWUP_NOT_EXTENDED_MSG"])
        return await self._return_to_main_menu(bot, userid, conv)
