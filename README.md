# Sıfır Araç Fiyat Robotu

Türkiye'deki 30 markanın sıfır araç liste ve kampanyalı fiyatlarını toplar. Marka başına ayrı okuyucuların çıktısı ortak kayda dönüştürülür; kapsam ve fiyat kontrollerinden sonra güncel Excel, fiyat geçmişi ve kısa e-posta raporu üretilir. **30/30 marka, her fiyatın o gün resmî kaynaktan doğrulandığı anlamına gelmez:** kaynak kullanımı Excel'deki `Kaynak_Durumu` sayfasında ve e-posta metninde ayrıca belirtilir.

Yeni geliştirici için [DEVIR.md](DEVIR.md) dosyasını okuyun.

## Canlı akış

[`.github/workflows/weekly-prices.yml`](.github/workflows/weekly-prices.yml) `main` dalında çalışır. Pazartesi ve cuma ile ayın 3'ünde planlanır; elle de başlatılabilir. Planlı koşunun başlangıcı 04:15 Türkiye saatine ayarlıdır ve e-posta adımı 09:00'dan önce çalışmaz. GitHub Actions gecikmeleri nedeniyle 09:00 teslimi mutlak garanti değildir. Kod `push` koşuları doğrulama içindir; e-posta göndermez.

Sıra: birim testleri → 30 kaynak taraması → önceki kapsamı doğrulanmış Excel'i karşılaştırma tabanı seçme → geçmişe yazma → güncel Excel → bağımsız ikinci kontrolör → rapor → artifact → planlı/elle koşulda e-posta. Denetim başarısızsa güncel Excel e-postaya eklenmez.

Güncel dosya `data/Sifir_arac_YYYY-MM-DD.xlsx` adını taşır. `Guncel_Fiyatlar` sayfasındaki dokuz kolon: Tarih, Marka, Model, Versiyon, Model Yılı, Liste Fiyatı, Kampanyalı Fiyat, TSB Kodu, Eşleşme Durumu. `Kaynak_Durumu` sayfası marka bazında doğrudan kaynak, tarihli ikincil kaynak ve B planını ayırır. Geçmiş `data/Sifir_Arac_Fiyat_Gecmisi.xlsx`, tarihli kopyalar `data/arsiv/` altındadır. Güncel Excel GitHub artifact'ında 90 gün tutulur; başarılı planlı/elle koşunun e-postasında tek Excel eki bulunur.

## Yerel kurulum ve güvenli test

Python 3.12 kullanın:

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m unittest discover -s tests -p "test_*.py"
```

Yerel testler e-posta göndermez. Tam kaynak taraması ve e-posta davranışını doğrulamak için GitHub Actions koşusunun adımlarını ve raporunu inceleyin. Canlı workflow tarayıcı için `ubuntu-24.04` kullanır. Çalıştırmadan önce `DEVIR.md` içindeki gizli bilgi ve canlı veri uyarılarını okuyun.

## Güvenlik ilkesi

Eksik marka/model kapsamı veya sıra dışı fiyat, sessizce güncel veri sayılmaz. Uygun son doğrulanmış tam Excel'den B planı uygulanır ve tarih/neden raporlanır; tarihli ikincil kaynak da açıkça işaretlenir. İkinci kontrolör JSON ile Excel'i, 30 marka kapsamını, mükerrerleri, pozitif fiyatları ve TSB katalog ilişkisinin tutarlılığını denetler. Bu kontroller **kaynakların eksiksiz ve her fiyatın doğru olduğunu garanti etmez**; B planı ve eşleşmeyen TSB'ler açık iş olarak kalır.
