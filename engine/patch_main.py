#!/usr/bin/env python3
"""Patch main.py with Discord nightly job."""

with open('main.py', 'r', encoding='utf-8', errors='replace') as f:
    lines = f.readlines()

insert_pos = None
for i, line in enumerate(lines):
    if 'Morning brief init failed (non-fatal)' in line:
        insert_pos = i + 1
        break

if insert_pos:
    new_code = '''
    # Initialize Nightly Discord Import (6:00 AM CT, Mon–Fri)
    try:

        async def run_nightly_discord() -> None:
            """Run Discord nightly import + sentiment ETL, emit completion event."""
            try:
                import scripts.nightly_discord as nd_module

                import_stats = nd_module.run_discord_import()
                sentiment_stats = nd_module.run_sentiment_etl()

                logger.info(f"Discord import complete: {import_stats}")
                logger.info(f"Discord sentiment ETL complete: {sentiment_stats}")

                from websocket.events import publish_event

                combined_stats = {"import": import_stats, "sentiment_etl": sentiment_stats}
                publish_event(
                    "system",
                    f"Discord nightly import complete: {combined_stats}",
                    severity="info",
                )

            except Exception as exc:
                logger.error("[Discord] Nightly import failed: %s", exc, exc_info=True)
                from websocket.events import publish_event

                publish_event("system", "Discord nightly import FAILED", severity="warn")

        if scheduler is not None:
            scheduler.add_job(
                run_nightly_discord,
                CronTrigger(
                    day_of_week="mon-fri",
                    hour=6,
                    minute=0,
                    timezone="America/Chicago",
                ),
                id="nightly_discord_import",
                name="Nightly Discord Import",
                max_instances=1,
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info("✅ Discord nightly import job registered — fires Mon–Fri at 06:00 CT")
    except Exception as _discord_err:
        logger.warning(f"Discord nightly import init failed (non-fatal): {_discord_err}")

'''
    lines.insert(insert_pos, new_code)
    with open('main.py', 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f'Inserted at {insert_pos}')
else:
    print('Not found')
