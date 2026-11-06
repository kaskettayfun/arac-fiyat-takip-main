import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import send_email


class FakeSMTP:
    sent = None

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def login(self, *args):
        pass

    def send_message(self, message):
        FakeSMTP.sent = message


class EmailFormatTest(unittest.TestCase):
    def test_subject_flags_actionable_changes_without_extra_attachment(self):
        self.assertTrue(send_email.has_actionable_changes(
            "Liste fiyatı değişen: 0; yeni versiyon: 1; kalkan versiyon: 0\nYeni TSB boşluğu: 0"))
        self.assertFalse(send_email.has_actionable_changes(
            "Liste fiyatı değişen: 0; yeni versiyon: 0; kalkan versiyon: 0\nYeni TSB boşluğu: 0\nTSB kodu değişen: 0"))

    def test_success_mail_has_only_current_excel_attachment(self):
        root = Path(__file__).parent / "fixtures" / ".email_test"
        excel = root / "data" / f"Sifir_arac_{date.today():%Y-%m-%d}.xlsx"
        excel.parent.mkdir(parents=True, exist_ok=True)
        excel.touch()
        try:
            env = {
                "SMTP_USERNAME": "sender@example.com", "SMTP_PASSWORD": "password",
                "REPORT_EMAIL_TO": "recipient@example.com", "JOB_STATUS": "success",
            }
            with patch.object(send_email, "ROOT", root), patch.dict(os.environ, env, clear=True), patch.object(send_email.smtplib, "SMTP_SSL", FakeSMTP):
                send_email.main()
            attachments = list(FakeSMTP.sent.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), excel.name)
            self.assertIn("Sıfır Araç Güncel Fiyat Listesi", FakeSMTP.sent["Subject"])
        finally:
            excel.unlink(missing_ok=True)
            excel.parent.rmdir()
            root.rmdir()

    def test_success_mail_selects_current_day_not_prior_export(self):
        root = Path(__file__).parent / "fixtures" / ".email_latest_test"
        first = root / "data" / "Sifir_arac_2026-08-17.xlsx"
        latest = root / "data" / f"Sifir_arac_{date.today():%Y-%m-%d}.xlsx"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.touch(); latest.touch()
        try:
            env = {
                "SMTP_USERNAME": "sender@example.com", "SMTP_PASSWORD": "password",
                "REPORT_EMAIL_TO": "recipient@example.com", "JOB_STATUS": "success",
            }
            with patch.object(send_email, "ROOT", root), patch.dict(os.environ, env, clear=True), patch.object(send_email.smtplib, "SMTP_SSL", FakeSMTP):
                send_email.main()
            attachments = list(FakeSMTP.sent.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_filename(), latest.name)
        finally:
            first.unlink(missing_ok=True); latest.unlink(missing_ok=True)
            first.parent.rmdir(); root.rmdir()


if __name__ == "__main__":
    unittest.main()
