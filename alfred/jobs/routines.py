"""Alfred's daily and weekly routines. Each one is a task for the agent plus delivery rules."""
from __future__ import annotations

import json
import logging
from datetime import datetime

from alfred.tools import ToolContext

log = logging.getLogger(__name__)

NO_NEWS = "NOTHING_TO_REPORT"


class Routines:
    def __init__(self, cfg, store, alfred, notifier):
        self.cfg, self.store, self.alfred, self.notifier = cfg, store, alfred, notifier

    def _for_each_adult(self, instruction_for):
        for m in self.cfg.adults:
            text = self.alfred.task(instruction_for(m), effort="low")
            if text and NO_NEWS not in text:
                self.notifier.send(m.id, text, subject="Your morning brief")

    # ---- 07:00 every day ---------------------------------------------------------
    def morning_brief(self) -> None:
        def instr(m):
            work = self.cfg.locations.get(m.work_location) if m.work_location else None
            return (
                f"Write {m.name}'s morning brief for WhatsApp. Check: family_agenda for today; weather_forecast "
                f"for home; rain_next_two_hours at home" + (f" and at {m.work_location}" if work else "") +
                "; weather_warnings; train_disruptions; and recent email "
                f"(search_email owner={m.id}, days=1) for anything family-relevant that needs attention today "
                "or soon: appointments, bills or deadlines, school notes, deliveries. If you find a dated "
                "appointment not yet on a calendar, use propose_family_calendar_event and mention its number. "
                "Lead with what affects the day. Keep it to about six short lines and finish with one small, "
                "kind suggestion (a healthy lunch idea, a walk, a call to someone). Do not mention sources that "
                "are unavailable unless it matters."
            )
        self._for_each_adult(instr)

    # ---- every 30 minutes ------------------------------------------------------
    def weather_guard(self) -> None:
        """Urgent alerts for orange/red warnings; no model call unless there is something new."""
        reg = self.alfred.registry
        text, err = reg.execute("weather_warnings", {}, ToolContext("system"))
        if err:
            return
        warnings = [w for w in json.loads(text)["warnings"] if w["level"] in ("orange", "red")]
        fresh = [w for w in warnings if not self.store.seen_before(f"warn:{w['event']}:{w['level']}:{w['onset']}")]
        if not fresh:
            return
        msg = self.alfred.task(
            "Write a short, calm WhatsApp alert to the family about these new official weather warnings for "
            "our area. Say what, when, and one or two practical precautions (cycling, driving the A2, the "
            "garden, the children). Data:\n" + json.dumps(fresh, ensure_ascii=False), effort="low")
        urgent = any(w["level"] == "red" for w in fresh)
        self.notifier.broadcast(msg, urgent=urgent, subject="Weather warning")

    # ---- hourly, 08:00–21:00 -----------------------------------------------------
    def email_scan(self) -> None:
        """Spot new appointments/tickets/deadlines in mail and propose them for the Family calendar."""
        for m in self.cfg.adults:
            if not (m.gmail or m.icloud_mail):
                continue
            text = self.alfred.task(
                f"Look through {m.name}'s email from the last day (search_email owner={m.id}, days=1). For "
                "each email that contains a concrete, dated appointment, event, ticket or deadline that "
                "concerns the family and is not already on family_agenda, call "
                "propose_family_calendar_event once (check pending_proposals first to avoid duplicates). "
                f"Then write one short WhatsApp message to {m.name} listing the new proposals with their "
                f"numbers and asking for 'yes <number>'. If there is nothing new, reply only {NO_NEWS}.",
                effort="low")
            if text and NO_NEWS not in text:
                self.notifier.send(m.id, text, subject="Shall I add these to the calendar?")

    # ---- Sunday 18:00 ----------------------------------------------------------------
    def week_ahead(self) -> None:
        text = self.alfred.task(
            "Prepare the family's Sunday evening 'week ahead' message. Use family_agenda for the next 7 days "
            "and weather_forecast for home. Point out clashes, early starts, late evenings, and days when "
            "someone needs to drive or collect the children. Then suggest a plan for next weekend with 2–3 "
            "options that fit the forecast, the family's preferences (recall_preferences) and a sensible "
            "budget. Use web_search to find real events, markets, museums, walks or activities in and around "
            "'s-Hertogenbosch and Eindhoven, with date, price and link. Include at least one free outdoor "
            "option, and, if the week looks busy, a gentle suggestion of an hour for the two of them. Keep it "
            "readable on a phone: short sections, no tables.", effort="high", web=True)
        self.notifier.broadcast(text, subject="The week ahead")

    # ---- Saturday 09:00 --------------------------------------------------------------
    def meal_plan(self) -> None:
        text = self.alfred.task(
            "Plan healthy family dinners for the coming week (Monday to Sunday). First recall_preferences "
            "(food and health) for everyone, check family_agenda for the week so that busy evenings get quick "
            "meals, and fetch shop_offers with kind 'groceries'. Build the menu around good offers on fresh "
            "food: plenty of vegetables, fish twice, at least two vegetarian nights, and little ultra-processed "
            "food. Then add the ingredients to the shopping list with add_to_shopping_list, noting the shop "
            "with the best offer for each. Message: the 7 dinners (one line each, with minutes to cook), the "
            "best 3–5 savings, and 'Reply with any changes, or \"perfect\".' Mention any drugstore offers "
            "(Etos, Holland & Barrett) only if they match something the family uses.", effort="medium")
        self.notifier.broadcast(text, subject="This week's menu and shopping list")

    # ---- daily 03:00 -------------------------------------------------------------------
    def housekeeping(self) -> None:
        self.store.purge_old(days=90)


JOBS = ["morning_brief", "weather_guard", "email_scan", "week_ahead", "meal_plan", "housekeeping"]


def schedule(scheduler, routines: Routines, cfg) -> None:
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    s, tz = cfg.schedule, cfg.timezone

    def at(hhmm: str, **kw):
        h, m = hhmm.split(":")
        return CronTrigger(hour=int(h), minute=int(m), timezone=tz, **kw)

    scheduler.add_job(routines.morning_brief, at(s.get("morning_brief", "07:00")), id="morning_brief")
    scheduler.add_job(routines.weather_guard, IntervalTrigger(minutes=int(s.get("weather_check_minutes", 30))),
                      id="weather_guard")
    scheduler.add_job(routines.email_scan, CronTrigger(minute=5, hour="8-21", timezone=tz), id="email_scan")
    scheduler.add_job(routines.week_ahead, at(s.get("week_ahead", "18:00"), day_of_week="sun"), id="week_ahead")
    scheduler.add_job(routines.meal_plan, at(s.get("meal_plan", "09:00"), day_of_week="sat"), id="meal_plan")
    scheduler.add_job(routines.housekeeping, at("03:00"), id="housekeeping")
    log.info("scheduled jobs at %s", datetime.now(tz).isoformat())
