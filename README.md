# Alfred — your family butler

> "Good morning, sir. Rain on the A2 from half past seven, so you may wish to leave ten minutes early. Madam has the dentist at 16:00, and Albert Heijn has salmon at 35% off — shall I add it to the list?"

Alfred reads your and your wife's email and calendars and keeps the shared Family calendar. He watches the weather, trains and the week's offers, plans healthy meals and weekend outings, and learns your preferences. He talks to you over WhatsApp. **He cannot buy anything, send email on your behalf, or change anything except the Family calendar, and he does that only after you reply "yes".**

Design and safety model: [docs/DESIGN.md](docs/DESIGN.md).

## Try it locally (5 minutes, no accounts needed)
```bash
pip install -r requirements.txt
```
```bash
cp config/family.example.yaml config/family.yaml && cp .env.example .env
```
```bash
export ANTHROPIC_API_KEY=sk-ant-...   # your key from console.anthropic.com
```
```bash
ALFRED_DRY_RUN=1 python -m alfred chat dad
```
`chat` talks to Alfred in the terminal. Weather and offers work straight away. Calendars and mail appear once they are connected (below). To run a routine once and print it instead of sending it:
```bash
ALFRED_DRY_RUN=1 python -m alfred run week_ahead
```
The other routines are `morning_brief`, `weather_guard`, `email_scan` and `meal_plan`.

Run the tests:
```bash
python -m pytest -q
```

## Connect your accounts
1. **Google (your Gmail + Calendar):**
   * In Google Cloud Console, create a project, enable the *Gmail API* and *Google Calendar API*, and create an OAuth client of type *Desktop*.
   * Save it as `config/google_client_secret.json`.
   * In Google Calendar, create a calendar called **Family**, share it with your wife, and put its Calendar ID in `family.yaml`.
   * Then run the command below and open the link it prints:
     ```bash
     python -m alfred google-auth dad
     ```
   * Alfred asks only for *read-only* Gmail access. Calendar write access is used for the Family calendar alone, and the code refuses any other calendar.
2. **iCloud (your wife's mail + calendar):**
   * At appleid.apple.com, go to Sign-In and Security, then App-Specific Passwords, and create one.
   * Put it in `.env` as `ICLOUD_PASSWORD_MUM`.
   * Her mailbox is opened read-only, and nothing is marked as read.
3. **WhatsApp:**
   * In Meta for Developers, create an app, add WhatsApp, and register a spare phone number for Alfred.
   * Copy the token, phone number ID and app secret into `.env`.
   * Set the webhook to `https://<your-domain>/webhook/whatsapp` with your `WHATSAPP_VERIFY_TOKEN`, and subscribe to *messages*.
   * Create a *Utility* template named `alfred_notice` (language English UK) whose body is `{{1}}`. Alfred needs it for morning briefs sent more than 24 h after your last message.
4. **Optional:**
   * A free NS API key (apiportal.ns.nl) for train disruptions.
   * A separate mailbox for Alfred to email you from (SMTP settings in `.env`).
   * Twilio for SMS on urgent alerts.

Privacy: each mailbox is private to its owner. Your wife can't ask Alfred about your mail, nor you about hers, unless `share_mail_with_family: true` is set.

## Run it on a server
On a small EU VPS (e.g. Hetzner, about €5/month) with Docker, point a domain at it and put that domain in `Caddyfile`. Then:
```bash
docker compose up -d --build
```
Caddy provides HTTPS automatically. Back up the `data/` folder, which holds Alfred's memory and the Google tokens.

## Talking to Alfred
- "What's on this week?" · "Anything I should know before I leave?"
- "Remember that Tom doesn't like mushrooms." · "What do you know about me?" · "Forget number 4."
- "Plan something nice for Saturday, outdoors if it's dry." · "Any good deals on nappies?"
- "Help me reply to the school." (Alfred drafts the text; you send it.)
- When he proposes an appointment: reply **yes 3**, **no 3**, or **yes all**.
- "What did you do today?" shows his activity log.

## Layout
```
alfred/agent.py          Claude tool loop, persona, caching, refusal fallbacks
alfred/persona.md        Alfred's character and hard limits
alfred/guards.py         the safety rules (tool allowlist, Family-calendar-only, recipients, quiet hours)
alfred/confirmations.py  "yes 3" → Family calendar (done by code, not the model)
alfred/tools/            calendars, mail, weather, trains, offers, memory/shopping list
alfred/integrations/     Google (Gmail/Calendar) and iCloud (IMAP/CalDAV)
alfred/channels/         WhatsApp, email (Alfred's own mailbox), SMS, notifier
alfred/jobs/routines.py  morning brief, weather guard, email scan, week ahead, meal plan
alfred/main.py           webhook + scheduler service
```
