import os
import unittest
from datetime import UTC, datetime

from market_intelligence.application.candidate_followups import enqueue_candidate_followups
from market_intelligence.persistence.postgres.command_jobs import PostgresCommandJobRepository


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class CandidateJobIntegrationTests(unittest.TestCase):
    def test_real_insert_conflict_and_claim_context(self):
        import psycopg

        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as c:
            c.execute(
                "CREATE TEMP TABLE instrument_symbols (instrument_id uuid,symbol text,valid_from date,valid_to date)"
            )
            c.execute(
                "INSERT INTO instrument_symbols VALUES ('00000000-0000-0000-0000-000000000001','TEST','2026-01-01',NULL)"
            )
            c.execute(
                "CREATE TEMP TABLE command_jobs(job_id uuid default gen_random_uuid(),command_name text,instrument_id uuid,symbol_at_request text,requested_by bigint,requested_topic bigint,request_key text unique,context jsonb,status text default 'pending',attempt_count int default 0,requested_at timestamptz default now(),started_at timestamptz,lease_until timestamptz,error_detail text,finished_at timestamptz)"
            )
            c.execute("CREATE TEMP TABLE telegram_outbox(semantic_key text,status text)")
            target = datetime(2026, 9, 11, 15, tzinfo=UTC)
            ranked = [dict(symbol="TEST", direction="bullish", scanners=["a", "b"])]
            self.assertEqual(enqueue_candidate_followups(c, "1h", target, ranked, 10), 3)
            self.assertEqual(enqueue_candidate_followups(c, "1h", target, ranked, 10), 0)
            self.assertEqual(enqueue_candidate_followups(c, "4h", target, ranked, 10), 2)
            job = PostgresCommandJobRepository(c).claim(now=target)
            self.assertTrue(job.context["automatic"])
            self.assertEqual(job.context["trigger_timeframe"], "1h")
            self.assertEqual(job.symbol, "TEST")

            from market_intelligence.application.full_scan_pdf import enqueue_full_scan_pdf

            enqueue_full_scan_pdf(
                c,
                universe="BIST_ALL",
                slot=target,
                sections=[],
                hashes=[],
                predecessors=["panel"],
                topic_id=10,
            )
            c.execute("INSERT INTO telegram_outbox VALUES ('panel','pending')")
            pdf_repo = PostgresCommandJobRepository(c, scan_reports_only=True)
            self.assertIsNone(pdf_repo.claim(now=target))
            c.execute("UPDATE telegram_outbox SET status='sent'")
            self.assertEqual(pdf_repo.claim(now=target).command.value, "scan_pdf")
            self.assertNotEqual(
                PostgresCommandJobRepository(c).claim(now=target).command.value, "scan_pdf"
            )
