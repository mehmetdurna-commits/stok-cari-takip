# StokCari

Bu proje, Python Flask tabanlı bir stok, cari ve POS yönetim uygulamasıdır.

## Kurulum

1. Sanal ortam oluşturun ve aktif edin:
   ```bash
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Bağımlılıkları yükleyin:
   ```bash
   pip install -r requirements.txt
   ```
3. Yerel ayar dosyasını oluşturun:
   ```powershell
   Copy-Item .env.example .env
   ```
   `.env` içindeki `PLATFORM_ADMIN_EMAILS` ve `PLATFORM_ADMIN_PASSWORD`
   değerlerini kendi bilgilerinizle değiştirin. Bu dosya uygulama başlarken
   otomatik yüklenir ve Git'e eklenmez.

## Çalıştırma

```bash
python run.py
```

Uygulama `http://localhost:5000` adresinde çalışır.

## Testler

```bash
pytest
```

## Ön Muhasebe (Hesaplar)

- Hesaplar ekranı: `/onmuhasebe/hesaplar`
- Hesap ekstresi: `/onmuhasebe/hesaplar/<id>`
- Varsayılan hesaplar otomatik oluşur: `Nakit Kasa`, `Banka Hesabı`, `POS`
- Para hareketleri `CashTransaction` üzerinden tutulur ve her hareket bir hesaba (`Account`) bağlanır.
- Hesap ekstresinden manuel fiş (giriş/çıkış) ve hesaplar arası transfer eklenebilir.
- Mutabakat (kasa sayımı): `/onmuhasebe/mutabakat` (fark varsa otomatik “Sayım Farkı” fişi oluşur).
- Ön muhasebe raporları: `/onmuhasebe/raporlar` (tarih + hesap filtresi, kırılımlar ve son hareketler).
- POS ödeme ekranında “Hesap” seçimi yapılabilir; “Cari Hesap/Veresiye” seçilirse kasa hareketi oluşturulmaz.
- Cari ödeme/tahsilat modallarında “Hesap” seçimi yapılabilir (boş bırakılırsa otomatik eşleşir).

## Üretim için öneriler

- `SECRET_KEY` ve `DATABASE_URL` çevre değişkenlerini ayarlayın.
- HTTPS kullanıyorsanız `SESSION_COOKIE_SECURE=True` yapın.
- Veritabanı olarak SQLite yerine PostgreSQL ya da MySQL tercih edin.
