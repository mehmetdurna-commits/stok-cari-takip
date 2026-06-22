# StokCari

StokCari; küçük ve orta ölçekli işletmeler için geliştirilen, Flask tabanlı bulut uyumlu bir işletme yönetim uygulamasıdır.  
Stok, cari, hızlı satış (POS), ön muhasebe, teklif, iade, personel ve platform yönetimi modüllerini tek yapıda toplar.

## Öne Çıkan Modüller

- `Ürünler / Stok`
  - ürün kartları, kategori ve depo yönetimi
  - kritik stok takibi
  - stok giriş / çıkış işlemleri
  - toplu stok içe aktarma ön izlemesi
  - toplu fiyat güncelleme

- `Cariler`
  - müşteri / tedarikçi kartları
  - tahsilat ve ödeme akışları
  - cari hareketleri ve ekstre
  - yazdırılabilir cari hesap dökümü

- `Hızlı Satış (POS)`
  - barkod ve ürün adına göre hızlı ürün ekleme
  - tek ekran sepet + ödeme akışı
  - nakit / kart / veresiye satış
  - KDV ve iskonto hesapları
  - fiş yazdırma ve tekrar yazdırma altyapısı
  - hızlı ürün ekleme desteği

- `Ön Muhasebe`
  - varsayılan hesaplar: `Nakit Kasa`, `Banka Hesabı`, `POS`
  - para giriş / çıkış kayıtları
  - hesap detayları ve hareket geçmişi
  - hesaplar arası transfer
  - kasa sayımı / mutabakat
  - finansal rapor ekranları

- `Teklif Yönetimi`
  - teklif oluşturma ve düzenleme
  - kalem, iskonto ve KDV ile teklif hazırlama
  - teklif detay / yazdırma

- `İade İşlemleri`
  - ürün / para iadesi kayıtları
  - stok ve finans etkilerinin işlenmesi
  - iade hareket geçmişi

- `Personel Yönetimi`
  - personel kartları ve departman yapısı
  - izin, avans ve prim kayıtları
  - bordro ön izleme
  - toplu maaş bordrosu ve banka listesi
  - personel finans geçmişi

- `Ayarlar`
  - kullanıcı tercihleri
  - tablo sayfalama tercihi
  - kategori / depo yönetimi
  - POS entegrasyon ayarları
  - kullanıcı rehberi ve hakkında alanları

- `Süper Admin / Platform Yönetimi`
  - firma ve kullanıcı yönetimi
  - sistem yönetimi sekmeleri
  - test merkezi
  - destek talepleri
  - yedekleme ve servis sağlığı alanları

## Teknik Yapı

- Backend: `Python Flask`
- Veritabanı: varsayılan olarak `SQLite`
- ORM: `Flask-SQLAlchemy`
- Şablonlar: `Jinja2`
- Arayüz: `Tailwind tabanlı özel şablon yapısı`

## Yerel Kurulum

### 1) Sanal ortam oluştur

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2) Bağımlılıkları yükle

```powershell
pip install -r requirements.txt
```

### 3) Ortam dosyasını oluştur

```powershell
Copy-Item .env.example .env
```

`.env` içindeki temel alanları kendi ortamına göre düzenle:

- `SECRET_KEY`
- `DATABASE_URL`
- `PLATFORM_ADMIN_EMAILS`

## Uygulamayı Çalıştırma

```powershell
python run.py
```

Varsayılan adres:

```text
http://localhost:5000
```

## Testler

Tüm ana test dosyasını çalıştırmak için:

```powershell
pytest tests/test_app.py
```

Projede uygulamanın ana akışlarını doğrulayan testler bulunur:

- POS satış akışı
- cari hareketleri
- ön muhasebe
- personel / bordro
- iade
- yazdırma şablonları
- yetki ve platform akışları

## Git Kullanımı

Bu projede Git geçmişi klasik `.git` yerine `.repo-git2` yapısı ile kullanılmaktadır.

Detaylar için:

- `GIT_KULLANIMI.md`
- `GIT_GERI_ALMA_REHBERI.md`

## Üretim Notları

- üretimde `SQLite` yerine `PostgreSQL` veya `MySQL` tercih edilmesi önerilir
- `SECRET_KEY` sabit ve güvenli olmalıdır
- HTTPS arkasında çalıştırılmalıdır
- düzenli yedekleme ve log takibi yapılmalıdır
- canlı ortamda demo veri araçları kapalı tutulmalıdır

## Mevcut Ürün Yaklaşımı

StokCari şu alanlara odaklanır:

- hırdavat
- market / perakende
- servis ve teknik işletmeler
- küçük ve orta ölçekli ticari ekipler

Amaç; karmaşık ERP dili yerine, günlük operasyonu hızlı ve anlaşılır hale getiren kullanıcı odaklı bir yönetim paneli sunmaktır.
