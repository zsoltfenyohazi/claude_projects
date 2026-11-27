"""Command line:
    python -m alfred chat <member_id>          talk to Alfred in the terminal
    python -m alfred run <job>                 run one routine now (add ALFRED_DRY_RUN=1 to print only)
    python -m alfred google-auth <member_id>   connect a Google account (one-off)
    python -m alfred tools                     list Alfred's capabilities
"""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="alfred")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("chat")
    c.add_argument("member_id")
    r = sub.add_parser("run")
    from alfred.jobs.routines import JOBS
    r.add_argument("job", choices=JOBS)
    g = sub.add_parser("google-auth")
    g.add_argument("member_id")
    g.add_argument("--client-secrets", default="config/google_client_secret.json")
    sub.add_parser("tools")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    from alfred.app import build_app

    if args.cmd == "google-auth":
        from alfred.config import load_config
        from alfred.integrations.google import GoogleIntegration
        path = GoogleIntegration(load_config()).authorise(args.member_id, args.client_secrets)
        print(f"Very good. Token saved to {path}.")
        return 0

    app = build_app()
    if args.cmd == "tools":
        for name in app.alfred.registry.names():
            print(name)
        return 0
    if args.cmd == "run":
        getattr(app.routines, args.job)()
        return 0
    if args.cmd == "chat":
        member = app.cfg.member(args.member_id)
        print(f"Alfred is listening, {member.address_as}. (Ctrl-D to finish)")
        for line in sys.stdin:
            if line.strip():
                print("\nAlfred: " + app.handle_message(member.id, line.strip(), channel="terminal") + "\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
