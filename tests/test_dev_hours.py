from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from services.dev_hours import (
    CommitRecord,
    GitHubApiClient,
    build_work_sessions,
    config_signature,
    deduplicate_commits,
    get_development_investment,
    is_cache_valid,
)


def _commit(sha: str, timestamp: datetime, message: str = "feat") -> CommitRecord:
    return CommitRecord(sha=sha, timestamp=timestamp, message=message, repo="owner/repo")


class DevHoursTest(unittest.TestCase):
    def test_sessions_split_by_gap_above_90_minutes(self) -> None:
        start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        commits = [
            _commit("a", start),
            _commit("b", start + timedelta(minutes=90)),
            _commit("c", start + timedelta(minutes=181)),
        ]

        sessions = build_work_sessions(commits, limiar_sessao_min=90, overhead_sessao_min=20)

        self.assertEqual(2, len(sessions))
        self.assertAlmostEqual(1.5, sessions[0].base_hours)
        self.assertEqual(2, sessions[0].commits)
        self.assertEqual(1, sessions[1].commits)

    def test_overhead_is_applied_per_session(self) -> None:
        start = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        commits = [
            _commit("a", start),
            _commit("b", start + timedelta(hours=3)),
        ]

        sessions = build_work_sessions(commits, limiar_sessao_min=90, overhead_sessao_min=30)

        self.assertEqual(2, len(sessions))
        self.assertAlmostEqual(1.0, sum(session.overhead_hours for session in sessions))

    def test_deduplicates_by_sha_and_timestamp_message(self) -> None:
        timestamp = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
        commits = [
            _commit("same", timestamp, "Fix bug"),
            _commit("same", timestamp + timedelta(minutes=5), "Different message"),
            _commit("mirror-1", timestamp + timedelta(hours=1), " Implement feature "),
            _commit("mirror-2", timestamp + timedelta(hours=1), "implement   feature"),
        ]

        deduped = deduplicate_commits(commits)

        self.assertEqual(["same", "mirror-1"], [commit.sha for commit in deduped])

    def test_cache_ttl_respects_signature_and_24_hours(self) -> None:
        now = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
        signature = config_signature({"repositorios": ["owner/repo"]})
        valid_cache = {"generated_at": (now - timedelta(hours=23, minutes=59)).isoformat(), "config_signature": signature}
        expired_cache = {"generated_at": (now - timedelta(hours=24, minutes=1)).isoformat(), "config_signature": signature}
        wrong_signature = {"generated_at": now.isoformat(), "config_signature": "other"}

        self.assertTrue(is_cache_valid(valid_cache, signature=signature, now=now))
        self.assertFalse(is_cache_valid(expired_cache, signature=signature, now=now))
        self.assertFalse(is_cache_valid(wrong_signature, signature=signature, now=now))

    def test_401_with_token_retries_without_authorization_for_public_call(self) -> None:
        calls: list[dict[str, str]] = []

        def transport(_url: str, headers: dict[str, str]):
            calls.append(dict(headers))
            if len(calls) == 1:
                return 401, {"message": "Bad credentials"}
            return 200, []

        client = GitHubApiClient(token="secret-token", transport=transport)

        payload = client.get_json("/repos/owner/repo/commits", params={"per_page": 100, "page": 1}, repo="owner/repo")

        self.assertEqual([], payload)
        self.assertIn("Authorization", calls[0])
        self.assertNotIn("Authorization", calls[1])
        self.assertTrue(client.token_invalid)
        self.assertTrue(client.used_unauthenticated_fallback)

    def test_uses_stale_cache_when_refresh_fails(self) -> None:
        now = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
        config = {"repositorios": ["owner/repo"], "limiar_sessao_min": 90, "overhead_sessao_min": 20}
        stale_payload = {"total_horas": 12.0, "warnings": []}
        cache = {
            "generated_at": (now - timedelta(days=2)).isoformat(),
            "config_signature": config_signature(config),
            "payload": stale_payload,
        }

        def transport(_url: str, _headers: dict[str, str]):
            return 404, {"message": "Not Found"}

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "cache.json"
            cache_path.write_text(__import__("json").dumps(cache), encoding="utf-8")
            payload, source, warnings = get_development_investment(
                config,
                cache_path=cache_path,
                refresh=True,
                now=now,
                client=GitHubApiClient(transport=transport),
            )

        self.assertEqual("cache_stale", source)
        self.assertEqual(12.0, payload["total_horas"])
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
