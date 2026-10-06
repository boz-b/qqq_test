# Mac publishing setup — awaiting activation

Task MAC-PUBLISH-20261005 prepares the restored Mac publisher. Boz changed the
schedule on 2026-10-05 to Tuesday and Wednesday–Saturday **01:00 Europe/Istanbul**.
Keep the Mac awake; review missed runs manually, with no automatic catch-up.
This replaces the earlier 02:00 intent for the Mac. The Pi remains paused.

## Prepared behavior

`scripts/mac_publish.py` renders an uninstalled launchd plist or runs the guarded
publisher. The existing Linux cron installer remains historical Pi behavior;
do not install it on this Mac. Refresh-script timestamps now use portable BSD/GNU
date formatting. No additional dependency is required.

The launchd calendar uses the host timezone, which must remain Europe/Istanbul;
setting TZ alone does not configure launchd's calendar. The wrapper checks both
the host timezone and current Istanbul time. It accepts only the 01:00 minute on
Tuesday–Saturday. Later wake events are logged and skipped, so launchd's native
coalesced wake behavior does not perform a delayed refresh. A restart/login does
not request an immediate run. Delays beyond that minute intentionally require
review. At 01:00 Istanbul the New York date is still the preceding market date
in both winter and summer. The wrapper pins that date for news summarization.

One kernel lock covers the entire Tuesday combined job or nightly job. A dated
attempt receipt is flushed before ingestion; failed/interrupted slots are never
automatically retried. Inspect failed receipts, Git status, cache/DB state and
provider quota before authorizing a manual repair. Never delete a receipt to
silently enable a retry. All manual publishing must respect this same lock;
direct refresh/export scripts bypass the wrapper and are not safe dry runs.

## Dedicated publishing checkout

Keep `/Volumes/SSD/Projects/qqq_test` as the development/data owner with its
existing modified AGENTS.md preserved. After the code is reviewed and merged,
prepare a separate clean clone at `/Volumes/SSD/Projects/qqq-publisher` on main.
A separate clone permits both development and publishing main checkouts without
Git worktree branch conflicts. Configure that clone's GitHub HTTPS authentication
with the existing Mac keychain-backed gh login; no migrated SSH key is needed.
Verify unattended Git credential access in the actual launchd session before
activation. Do not embed credentials in the remote URL or plist.

Use the existing native QQQ environment through an explicit `venv` link. Seed
the publisher's ignored caches from a checked snapshot of the accepted QQQ data;
retain the originals. Do not share mutable data directories between development
and scheduled writers. Configure provider files securely in its ignored env
directory; preserve the accepted Gemini model and Brave limits from the owning
context, with no broader history backfill or additional quota scope.

The restored PostgreSQL cluster remains stopped, Unix-socket-only, port 55437.
Activation must explicitly approve startup and changing the qqq_test role's
read-only default for scheduled ingestion. Keep TCP disabled and maintenance
credentials out of the publisher. The wrapper checks DB availability and
transaction writability before providers; existing backfill/parity gates still
run before export. It never starts the DB or alters its permissions itself.

## Activation checklist, not commands to run during preparation

1. Review/publish/merge this code through the normal issue/PR workflow. Preserve
   the existing dirty development checkout and all recovery material.
2. Recheck the Pi's two QQQ cron lines are still paused and no QQQ writer is
   running. Never resume Pi and Mac publishers together.
3. Prepare the dedicated clone, ignored caches and local environment. Boz enters
   Finnhub/Gemini/Brave credentials using a local editor or approved secure store;
   never request values in chat or restore old authentication stores.
4. Review DB startup/write configuration and startup-after-login behavior. A
   user LaunchAgent requires boz's login; after restart/FileVault unlock, log in
   before the scheduled slot. Until an approved DB startup arrangement exists,
   a stopped DB causes the slot to fail before ingestion. No automatic retry.
5. Confirm host timezone, SSD mounted, AC system sleep disabled (observed sleep=0),
   Git main clean and synchronized, unattended Git auth and provider configuration.
   Disk/display sleep need not be disabled. Wake-on-network is not a schedule.
6. Review a bounded first provider/DB/publish run and exact activation approval.
   Even `EXPORT_JSON_FLAGS=--no-git` still calls providers and mutates local data.
7. Render the plist using `venv/bin/python scripts/mac_publish.py --render-plist
   /Volumes/SSD/Projects/qqq-publisher`, review it, create its logs directory, and
   install/bootstrap it only after approval. Copy the non-secret activation JSON
   template to ignored `env/mac-publishing.json`; change enabled to true only
   during that approved cutover. No activation file is created by this patch.

Recovery: disable/bootout the Mac job first, preserve any in-flight process and
attempt evidence, and assess divergent Git/CSV/DB state before a selected retry
or Pi rollback. A failed push may leave a local data commit; do not reset it.
The static site keeps its last published data. No deletion, migration repeat,
old gateway restoration or automatic Pi rollback follows from this setup.

## Subscription-based summaries

The `codex` news provider is configured separately in ignored
`env/codex_summary.env`; see ENVIRONMENT.md. Pin the absolute CLI executable path
for launchd, verify ChatGPT subscription authentication in that user session, and
keep the existing keys for rollback. The publisher uses the same 01:00 schedule,
lock, receipt and DB parity gates. Merge the provider implementation before enabling
the override in the clean publisher; never run a feature branch as the publisher.
