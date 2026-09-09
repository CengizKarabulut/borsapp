-- The 2026-09-09 acceptance run rendered the documents but rolled back the
-- report/hisse jobs when a deterministic artifact_id already existed.
-- No worker from that run remains active; safely make only those jobs claimable again.
UPDATE command_jobs
SET status = 'pending',
    started_at = NULL,
    lease_until = NULL,
    error_detail = NULL
WHERE status = 'running'
  AND command_name IN ('rapor', 'hisse')
  AND requested_at >= TIMESTAMPTZ '2026-09-09 10:00:00+00';
