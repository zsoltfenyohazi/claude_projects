"""HTTP service: WhatsApp webhook + scheduler. Run with:  uvicorn alfred.main:api --host 0.0.0.0 --port 8000"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse

from alfred.app import build_app
from alfred.channels.whatsapp import parse_inbound, verify_signature

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("alfred")

state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    app = build_app()
    state["app"] = app
    if os.environ.get("ALFRED_SCHEDULER", "1") == "1":
        from apscheduler.schedulers.background import BackgroundScheduler

        from alfred.jobs.routines import schedule
        scheduler = BackgroundScheduler(timezone=app.cfg.timezone, job_defaults={"coalesce": True,
                                                                                  "misfire_grace_time": 900})
        schedule(scheduler, app.routines, app.cfg)
        scheduler.start()
        state["scheduler"] = scheduler
    log.info("Alfred is at your service.")
    yield
    if "scheduler" in state:
        state["scheduler"].shutdown(wait=False)


api = FastAPI(title="Alfred", lifespan=lifespan)


@api.get("/health")
def health():
    return {"status": "ok"}


@api.get("/webhook/whatsapp")
def verify(request: Request):
    p = request.query_params
    if p.get("hub.mode") == "subscribe" and p.get("hub.verify_token") == state["app"].cfg.secrets.get(
            "WHATSAPP_VERIFY_TOKEN"):
        return PlainTextResponse(p.get("hub.challenge", ""))
    raise HTTPException(status_code=403)


def _respond(number: str, text: str, message_id: str | None) -> None:
    app = state["app"]
    member = app.cfg.member_by_whatsapp(number)
    if member is None:  # strangers get no reply at all
        app.store.audit("unknown", "inbound:ignored", f"message from non-family number ending {number[-3:]}")
        return
    try:
        if message_id and app.whatsapp.configured:
            app.whatsapp.mark_read(message_id)
        reply = app.handle_message(member.id, text)
    except Exception:
        log.exception("handling message failed")
        reply = "My apologies, something went amiss on my side. Might you try again in a moment?"
    app.notifier.send(member.id, reply, channel="whatsapp", urgent=True)  # replies are never held back


@api.post("/webhook/whatsapp")
async def inbound(request: Request, background: BackgroundTasks):
    body = await request.body()
    app = state["app"]
    if not verify_signature(app.cfg.secrets.get("WHATSAPP_APP_SECRET", ""), body,
                            request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(status_code=401)
    for msg in parse_inbound(await request.json()):
        if msg.get("id") and app.store.seen_before(f"wamid:{msg['id']}"):
            continue  # Meta retries deliveries; answer each message once
        background.add_task(_respond, msg["from"], msg["text"], msg.get("id"))
    return {"ok": True}
