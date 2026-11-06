from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook
from source_quality import secondary_source_details, restored_scope_brands
from tsb_only_matcher import NO_TSB_STATUS
from vehicle_prices.weekly_changes import compare as compare_weekly

ROOT = Path(__file__).resolve().parent
SOURCE_UPDATING_PREFIX = "RESMÎ SİTEDE FİYATLAR GÜNCELLENİYOR:"


def main() -> None:
    test_outcome = os.getenv("TEST_OUTCOME", "unknown").lower()
    collect_outcome = os.getenv("COLLECT_OUTCOME", "unknown").lower()
    export_outcome = os.getenv("EXPORT_OUTCOME", "unknown").lower()
    audit_outcome = os.getenv("AUDIT_OUTCOME", "unknown").lower()
    payload_path = ROOT / "data" / "official" / "direct_latest.json"
    stopped_stage = ""
    if test_outcome == "failure":
        rows, errors = [], {"Sistem testi": "Test aşaması başarısız; fiyat kaynakları çalıştırılmadı"}
        stopped_stage = "SİSTEM TESTLERİ"
    elif collect_outcome not in ("success", "unknown"):
        rows, errors = [], {"Veri toplama": "Resmi kaynak taraması tamamlanamadı"}
        stopped_stage = "VERİ TOPLAMA"
    else:
        payload = json.loads(payload_path.read_text(encoding="utf-8")) if payload_path.exists() else {"records": [], "errors": {"Sistem": "Çıktı üretilemedi"}}
        rows, errors = payload.get("records", []), payload.get("errors", {})
    errors = dict(errors)
    if audit_outcome == "failure":
        errors.setdefault("İkinci kontrol", "Bağımsız doğrulama başarısız; Excel teslim edilmedi")
    fallbacks = payload.get("fallbacks", {}) if 'payload' in locals() else {}
    secondary_sources = {brand: detail for brand, detail in secondary_source_details(rows).items()
                         if brand not in fallbacks}
    counts = Counter(row.get("Marka", "") for row in rows)
    success = os.getenv("JOB_STATUS", "unknown").lower() == "success" and len(counts) == 30 and not errors
    now = datetime.now().astimezone()
    if success:
        result = "KISMİ GÜNCELLEME" if fallbacks or secondary_sources else "BAŞARILI"
    elif audit_outcome == "failure" and export_outcome == "success":
        result = "BAŞARISIZ - İKİNCİ KONTROL GEÇİLMEDİ; EXCEL GÖNDERİLMEDİ"
        stopped_stage = "İKİNCİ KONTROL"
    elif export_outcome == "failure":
        result = "BAŞARISIZ - GÜNCEL EXCEL ÜRETİLEMEDİ"
        stopped_stage = "EXCEL ÜRETİMİ"
    else:
        result = "BAŞARISIZ - GÜNCEL EXCEL DOĞRULANAMADI"
    fallback_rows = sum(int(detail.get("rows") or 0) for detail in fallbacks.values())
    lines = [
        "SIFIR ARAÇ FİYAT RAPORU", f"Tarih: {now:%d.%m.%Y %H:%M}", f"Sonuç: {result}",
        f"Raporda bulunan marka: {len(counts)}/30",
        f"Doğrudan resmî kaynaktan doğrulanan marka: {len(counts) - len(fallbacks) - len(secondary_sources)}/30",
        f"Son doğrulanmış veriye dönülen marka: {len(fallbacks)}/30",
        f"Tarihli ikincil kaynaktan alınan marka: {len(secondary_sources)}/30",
        f"Rapordaki toplam fiyat satırı: {len(rows)}",
        f"Son doğrulanmış veriden korunan satır: {fallback_rows}",
    ]
    if fallbacks:
        lines.extend(["", "B planı kullanılan markalar:"])
        for brand, detail in sorted(fallbacks.items()):
            reason = str(detail.get("reason") or "")
            kept = (f"{detail.get('source_date')} tarihli son doğrulanmış veri korundu "
                    f"({detail.get('rows')} satır).")
            if reason.startswith(SOURCE_UPDATING_PREFIX):
                notice = reason.removeprefix(SOURCE_UPDATING_PREFIX).strip()
                lines.append(f"- {brand}: RESMÎ SİTEDE FİYATLAR GÜNCELLENİYOR. {kept} Site mesajı: {notice}")
            else:
                lines.append(f"- {brand}: KAYNAK/KAPSAM SORUNU. {kept} Teknik neden: {reason}")
    if secondary_sources:
        lines.extend(["", "Resmî olmayan tarihli kaynaklar:"])
        for brand, detail in sorted(secondary_sources.items()):
            lines.append(f"- {brand}: {detail['rows']} satır; kaynak tarihi {detail['source_date']}; {detail['url']}")
    if stopped_stage:
        lines.extend([
            f"Durdurulan aşama: {stopped_stage}",
            "Not: Önceki başarılı Excel ve fiyat geçmişi korunmuştur."
            if export_outcome != "success" else
            "Not: Excel oluşturuldu; kontrolü geçmediği için e-postaya eklenmedi.",
        ])
    audit_path = ROOT / "data" / "reports" / "ikinci_kontrol.json"
    if audit_path.exists():
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        if fallbacks or secondary_sources:
            lines.append("")
        lines.append(f"İkinci kontrolör: {audit.get('status', 'BILINMIYOR')}")
        if "tsb_external_verified" in audit:
            lines.append(f"TSB Kasko/SmartIQ marka+yıl teyidi: {audit['tsb_external_verified']}")
            lines.append(f"TSB yalnız önceki manuel eşleştirme listesinde: {audit.get('tsb_manual_only', 0)}")
        if audit.get("errors"):
            lines.extend(f"- Kontrol hatası: {message}" for message in audit["errors"])
    exports = sorted((ROOT / "data").glob("Sifir_arac_????-??-??.xlsx"))
    if success and len(exports) == 1:
        workbook = load_workbook(exports[0], read_only=True, data_only=True)
        sheet = workbook["Guncel_Fiyatlar"]
        headers = {cell.value: index for index, cell in enumerate(sheet[1], 1)}
        status_column = headers.get("Eşleşme Durumu")
        if status_column:
            statuses = Counter(row[0] for row in sheet.iter_rows(
                min_row=2, min_col=status_column, max_col=status_column, values_only=True
            ))
            lines.extend([
                f"TSB kesin: {statuses.get('KESİN', 0)}",
                f"TSB kataloğunda henüz yok: {statuses.get(NO_TSB_STATUS, 0)}",
            ])
        baseline_path = ROOT / "data" / "reports" / "onceki_basarili_excel.json"
        if baseline_path.exists():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            if baseline.get("rows"):
                current_rows = list(sheet.iter_rows(min_row=2, max_col=9, values_only=True))
                restored_brands = restored_scope_brands(baseline["rows"], current_rows, rows)
                changes = compare_weekly(baseline["rows"], current_rows, set(fallbacks) | restored_brands)
                lines.extend([
                    "", f"Önceki başarılı Excel'e göre değişiklikler ({baseline.get('source') or 'tarih bilinmiyor'}):",
                    f"Liste fiyatı değişen: {len(changes['price_changes'])}; yeni versiyon: {len(changes['new_versions'])}; kalkan versiyon: {len(changes['removed_versions'])}",
                    f"Kampanyaya giren: {changes['campaigns_entered']}; kampanyadan çıkan: {changes['campaigns_exited']}",
                    f"Yeni TSB boşluğu: {len(changes['newly_missing_tsb'])}; toplam TSB boşluğu: {changes['total_missing_tsb']}",
                    f"TSB kodu değişen: {len(changes['tsb_changes'])}",
                ])
                if fallbacks:
                    lines.append("Eski veri kullanılan markalarda fiyat değişimi hesaplanmadı: " + ", ".join(sorted(fallbacks)))
                if restored_brands:
                    lines.append("Kapsam toparlanması (yeni/kalkan araç ve fiyat trendi sayılmadı): " + ", ".join(sorted(restored_brands)))
                if changes["ambiguous_keys"]:
                    lines.append(f"Kimliği çakışan {changes['ambiguous_keys']} kayıt karşılaştırmadan çıkarıldı; isimler incelenmeli.")
                for _, name, old_price, new_price, delta in changes["price_changes"][:10]:
                    lines.append(f"- FİYAT: {name}: {old_price:,} → {new_price:,} TL ({delta:+,} TL)")
                for heading, names in (("YENİ", changes["new_versions"]), ("KALKAN", changes["removed_versions"]),
                                       ("TSB KODU GEREKLİ", changes["newly_missing_tsb"])):
                    for name in names[:10]:
                        lines.append(f"- {heading}: {name}")
                    if len(names) > 10:
                        lines.append(f"- {heading}: ve {len(names) - 10} kayıt daha; ayrıntı güncel Excel'de")
                for name, old_code, new_code in changes["tsb_changes"][:10]:
                    lines.append(f"- TSB DEĞİŞTİ: {name}: {old_code or 'boş'} → {new_code or 'boş'}")
                if len(changes["tsb_changes"]) > 10:
                    lines.append(f"- TSB DEĞİŞTİ: ve {len(changes['tsb_changes']) - 10} kayıt daha; ayrıntı güncel Excel'de")
        workbook.close()
    lines.extend(["", "Marka bazında satır sayısı:"])
    lines.extend(f"- {brand}: {count}" for brand, count in sorted(counts.items()))
    lines.append("")
    if errors:
        lines.append("Başarısızlıklar:")
        lines.extend(f"- {brand}: {message}" for brand, message in sorted(errors.items()))
    else:
        lines.append("Başarısızlık: yok")
    run_url = os.getenv("RUN_URL", "")
    if run_url: lines.extend(["", f"GitHub çalışması: {run_url}"])
    report = "\n".join(lines) + "\n"
    target = ROOT / "data" / "reports" / "son_rapor.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8")
    print(report)


if __name__ == "__main__": main()
