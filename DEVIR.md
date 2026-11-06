# Geliştirici devir notu

Bu belge robotu devralan geliştirici içindir. Canlı akış `main` dalındaki `weekly-prices.yml`; `feature/operations-v2` dalı ve `operations-v2.yml` ise ayrı bir **gölge/deneme** hattıdır. V2 workflow'u şu anda yalnız `workflow_dispatch` ile başlar; canlı raporun yerine geçtiği varsayılmamalıdır. Geliştirmeleri ayrı dalda yapın, test ve artifact sonuçlarını inceleyip pull request ile birleştirin. `main` ve geçmiş Excel'leri doğrudan deney alanı olarak kullanmayın.

## İlk kurulum ve yön bulma

1. Python 3.12, `requirements.txt` ve Playwright Chromium'u README'deki komutlarla kurun. CI'daki tarayıcı işi `ubuntu-24.04` üzerinde çalışır.
2. `python -m unittest discover -s tests -p "test_*.py"` ile testleri çalıştırın. Yerel testlerin geçmesi, canlı kaynakların bugün okunabildiği anlamına gelmez.
3. Kaynaklar: `collect_official_direct.py` ve `config/official_sources.json`. Kapsam eşikleri aynı toplayıcıdaki `MINIMUM_BRAND_ROWS`, `MINIMUM_MODEL_COUNTS` ve zorunlu model kurallarında bulunur.
4. Kontrol tabanı: `prepare_audit_baseline.py`; geçmiş ve şema: `main.py`, `vehicle_prices/`; güncel Excel: `export_current_excel.py`; ikinci kontrolör: `audit_current_run.py`; rapor/e-posta: `generate_report.py`, `send_email.py`.
5. TSB eşleştirmesi `tsb_only_matcher.py` ile `data/catalog/` altındaki katalog ve onaylı manuel eşleştirmelere dayanır. Sırf isim benzerliğiyle boş kodları doldurmayın.

## Koşu değerlendirme listesi

- GitHub Actions'ta **iş akışının genel sonucunu değil, her adımı** kontrol edin: test, toplama, kontrol tabanı, geçmiş, Excel, ikinci kontrolör, artifact ve `E-posta gonder`.
- Beklenen marka kapsamı `main.EXPECTED_BRANDS` içindeki 30 markadır. Satır sayısı tek başına tamlık kanıtı değildir; model aileleri ve zorunlu modeller de kontrol edilir.
- `data/Sifir_arac_YYYY-MM-DD.xlsx` içindeki `Guncel_Fiyatlar` ve `Kaynak_Durumu` sayfalarını birlikte okuyun. `B PLANI` eski doğrulanmış fiyat, `İKİNCİL KAYNAK` tarihli resmî olmayan fiyat demektir; bunları yeni resmî fiyat diye sunmayın.
- TSB durumunda `KESİN` bile iki düzeydedir: dış katalogda marka+yıl teyidi veya yalnız önceki manuel eşleştirme. `TSB_KATALOGUNDA_YOK` satırına tahminî kod yazılmaz.
- Kod `push` koşusunda e-posta adımının `skipped` olması beklenir. Planlı veya elle koşuda e-posta adımı ayrıca başarılı olmalıdır; artifact başarısı e-posta teslimini kanıtlamaz.
- CI başarısızsa logda **ilk gerçek hata adımını** bulun. Eski tam Excel veya geçmişi başarısız koşunun eksik çıktısıyla değiştirmeyin.

## Bilinen açıklar — 4 Kasım 2026 koşusu #103

[Koşu #103](https://github.com/eneslokmanak001-rgb/arac-fiyat-takip/actions/runs/41825976221) başarılı tamamlandı: 30 marka, 1.017 fiyat satırı, 9 kolon, ikinci kontrolör başarılı; iki alıcıya tek Excel eki gönderildi. Sonuç yine **kısmi güncelleme**: 24 marka doğrudan resmî kaynak, 5 marka son doğrulanmış veriye dönüş, Volvo için 1 Ekim 2026 tarihli ikincil kaynak.

| Marka | Açık durum |
| --- | --- |
| BYD | Kaynak/kapsam 0/3; 30 Ekim doğrulanmış 3 satır korundu. |
| Chery | Resmî sitede “Fiyatlarımız Güncellenmektedir”; 30 Ekim doğrulanmış 4 satır korundu. |
| Fiat | Kapsam 59/60; 30 Ekim doğrulanmış 60 satır korundu. |
| Nissan | Ticari Townstar ailesi eksik; 30 Ekim doğrulanmış 26 satır korundu. |
| Tesla | Kaynak 0/4; 1 Ekim tarihli doğrulanmış 4 satır korundu. |
| Volvo | 48 satır 1 Ekim tarihli `tekerli.com` ikincil kaynağından; bugünün resmî fiyatı olarak yorumlanmamalı. |

TSB: 922/1.017 `KESİN`; bunun 870'i Kasko/SmartIQ marka+yıl teyitli, 52'si yalnız önceki manuel eşleştirme listesinde. **95 satırın TSB kodu yok; 15'i önceki tam Excel'e göre yeni boşluk.** Öncelik, bu açıkları katalog ve araç özellikleriyle tek tek doğrulamak; eşleşmeyeni boş bırakmaktır. Bu rakamlar tarihli koşu durumudur, sonraki koşularda değişebilir.

## Gizli bilgiler ve yayın

Depoda fiyat geçmişi ile SmartIQ/TSB katalog türevleri bulunur; şirket paylaşım iznini doğrulayın. GitHub şifresi veya SMTP uygulama şifresi paylaşmayın. `weekly-prices.yml` ve V2 akışı `FIAT_API_AUTH`; e-posta adımları `SMTP_USERNAME`, `SMTP_PASSWORD`, `REPORT_EMAIL_TO` ve isteğe bağlı `SMTP_HOST`/`SMTP_PORT` GitHub Actions gizlilerini kullanır. Gizli değerleri dosyaya, loga veya pull request'e yazmayın. Kişisel hesaptaki özel depo işbirlikçisi kodu yazabildiği için workflow değişikliklerini özellikle inceleyin.

Dokümantasyon değişiklikleri tek başına canlı e-posta göndermez. Kod değişikliği için önce testleri ve `push` doğrulamasını, sonra gerekliyse açıkça istenen manuel üretim koşusunu kontrol edin. Sürekli, hatasız veri garantisi vermeyin; B planı ve kaynak tarihlerini raporlayın.
