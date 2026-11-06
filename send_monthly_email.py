from __future__ import annotations

import mimetypes
import os
import smtplib
import json
from email.message import EmailMessage
from pathlib import Path

from prepare_audit_baseline import select_current_export


ROOT = Path(__file__).resolve().parent


def main() -> None:
    username = os.getenv("SMTP_USERNAME", "").strip(); password = "".join(os.getenv("SMTP_PASSWORD", "").split())
    recipients = [x.strip() for x in os.getenv("REPORT_EMAIL_TO", "").replace(";", ",").split(",") if x.strip()]
    if not username or not password or not recipients:
        print("Aylık e-posta ayarları eksik; gönderim atlandı"); return
    report = ROOT / "v2_output" / "reports" / "monthly_trend.txt"
    report_data = json.loads((ROOT / "v2_output" / "reports" / "monthly_trend.json").read_text(encoding="utf-8"))
    files = list((ROOT / "data").glob("Sifir_arac_????-??-??.xlsx"))
    current_export = select_current_export(files)
    if current_export is None: raise RuntimeError("Aylık mail için güncel Excel bulunamadı")
    period = report_data["period"]
    msg = EmailMessage(); msg["Subject"] = f"Aylık Sıfır Araç Fiyat Trendi | {period[5:7]}.{period[:4]}"
    msg["From"] = username; msg["To"] = ", ".join(recipients); msg.set_content(report.read_text(encoding="utf-8"))
    path = current_export; mime, _ = mimetypes.guess_type(path.name); main_type, sub_type = (mime or "application/octet-stream").split("/", 1)
    msg.add_attachment(path.read_bytes(), maintype=main_type, subtype=sub_type, filename=path.name)
    with smtplib.SMTP_SSL(os.getenv("SMTP_HOST") or "smtp.gmail.com", int(os.getenv("SMTP_PORT") or "465"), timeout=30) as smtp:
        smtp.login(username, password); smtp.send_message(msg)
    print(f"Aylık trend e-postası {len(recipients)} alıcıya gönderildi; ek=1")


if __name__ == "__main__": main()
