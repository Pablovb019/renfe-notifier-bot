#!/usr/local/bin/python3

import argparse
import asyncio
import datetime
import logging

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import dbmanager as renfebotdb
import renfechecker
from bot_data import ADMIN_ID, TOKEN
from conversations import ConvStates, RenfeBotConversations
from texts import texts as TEXTS

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.DEBUG)
logger = logging.getLogger(__name__)


class RenfeBot:
    def __init__(self, token, admin_id, database):
        self._token = token
        self._admin_id = admin_id
        self._DB = renfebotdb.RenfeBotDB(database)
        self._RF = renfechecker.RenfeChecker()
        self._CV = RenfeBotConversations(self)
        self._app = Application.builder().token(token).build()
        self._install_handlers()

    async def ask_admin_for_access(self, bot, userid, username):
        keyboard = [
            ["/admin ALLOW %d %s" % (userid, username)],
            ["/admin NOTALLOW %d %s" % (userid, username)],
        ]
        await bot.send_message(
            chat_id=self._admin_id,
            text=TEXTS["ADMIN_USER_REQ_ACCESS"].format(username=username),
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True),
        )

    async def _h_admin_access(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        userid = update.effective_user.id
        args = context.args or []
        username = "User "
        username += (update.effective_user.first_name + " ") if update.effective_user.first_name else ""
        username += (update.effective_user.last_name + " ") if update.effective_user.last_name else ""
        username += (update.effective_user.username + " ") if update.effective_user.username else ""

        msg = "Resp: "
        if userid == self._admin_id:
            if len(args) < 3:
                msg += "Invalid admin command"
            elif args[0] == "ALLOW":
                self._DB.update_user(int(args[1]), args[2], 1)
                msg += "%s ALLOWED access" % username
            elif args[0] == "NOTALLOW":
                self._DB.update_user(int(args[1]), args[2], 0)
                msg += "%s NOT ALLOWED access" % username
            else:
                msg += "Unknown admin command"
            await context.bot.send_message(chat_id=userid, text=msg, reply_markup=ReplyKeyboardRemove())
            return

        await context.bot.send_message(
            chat_id=userid,
            text="Received unauthorized message: %s from %d-%s"
            % (update.message.text, userid, username),
            reply_markup=ReplyKeyboardRemove(),
        )

    def _install_handlers(self):
        conv_handler = ConversationHandler(
            entry_points=[
                CommandHandler("start", self._CV.handler_start),
                CommandHandler("menu", self._CV.handler_start),
            ],
            states={
                ConvStates.OPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_option)],
                ConvStates.STATION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_station),
                    CallbackQueryHandler(self._CV.handler_station_callback, pattern=r"^STSEL\|"),
                ],
                ConvStates.STATION_GROUP_CHOICE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_station_group_choice)
                ],
                ConvStates.DATE: [CallbackQueryHandler(self._CV.handler_date)],
                ConvStates.PLAZA_H: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_plaza_h)],
                ConvStates.SEARCH_MODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_search_mode)],
                ConvStates.TRAIN_SELECT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_train_select),
                    CallbackQueryHandler(self._CV.handler_train_select_callback, pattern=r"^TRSEL\|"),
                ],
                ConvStates.FOLLOWUP_CONFIRM: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_followup_confirm)
                ],
                ConvStates.FOLLOWUP_LIST_ACTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_followup_list_action)
                ],
                ConvStates.FOLLOWUP_DELETE_SELECT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_followup_delete_select)
                ],
                ConvStates.ADDITIONAL_QUERY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_additional_query)
                ],
                ConvStates.ADDITIONAL_SAME_STATIONS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_additional_same_stations)
                ],
                ConvStates.ADDITIONAL_SAME_DATE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_additional_same_date)
                ],
                ConvStates.EXTEND_DECISION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_extend_decision)
                ],
                ConvStates.RECOVERY_ACTION: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self._CV.handler_recovery_action)
                ],
            },
            fallbacks=[
                CommandHandler("cancel", self._CV.handler_cancel),
                CommandHandler("start", self._CV.handler_start),
                CommandHandler("menu", self._CV.handler_start),
                CommandHandler("stats", self._h_stats),
                CommandHandler("stop", self._h_stop),
            ],
            allow_reentry=True,
        )
        self._app.add_handler(conv_handler)
        self._app.add_handler(CommandHandler("admin", self._h_admin_access))
        self._app.add_handler(CommandHandler("stats", self._h_stats))
        self._app.add_handler(CommandHandler("stop", self._h_stop))

    @staticmethod
    def _format_time_for_followup(txt):
        return txt if txt else "--:--"

    @staticmethod
    def _filter_today_trains(trains, travel_date):
        today = datetime.datetime.now().strftime("%d/%m/%Y")
        if travel_date != today:
            return trains
        now_time = datetime.datetime.now().time()
        return [t for t in trains if t["SALIDA"] > now_time]

    @staticmethod
    def _match_followup_train(available_trains, dep, arr):
        for train in available_trains:
            if train["SALIDA"].strftime("%H:%M") == dep and train["LLEGADA"].strftime("%H:%M") == arr:
                return train
        return None

    async def check_followups(self, context: ContextTypes.DEFAULT_TYPE):
        followups = self._DB.get_active_followups()
        now_ts = int(datetime.datetime.now().timestamp())
        for f in followups:
            dep = self._format_time_for_followup(f["departure_time"])
            arr = self._format_time_for_followup(f["arrival_time"])

            if now_ts >= f["expires_at"]:
                if now_ts >= f["departure_ts"]:
                    await context.bot.send_message(
                        chat_id=f["userid"],
                        text=TEXTS["FOLLOWUP_EXPIRED_DEPARTURE_MSG"].format(
                            date=f["travel_date"],
                            origin=f["origin"],
                            dep_time=dep,
                            destination=f["destination"],
                            arr_time=arr,
                        ),
                    )
                    self._DB.delete_followup(f["id"])
                else:
                    self._DB.set_followup_awaiting_extension(f["id"])
                    await context.bot.send_message(
                        chat_id=f["userid"],
                        text=TEXTS["FOLLOWUP_EXPIRED_MONTH_MSG"].format(
                            date=f["travel_date"],
                            origin=f["origin"],
                            dep_time=dep,
                            destination=f["destination"],
                            arr_time=arr,
                        ),
                    )
                continue

            res = await asyncio.to_thread(
                self._RF.check_trip,
                f["origin"],
                f["destination"],
                f["travel_date"],
                None,
                bool(f["plaza_h"]),
            )
            # Incrementar contador de consultas (siempre que se consulte Renfe)
            self._DB.increment_followup_queries(f["id"])

            if not res[0] or res[1] is None:
                continue

            trains = sorted(list(res[1]), key=lambda t: t["SALIDA"])
            trains = self._filter_today_trains(trains, f["travel_date"])
            available = [t for t in trains if t.get("DISPONIBLE")]
            if bool(f["watch_all"]):
                if len(available) == 0:
                    continue
                # Pasar a modo notifying: aviso periódico hasta /stop
                self._DB.set_followup_notifying(f["id"])
                await context.bot.send_message(
                    chat_id=f["userid"],
                    text=TEXTS["FOLLOWUP_NOTIFYING_AVAILABLE_MSG"].format(
                        origin=f["origin"],
                        destination=f["destination"],
                        date=f["travel_date"],
                        dep_time="Todos los trenes",
                    ),
                )
                continue

            match = self._match_followup_train(available, f["departure_time"], f["arrival_time"])
            if match is None:
                continue
            # Pasar a modo notifying: aviso periódico hasta /stop
            self._DB.set_followup_notifying(f["id"])
            await context.bot.send_message(
                chat_id=f["userid"],
                text=TEXTS["FOLLOWUP_NOTIFYING_AVAILABLE_MSG"].format(
                    origin=f["origin"],
                    destination=f["destination"],
                    date=f["travel_date"],
                    dep_time=dep,
                ),
            )

    async def notify_available_followups(self, context: ContextTypes.DEFAULT_TYPE):
        """Envía aviso periódico cada 10s a los seguimientos en estado 'notifying'."""
        notifying = self._DB.get_notifying_followups()
        now_ts = int(datetime.datetime.now().timestamp())
        for f in notifying:
            dep = self._format_time_for_followup(f["departure_time"])
            dep_label = dep if not bool(f["watch_all"]) else "Todos los trenes"
            # Cancelar automáticamente si el tren ya salió
            if now_ts >= f["departure_ts"]:
                self._DB.delete_followup(f["id"])
                await context.bot.send_message(
                    chat_id=f["userid"],
                    text=TEXTS["FOLLOWUP_EXPIRED_DEPARTURE_MSG"].format(
                        date=f["travel_date"],
                        origin=f["origin"],
                        dep_time=dep,
                        destination=f["destination"],
                        arr_time=self._format_time_for_followup(f["arrival_time"]),
                    ),
                )
                continue
            await context.bot.send_message(
                chat_id=f["userid"],
                text=TEXTS["FOLLOWUP_NOTIFYING_AVAILABLE_MSG"].format(
                    origin=f["origin"],
                    destination=f["destination"],
                    date=f["travel_date"],
                    dep_time=dep_label,
                ),
            )

    @staticmethod
    def _build_stats_lines(followups):
        """Genera las líneas de texto de estadísticas para una lista de followups."""
        lines = []
        for idx, f in enumerate(followups, start=1):
            dep = f["departure_time"] if f["departure_time"] else "Todos los trenes"
            daily = f.get("daily_queries") or 0
            total = f.get("total_queries") or 0
            lines.append(
                TEXTS["STATS_ITEM"].format(
                    index=idx,
                    origin=f["origin"],
                    destination=f["destination"],
                    date=f["travel_date"],
                    dep_time=dep,
                    daily=daily,
                    total=total,
                )
            )
        return lines

    async def send_daily_stats(self, context: ContextTypes.DEFAULT_TYPE):
        """Tarea diaria a las 00:00: envía resumen de consultas a cada usuario y resetea contador diario."""
        all_followups = self._DB.get_all_followups_for_daily_stats()
        # Agrupar por userid
        by_user = {}
        for f in all_followups:
            by_user.setdefault(f["userid"], []).append(f)
        for userid, followups in by_user.items():
            lines = self._build_stats_lines(followups)
            if lines:
                msg = TEXTS["DAILY_STATS_TITLE"] + "\n" + "\n".join(lines)
                await context.bot.send_message(chat_id=userid, text=msg)
        # Resetear contadores diarios tras el envío
        self._DB.reset_daily_queries()

    async def _h_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para el comando /stats."""
        userid = update.effective_user.id
        followups = self._DB.get_user_followups(userid)
        if not followups:
            await context.bot.send_message(chat_id=userid, text=TEXTS["STATS_EMPTY"])
            return
        lines = self._build_stats_lines(followups)
        msg = TEXTS["STATS_TITLE"] + "\n" + "\n".join(lines)
        await context.bot.send_message(chat_id=userid, text=msg)

    async def _h_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handler para el comando /stop: detiene los avisos de seguimientos en estado 'notifying'."""
        userid = update.effective_user.id
        stopped = self._DB.stop_user_notifying_followups(userid)
        if not stopped:
            await context.bot.send_message(chat_id=userid, text=TEXTS["STOP_EMPTY"])
            return
        lines = []
        for f in stopped:
            dep = f["departure_time"] if f["departure_time"] else "Todos los trenes"
            lines.append(f"• {f['origin']} - {f['destination']} ({f['travel_date']} {dep})")
        msg = TEXTS["STOP_SUCCESS"].format(items="\n".join(lines))
        await context.bot.send_message(chat_id=userid, text=msg)

    def register_jobs(self):
        if self._app.job_queue is not None:
            self._app.job_queue.run_repeating(
                self.check_followups, interval=30, first=0, name="followups-30s"
            )
            self._app.job_queue.run_repeating(
                self.notify_available_followups, interval=10, first=10, name="notifying-10s"
            )
            # Tarea diaria a las 00:00 (hora local del servidor)
            self._app.job_queue.run_daily(
                self.send_daily_stats,
                time=datetime.time(hour=0, minute=0, second=0),
                name="daily-stats-00",
            )

    def start(self):
        logger.info("=" * 60)
        logger.info("✅ BOT STARTED - READY FOR /start COMMAND")
        logger.info("=" * 60)
        self.register_jobs()
        try:
            self._app.run_polling()
        finally:
            self._RF.close()


def parse_arguments():
    parser = argparse.ArgumentParser("RenfeBot: check renfe web for tickets")
    parser.add_argument(
        "--database",
        "-d",
        help="Database location",
        dest="database",
        default="/mnt/shared/renfebot.db",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_arguments()
    rb = RenfeBot(TOKEN, ADMIN_ID, args.database)
    rb.start()
