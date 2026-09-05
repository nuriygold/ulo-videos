import unittest
from pathlib import Path


class RenderJobSchemaMigrationTests(unittest.TestCase):
    def test_worker_can_record_the_worker_id_on_existing_render_jobs(self):
        migrations = sorted((Path(__file__).parents[1] / "supabase" / "migrations").glob("*.sql"))
        migration_sql = "\n".join(path.read_text(encoding="utf-8") for path in migrations)

        self.assertIn(
            "alter table public.render_jobs add column if not exists worker_id text;",
            migration_sql.lower(),
        )
        self.assertIn(
            "alter table public.render_jobs add column if not exists lease_expires_at timestamptz;",
            migration_sql.lower(),
        )


if __name__ == "__main__":
    unittest.main()
