#!/usr/bin/env python3
#
# A library that allows to create an inline calendar keyboard.
# grcanosa https://github.com/grcanosa
#
"""
Base methods for calendar keyboard creation and processing.
"""


from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import datetime
import calendar

def create_callback_data(action,year,month,day):
    """ Create the callback data associated to each button"""
    return ";".join([action,str(year),str(month),str(day)])

def separate_callback_data(data):
    """ Separate the callback data"""
    return data.split(";")


def create_calendar(year=None, month=None, min_date=None, max_date=None):
    """
    Create an inline keyboard with the provided year and month
    :param int year: Year to use in the calendar, if None the current year is used.
    :param int month: Month to use in the calendar, if None the current month is used.
    :return: Returns the InlineKeyboardMarkup object with the calendar.
    """
    now = datetime.datetime.now()
    if year == None: year = now.year
    if month == None: month = now.month
    data_ignore = create_callback_data("IGNORE", year, month, 0)
    keyboard = []
    #First row - Month and Year
    row=[]
    row.append(InlineKeyboardButton(calendar.month_name[month]+" "+str(year),callback_data=data_ignore))
    keyboard.append(row)
    #Second row - Week Days
    row=[]
    for day in ["Mo","Tu","We","Th","Fr","Sa","Su"]:
        row.append(InlineKeyboardButton(day,callback_data=data_ignore))
    keyboard.append(row)

    my_calendar = calendar.monthcalendar(year, month)
    for week in my_calendar:
        row=[]
        for day in week:
            if(day==0):
                row.append(InlineKeyboardButton(" ",callback_data=data_ignore))
            else:
                day_date = datetime.date(year, month, day)
                disabled = False
                if min_date is not None and day_date < min_date:
                    disabled = True
                if max_date is not None and day_date > max_date:
                    disabled = True
                if disabled:
                    row.append(InlineKeyboardButton("·", callback_data=data_ignore))
                else:
                    row.append(InlineKeyboardButton(str(day),callback_data=create_callback_data("DAY",year,month,day)))
        keyboard.append(row)
    #Last row - Buttons
    row=[]
    prev_month = (datetime.date(year, month, 1) - datetime.timedelta(days=1)).replace(day=1)
    next_month = (datetime.date(year, month, 1) + datetime.timedelta(days=31)).replace(day=1)
    prev_allowed = True
    next_allowed = True
    if min_date is not None:
        prev_allowed = not (prev_month.year < min_date.year or
                            (prev_month.year == min_date.year and prev_month.month < min_date.month))
    if max_date is not None:
        next_allowed = not (next_month.year > max_date.year or
                            (next_month.year == max_date.year and next_month.month > max_date.month))

    row.append(InlineKeyboardButton("<" if prev_allowed else " ",callback_data=create_callback_data("PREV-MONTH",year,month,1) if prev_allowed else data_ignore))
    row.append(InlineKeyboardButton(" ",callback_data=data_ignore))
    row.append(InlineKeyboardButton(">" if next_allowed else " ",callback_data=create_callback_data("NEXT-MONTH",year,month,1) if next_allowed else data_ignore))
    keyboard.append(row)

    return InlineKeyboardMarkup(keyboard)


async def process_calendar_selection(update, min_date=None, max_date=None):
    """
    Process the callback_query. This method generates a new calendar if forward or
    backward is pressed. This method should be called inside a CallbackQueryHandler.
    :param telegram.Bot bot: The bot, as provided by the CallbackQueryHandler
    :param telegram.Update update: The update, as provided by the CallbackQueryHandler
    :return: Returns a tuple (Boolean,datetime.datetime), indicating if a date is selected
                and returning the date if so.
    """
    ret_data = (False,None)
    query = update.callback_query
    (action,year,month,day) = separate_callback_data(query.data)
    curr = datetime.datetime(int(year), int(month), 1)
    if action == "IGNORE":
        await query.answer()
    elif action == "DAY":
        selected_date = datetime.datetime(int(year),int(month),int(day))
        if min_date is not None and selected_date.date() < min_date:
            await query.answer(text="Fecha fuera de rango")
            return ret_data
        if max_date is not None and selected_date.date() > max_date:
            await query.answer(text="Fecha fuera de rango")
            return ret_data
        await query.edit_message_text(text=query.message.text)
        ret_data = True, selected_date
    elif action == "PREV-MONTH":
        pre = curr - datetime.timedelta(days=1)
        pre_first = datetime.date(int(pre.year), int(pre.month), 1)
        if min_date is not None and (pre_first.year < min_date.year or
                                     (pre_first.year == min_date.year and pre_first.month < min_date.month)):
            await query.answer()
            return ret_data
        await query.edit_message_text(
            text=query.message.text,
            reply_markup=create_calendar(
                int(pre.year),
                int(pre.month),
                min_date=min_date,
                max_date=max_date,
            ),
        )
    elif action == "NEXT-MONTH":
        ne = curr + datetime.timedelta(days=31)
        ne_first = datetime.date(int(ne.year), int(ne.month), 1)
        if max_date is not None and (ne_first.year > max_date.year or
                                     (ne_first.year == max_date.year and ne_first.month > max_date.month)):
            await query.answer()
            return ret_data
        await query.edit_message_text(
            text=query.message.text,
            reply_markup=create_calendar(
                int(ne.year),
                int(ne.month),
                min_date=min_date,
                max_date=max_date,
            ),
        )
    else:
        await query.answer(text="Something went wrong!")
        # UNKNOWN
    return ret_data
