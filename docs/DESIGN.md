# Alfred — design

Alfred is a family butler for a household in Engelen ('s-Hertogenbosch, NL). The family works in Eindhoven and shops in Den Bosch. He keeps the household organised, looks after health, money and time together, and talks to the family over WhatsApp, with email and SMS as fallbacks. In voice he is a warm, discreet, middle-aged British butler.

## 1. Principles
1. **He cannot, not merely will not.** Risky abilities are left out of the code. There is no tool to send email as the family, buy, book, pay or delete. The Gmail token has only the `gmail.readonly` scope, and the IMAP mailbox is opened with `EXAMINE`, which is read-only.
2. **One guarded write.** Alfred may add events to the shared *Family* Google calendar only. He first creates a numbered *proposal*, and **code, not the model**, carries it out once an adult replies `yes <n>` (`alfred/confirmations.py`).
3. **Only the family.** Messages go only to numbers and addresses in `family.yaml`. Messages from unknown numbers are ignored and logged.
4. **External text is data.** Email, web and shop pages are wrapped in `<untrusted_content>` (`guards.untrusted`). The persona tells Alfred never to follow instructions inside it. Even a successful prompt injection could at most create a proposal that a human must approve.
5. **Privacy between spouses.** Each mailbox is private to its owner unless `share_mail_with_family: true`. Scheduled jobs read mail only to pick out family-relevant items.
6. **Calm.** Quiet hours run 22:00–07:00. Only red weather warnings break them. Alerts are de-duplicated.
7. **Accountable.** Every tool call, LLM call (with token counts) and message is written to an audit log ("Alfred, what did you do today?"). Old history is purged after 90 days.

## 2. Architecture
```
WhatsApp ──► Caddy (HTTPS) ──► FastAPI /webhook/whatsapp ──► App.handle_message
                                    │                         ├─ confirmations (yes/no → Family calendar)
                                    │                         └─ Alfred.chat ─► Claude tool loop ─► ToolRegistry
APScheduler ──► Routines (brief, weather guard, email scan, week ahead, meal plan) ─┘        │
                                                                                         guards + audit
Notifier ──► WhatsApp (template outside 24 h) / Alfred's own mailbox / Twilio SMS (urgent only)
SQLite: memory · history · proposals · shopping list · seen · cache · audit
```
* **Model:** `claude-opus-5-5` on the Messages API with adaptive thinking.
  * Effort is `low` for chat and alerts, `medium` for meal planning and `high` for the week ahead.
  * Server-side refusal `fallbacks: "default"` is enabled.
  * The persona plus family profile form a stable, cached system prompt; the date and speaker go in the user turn so the cache holds.
* **Web search** (Anthropic server tool, located to 's-Hertogenbosch) finds events, activities and news without fragile scrapers.
* **Shop offers:** each shop's public offers page is turned into text, and Claude extracts the offers into a strict JSON schema. Results are cached for 12 hours, and each shop fails on its own without affecting the rest.
* **Hosting:** the family hosts it themselves on a small EU VPS (data stays in the EU, and the tokens stay on the family's server). Anthropic Managed Agents could host the loop later if wanted.

## 3. Capabilities
| Routine | When | What |
|---|---|---|
| Morning brief | 07:00 daily, per adult | Agenda, weather, rain at home/work, KNMI warnings, NS disruptions, urgent mail, one kind suggestion |
| Weather guard | every 30 min | New orange/red warnings for Noord-Brabant, sent to both adults (red breaks quiet hours) |
| Email scan | hourly 08–21 | Dated appointments, tickets and deadlines in mail become numbered calendar proposals |
| Week ahead | Sun 18:00 | Clashes, early starts, who drives where; 2–3 weekend options (real events, prices, links); an hour for the couple when the week is busy |
| Meal plan | Sat 09:00 | 7 healthy dinners around this week's offers, quick meals on busy nights, shopping list by shop |
| Chat | any time | Questions, "remember that…", "forget that", shopping list, activity ideas, drafting a reply for you to send |

## 4. Data sources
| Need | Source | Notes |
|---|---|---|
| Forecast | Open-Meteo | free, no key |
| Rain radar | Buienradar raintext | 2-hour rain nowcast per location |
| Warnings | MeteoAlarm feed (KNMI data) | code geel/oranje/rood per province |
| Trains | NS API (disruptions v3) | free key from apiportal.ns.nl |
| Calendars | Google Calendar API, iCloud CalDAV | read; write only to the Family calendar |
| Mail | Gmail API (readonly), iCloud IMAP (EXAMINE/PEEK) | app-specific password for iCloud |
| Offers | AH, Plus, Lidl, Aldi, Ekoplaza, Etos, Holland & Barrett, Bol, Coolblue pages | some are JavaScript-heavy; swap in folder URLs |
| Events/news | Claude web search | Uit in Den Bosch, Eindhoven365, Omroep Brabant, etc. |

## 5. Roadmap
* **Phase 2:**
  * Municipal announcements (overheid.nl SRU API for 's-Hertogenbosch and Eindhoven: road works, permits).
  * Omroep Brabant / 112 RSS near home and work.
  * Waste-collection calendar.
  * Bol/Coolblue price watches on named items.
  * NDW traffic on the A2/A59.
* **Phase 3:**
  * **Finances:** a subscription and bill tracker built from email, with a monthly "where the money went" note.
  * **Health:** activity nudges and a weekly vegetable-variety score.
  * **Relationships:** birthdays and gift ideas (suggest only), date-night reminders, a family-time balance.
* **Possible later:** a small web dashboard to view and edit what Alfred remembers.

## 6. Costs (rough)
* **VPS:** about €5/month.
* **Claude API:** a few euros a month at this volume. Each LLM call's token counts are logged for review.
* **WhatsApp:** replies within 24 h are free; template messages (proactive briefs) cost a few cents each.
* **Web search:** billed per search, at most 5 per request.
