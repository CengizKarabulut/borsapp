# Laptop resource budget

The Windows startup scripts include `compose.local.yaml`. This profile caps CPU time for background financial sync, research, backfills and backups, while giving the scanner and Telegram workers higher relative CPU shares. Native numerical libraries use one thread per process, avoiding several CPU threads per worker and health probe.

The caps are per container, not a global Docker CPU limit. They apply continuously in this local profile. All existing scan timeframes, the 15-minute summary schedule, and data retention remain unchanged. Heavy reports and archive bootstrap can take longer; delivery time is not guaranteed by the summary schedule.

No hard memory limits were lowered: an aggressive limit on an 8 GB host could kill workers or increase swapping. Chrome and unused startup programs must be managed separately. Recheck resource consumption during an actual market session, since weekend measurements do not represent peak scans.

Apply without rebuilding images:

```powershell
docker compose -f compose.yaml -f compose.live.yaml -f compose.local.yaml --profile runtime --profile financials up -d --no-build
```

Applying changed environment variables recreates the affected application containers. PostgreSQL is not modified. Pending jobs remain in the database; interrupted leased jobs become eligible again when their lease expires.

To undo the local CPU/thread budget, restore the previous `compose.local.yaml` and run the same command. This does not require deleting any Docker volumes.
