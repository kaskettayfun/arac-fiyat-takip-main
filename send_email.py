from __future__ import annotations

import json
import mimetypes
import os
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from prepare_audit_baseline import select_current_export

ROOT = Path(__file__).resolve().parent


def has_actionable_changes(body: str) -> bool:
    patterns = (
        r"Liste fiyatı değişen:\s*(\d+); yeni versiyon:\s*(\d+); kalkan versiyon:\s*(\d+)",
        r"Yeni TSB boşluğu:\s*(\d+)",
        r"TSB kodu değişen:\s*(\d+)",
        r"Kampanyaya giren:\s*(\d+); kampanyadan çıkan:\s*(\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, body)
        if match and any(int(value) > 0 for value in match.groups()):
            return True
    return False


def main() -> None:
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = "".join(os.getenv("SMTP_PASSWORD", "").split())
    recipients = [x.strip() for x in os.getenv("REPORT_EMAIL_TO", "").replace(";", ",").split(",") if x.strip()]
    if not username or not password or not recipients:
        print("E-posta ayarları eksik; gönderim atlandı."); return
    success = os.getenv("JOB_STATUS", "unknown").lower() == "success"
    body_path = ROOT / "data" / "reports" / "son_rapor.txt"
    body = body_path.read_text(encoding="utf-8") if body_path.exists() else "Rapor üretilemedi."
    files = list((ROOT / "data").glob("Sifir_arac_????-??-??.xlsx"))
    current_export = select_current_export(files)
    if success and current_export is None:
        raise RuntimeError("E-posta için güncel Excel bulunamadı")
    message = EmailMessage()
    today = datetime.now().astimezone().strftime("%d.%m.%Y")
    payload_path = ROOT / "data" / "official" / "direct_latest.json"
    fallbacks = json.loads(payload_path.read_text(encoding="utf-8")).get("fallbacks", {}) if payload_path.exists() else {}
    label = "KISMİ GÜNCELLEME" if success and fallbacks else ("BAŞARILI" if success else "BAŞARISIZ")
    if success and has_actionable_changes(body):
        label += " | DEĞİŞİM VAR"
    message["Subject"] = f"Sıfır Araç Güncel Fiyat Listesi | {today} | {label}"
    message["From"] = username; message["To"] = ", ".join(recipients); message.set_content(body)
    if success:
        path = current_export
        mime, _ = mimetypes.guess_type(path.name)
        main_type, sub_type = (mime or "application/octet-stream").split("/", 1)
        message.add_attachment(path.read_bytes(), maintype=main_type, subtype=sub_type, filename=path.name)
    host = os.getenv("SMTP_HOST", "").strip() or "smtp.gmail.com"
    port = int(os.getenv("SMTP_PORT", "").strip() or "465")
    with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
        smtp.login(username, password); smtp.send_message(message)
    print(f"E-posta {len(recipients)} alıcıya gönderildi; ek={len(list(message.iter_attachments()))}")


if __name__ == "__main__": main()
