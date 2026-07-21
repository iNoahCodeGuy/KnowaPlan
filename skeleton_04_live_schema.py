"""Live-DB schema check + one-time reset (pre-launch, decisions.md 7/21).

The live DB's "one planned drop/recreate" rides the post-$1-test
deploy. This morning's test proved the CHARGE path but never touched
/me/ (needs attendee_token) or the direct-pay claim flow (needs
payment_handles, claimed_at, claimed_via, paid_direct_at) — columns
create_all CANNOT add to tables that already exist.

Default run = READ-ONLY check: prints which required columns are
present or MISSING, plus row counts. Pass --reset to DROP every table
and rebuild from the current models (wipes data — safe pre-launch,
when the only rows are refunded test charges). --reset shows the
target + counts and requires typing DROP before it touches anything.

    # check (safe):
    DATABASE_URL="postgresql://<live url>" \\
        .venv/bin/python skeleton_04_live_schema.py
    # recreate (only if something is MISSING):
    DATABASE_URL="postgresql://<live url>" \\
        .venv/bin/python skeleton_04_live_schema.py --reset

config.py rewrites postgres:// -> postgresql+asyncpg:// so a Railway
URL pastes verbatim. From your laptop use the PUBLIC url; via
`railway ssh` into the app service DATABASE_URL is already set.
"""
import asyncio
import sys

from sqlalchemy.engine import make_url
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.models import Base

# The columns the 7/21 work added to already-existing tables.
REQUIRED = [
    ("attendees", "attendee_token"),
    ("planners", "payment_handles"),
    ("payments", "charge_requested_cents"),
    ("payments", "claimed_at"),
    ("payments", "claimed_via"),
    ("payments", "paid_direct_at"),
]
TABLES = ("events", "planners", "attendees", "rsvps", "payments")


async def main(reset: bool) -> None:
    url = make_url(get_settings().database_url)
    print(f"target: {url.host}/{url.database}  (user {url.username})")
    engine = get_engine()
    async with engine.connect() as conn:
        db = (await conn.execute(text("select current_database()"))).scalar()
        print(f"connected: {db}\n")
        missing: list[str] = []
        for tbl, col in REQUIRED:
            got = (
                await conn.execute(
                    text(
                        "select 1 from information_schema.columns "
                        "where table_name = :t and column_name = :c"
                    ),
                    {"t": tbl, "c": col},
                )
            ).first()
            print(f"  {tbl}.{col:<22} {'present' if got else 'MISSING'}")
            if not got:
                missing.append(f"{tbl}.{col}")
        print()
        events_rows = 0
        for t in TABLES:
            try:
                n = (
                    await conn.execute(text(f"select count(*) from {t}"))
                ).scalar()
                print(f"  rows in {t:<10} {n}")
                if t == "events":
                    events_rows = n or 0
            except Exception:
                print(f"  rows in {t:<10} (table absent)")

    if not reset:
        verdict = (
            "all present — no recreate needed."
            if not missing
            else f"MISSING {len(missing)} — rerun with --reset to fix: "
            + ", ".join(missing)
        )
        print(f"\nread-only check. {verdict}")
        await engine.dispose()
        return

    print("\n--reset DROPS every table and rebuilds from the models.")
    if events_rows:
        # Loud guard: after tomorrow, a real event lives here.
        print(f"!! this DB already has {events_rows} event row(s) — "
              "do NOT wipe a real event.")
    if input("type DROP to confirm: ").strip() != "DROP":
        print("aborted — nothing changed.")
        await engine.dispose()
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("dropped + recreated. re-run without --reset to confirm.")


if __name__ == "__main__":
    asyncio.run(main("--reset" in sys.argv))
