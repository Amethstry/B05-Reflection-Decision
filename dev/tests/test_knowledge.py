"""Exercise evidence filtering, version history, and compatibility with older knowledge."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from src import experience_store as knowledge


def entry(label="materials", status="verified", conditions=("download-failure", "login-works")):
    return {
        "task": "support-tickets", "domain": "campus-support-demo", "topic": "course-materials",
        "conditions": list(conditions), "case_label": label, "problem": "Download fails",
        "lesson": "Use the primary symptom.", "applies_when": "The session already works.",
        "status": status, "expected_label": label if status == "verified" else None,
        "source": "simulated_gateway",
    }


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "knowledge.sqlite3"

    def test_conflicts_use_explicit_conditions_and_evidence(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            knowledge.save_lesson(db, "scope", "a", entry())
            knowledge.save_lesson(db, "scope", "b", entry("account", "unverified"))
            knowledge.save_lesson(db, "scope", "c", entry("schedule", "rejected"))
            knowledge.save_lesson(db, "scope", "d", entry("other", "verified", conditions=("login-works",)))
            features = ["login-works", "download-failure", "pdf"]
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "next")
            self.assertEqual([hit["case_id"] for hit in hits], ["a"])
            self.assertEqual([row["handling"] for row in conflicts], ["prefer_verified", "prefer_dominant"])
            self.assertEqual(conflicts[0]["preferred_label"], "materials")
            knowledge.save_lesson(db, "scope", "b", entry("account", "verified"))
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "d")
            self.assertEqual(hits, [])
            self.assertEqual([row["handling"] for row in conflicts], ["withhold"])

    def test_incomparable_applicable_conditions_withhold_conflicting_labels(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            knowledge.save_lesson(db, "scope", "account", entry("account", conditions=("login-works",)))
            knowledge.save_lesson(db, "scope", "download", entry(conditions=("download-failure", "pdf")))
            features = ["login-works", "download-failure", "pdf"]
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "new")
            self.assertEqual(hits, [])
            self.assertEqual(conflicts[0]["scope"], "applicable")
            self.assertEqual(conflicts[0]["handling"], "withhold")

    def test_exact_ambiguity_is_not_hidden_by_a_broad_fallback(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            knowledge.save_lesson(db, "scope", "a", entry("materials"))
            knowledge.save_lesson(db, "scope", "b", entry("account"))
            knowledge.save_lesson(db, "scope", "broad", entry("materials", conditions=("login-works",)))
            features = ["login-works", "download-failure"]
            hits, conflicts = knowledge.retrieve_lessons(db, "scope", "course-materials", features, "new")
            self.assertEqual(hits, [])
            self.assertEqual([item["handling"] for item in conflicts], ["withhold", "withhold"])

    def test_repeating_same_entry_does_not_create_a_revision(self):
        with closing(knowledge.open_store(self.path)) as db, db:
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry())["revision"], 1)
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry())["action"], "unchanged")
            self.assertEqual(knowledge.save_lesson(db, "scope", "a", entry("other"))["revision"], 2)
            history = db.execute("SELECT revision, case_label FROM knowledge_versions ORDER BY revision")
            self.assertEqual([tuple(row) for row in history], [(1, "materials"), (2, "other")])
            hits, _ = knowledge.retrieve_lessons(
                db, "scope", "course-materials", ["login-works", "download-failure"], "a"
            )
            self.assertEqual(hits, [])

    def test_legacy_rows_are_imported_once_as_unverified(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "CREATE TABLE lessons (scope TEXT, case_id TEXT, revision INTEGER, "
                "topic TEXT, label TEXT, lesson TEXT, updated_at TEXT)"
            )
            db.execute(
                "INSERT INTO lessons VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("old-scope", "previous", 2, "course-materials", "materials", "Old advice", "2026-11-20"),
            )
        for _ in range(2):
            with closing(knowledge.open_store(self.path)) as db:
                hits = knowledge.latest_lessons(db, "old-scope")
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["status"], "unverified")
                self.assertEqual(hits[0]["source"], "legacy")
                self.assertEqual(hits[0]["revision"], 2)
                self.assertEqual(knowledge.latest_lessons(db, "new-scope"), [])
