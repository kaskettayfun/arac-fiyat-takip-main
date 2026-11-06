import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WorkflowMaintenanceTest(unittest.TestCase):
    def test_v2_shadow_has_no_recurring_schedule(self):
        workflow = (ROOT / ".github" / "workflows" / "operations-v2.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("cron:", workflow)

    def test_workflows_use_node24_compatible_official_actions(self):
        for path in (ROOT / ".github" / "workflows").glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            self.assertNotIn("actions/checkout@v4", workflow, path.name)
            self.assertNotIn("actions/setup-python@v5", workflow, path.name)
            self.assertNotIn("actions/upload-artifact@v4", workflow, path.name)

    def test_collector_does_not_hide_webdriver_identity(self):
        collector = (ROOT / "collect_official_direct.py").read_text(encoding="utf-8")
        self.assertNotIn("navigator, 'webdriver'", collector)

    def test_weekly_job_prepares_early_and_holds_email_until_nine(self):
        workflow = (ROOT / ".github" / "workflows" / "weekly-prices.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "15 1 * * 1,5"', workflow)
        self.assertIn('cron: "15 1 3 * *"', workflow)
        self.assertIn("Planli e-posta saatini bekle", workflow)
        self.assertIn('06:00:00', workflow)
        self.assertIn("github.event_name == 'schedule'", workflow)
        self.assertIn("github.event_name != 'push'", workflow)

    def test_verified_excel_delivery_is_not_blocked_by_snapshot_push_race(self):
        workflow = (ROOT / ".github" / "workflows" / "weekly-prices.yml").read_text(encoding="utf-8")
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("git pull --rebase origin main", workflow)
        self.assertIn("steps.store_history.outcome == 'success'", workflow)
        self.assertIn("steps.export_excel.outcome == 'success'", workflow)
        self.assertIn("steps.audit.outcome == 'success'", workflow)


if __name__ == "__main__":
    unittest.main()
