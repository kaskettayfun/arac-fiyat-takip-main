import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_report


class GenerateReportTest(unittest.TestCase):
    def test_reports_partial_update_when_fallback_is_used(self):
        root = Path(__file__).parent / "fixtures" / ".partial_report_test"
        official = root / "data" / "official"
        official.mkdir(parents=True, exist_ok=True)
        try:
            records = ([{"Marka": f"Marka-{index}"} for index in range(27)]
                       + [{"Marka": "Tesla", "Kaynak_URL": "https://www.webtekno.com/tesla", "Liste_Tarihi": "2026-09-01"}]
                       + [{"Marka": "Dacia"}] * 12 + [{"Marka": "Renault"}] * 24)
            (official / "direct_latest.json").write_text(json.dumps({
                "records": records,
                "errors": {},
                "fallbacks": {
                    "Dacia": {"source_date": "2026-08-28", "rows": 12, "reason": "fiyat satırı bulunamadı"},
                    "Renault": {"source_date": "2026-08-28", "rows": 24,
                                "reason": "RESMÎ SİTEDE FİYATLAR GÜNCELLENİYOR: Fiyat listemiz güncellenmektedir"},
                },
            }), encoding="utf-8")
            env = {"JOB_STATUS": "success", "TEST_OUTCOME": "success", "COLLECT_OUTCOME": "success"}
            with patch.object(generate_report, "ROOT", root), patch.dict(os.environ, env, clear=True):
                generate_report.main()
            report = (root / "data" / "reports" / "son_rapor.txt").read_text(encoding="utf-8")
            self.assertIn("Sonuç: KISMİ GÜNCELLEME", report)
            self.assertIn("Doğrudan resmî kaynaktan doğrulanan marka: 27/30", report)
            self.assertIn("Tarihli ikincil kaynaktan alınan marka: 1/30", report)
            self.assertIn("Tesla: 1 satır; kaynak tarihi 2026-09-01", report)
            self.assertIn("Son doğrulanmış veriden korunan satır: 36", report)
            self.assertIn("Dacia: KAYNAK/KAPSAM SORUNU", report)
            self.assertIn("Teknik neden: fiyat satırı bulunamadı", report)
            self.assertIn("Renault: RESMÎ SİTEDE FİYATLAR GÜNCELLENİYOR", report)
            self.assertIn("Site mesajı: Fiyat listemiz güncellenmektedir", report)
        finally:
            for path in sorted(root.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            root.rmdir()

    def test_test_failure_does_not_report_stale_prices_as_current(self):
        root = Path(__file__).parent / "fixtures" / ".report_test"
        official = root / "data" / "official"
        official.mkdir(parents=True, exist_ok=True)
        try:
            (official / "direct_latest.json").write_text(json.dumps({
                "records": [{"Marka": "BMW"}], "errors": {}
            }), encoding="utf-8")
            env = {
                "JOB_STATUS": "failure",
                "TEST_OUTCOME": "failure",
                "COLLECT_OUTCOME": "skipped",
            }
            with patch.object(generate_report, "ROOT", root), patch.dict(os.environ, env, clear=True):
                generate_report.main()
            report = (root / "data" / "reports" / "son_rapor.txt").read_text(encoding="utf-8")
            self.assertIn("Durdurulan aşama: SİSTEM TESTLERİ", report)
            self.assertIn("fiyat kaynakları çalıştırılmadı", report)
            self.assertIn("Önceki başarılı Excel ve fiyat geçmişi korunmuştur", report)
            self.assertIn("Raporda bulunan marka: 0/30", report)
        finally:
            for path in sorted(root.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            root.rmdir()

    def test_audit_failure_reports_created_excel_without_claiming_it_was_missing(self):
        root = Path(__file__).parent / "fixtures" / ".audit_failure_report_test"
        official = root / "data" / "official"
        official.mkdir(parents=True, exist_ok=True)
        try:
            (official / "direct_latest.json").write_text(json.dumps({
                "records": [{"Marka": f"Marka-{index}"} for index in range(30)],
                "errors": {},
            }), encoding="utf-8")
            env = {
                "JOB_STATUS": "failure", "TEST_OUTCOME": "success",
                "COLLECT_OUTCOME": "success", "EXPORT_OUTCOME": "success",
                "AUDIT_OUTCOME": "failure",
            }
            with patch.object(generate_report, "ROOT", root), patch.dict(os.environ, env, clear=True):
                generate_report.main()
            report = (root / "data" / "reports" / "son_rapor.txt").read_text(encoding="utf-8")
            self.assertIn("Sonuç: BAŞARISIZ - İKİNCİ KONTROL GEÇİLMEDİ", report)
            self.assertIn("Durdurulan aşama: İKİNCİ KONTROL", report)
            self.assertIn("Excel oluşturuldu; kontrolü geçmediği için e-postaya eklenmedi", report)
            self.assertNotIn("EXCEL ÜRETİLMEDİ", report)
            self.assertIn("Bağımsız doğrulama başarısız", report)
            self.assertNotIn("Başarısızlık: yok", report)
        finally:
            for path in sorted(root.rglob("*"), reverse=True):
                path.unlink() if path.is_file() else path.rmdir()
            root.rmdir()


if __name__ == "__main__":
    unittest.main()
