# StokCari World-Class Roadmap

Bu yol haritasi uygulamayi kullanici odakli, guvenilir, olceklenebilir ve urunlesmeye hazir bir seviyeye tasimak icin hazirlandi.

## 1. Temel Urun Guveni

- Ortam bazli guvenli konfig: development, test, production ayrimi.
- Uygulama saglik kontrolu: veritabani ve servis durumu tek endpointten izlenebilir.
- Standart guvenlik basliklari: temel tarayici korumalarinin her cevapta gelmesi.
- Kullanici dostu hata deneyimi: 404 ve 500 sayfalari teknik olmayan dille yonlendirir.
- Test kosullari: testler sadece `tests/` altindan toplanir ve gecici cache klasorlerinden etkilenmez.

## 2. Kullanici Deneyimi

- Tum ekranlarda tutar, tarih, stok ve durum formatlari tek standarda baglanacak.
- Kritik akislar icin bos durum, yukleniyor durumu, hata durumu ve basari geri bildirimi tamamlanacak.
- POS, stok girisi/cikisi ve cari tahsilat akislari daha az tikla tamamlanacak sekilde sadeleştirilecek.
- Bildirimler gercek veriye baglanacak; sahte/statik bildirimler kaldirilacak.
- Mobil deneyim tablo ve aksiyon yogun ekranlarda yeniden duzenlenecek.

## 3. Teknik Mimari

- Tek dosyalik `app.py`, kademeli olarak `models`, `routes`, `services`, `repositories` ve `forms` katmanlarina ayrilacak.
- Veritabani sema degisimleri icin migration sistemi eklenecek.
- Is kurallari route'lardan ayrilarak test edilebilir servis fonksiyonlarina tasinacak.
- Yetki ve sahiplik kontrolleri ortak yardimci fonksiyonlarla standartlastirilacak.
- Audit, stok hareketi ve cari hareket kayitlari tutarli domain event mantigina baglanacak.

## 4. Guvenlik ve Uyumluluk

- CSRF korumasi tum form ve state-changing endpointlere eklenecek.
- Parola kurallari, giris deneme siniri ve oturum suresi politikasi netlestirilecek.
- Yedek geri yukleme icin dosya tipi, boyut ve sahiplik kontrolleri sertlestirilecek.
- Uretim ortaminda gizli anahtar, HTTPS cookie ve debug kapatma zorunlu hale getirilecek.

## 5. Performans ve Olcek

- Dashboard ve rapor sorgulari toplu SQL agregasyonlarina tasinacak.
- Liste ekranlarinda server-side sayfalama, filtreleme ve siralama standart olacak.
- SQLite gelistirme icin kalacak; uretim icin PostgreSQL hedeflenecek.
- Sik kullanilan raporlar icin cache stratejisi eklenecek.

## 6. Kalite Kapilari

- Kritik is akislari icin unit ve integration test kapsami artirilacak.
- Hata senaryolari, yetki ihlalleri ve veri izolasyonu testleri genisletilecek.
- Otomatik smoke test: giris, urun ekleme, POS satis, cari tahsilat, yedek alma.
- Her buyuk degisiklikten sonra test, lint ve guvenlik kontrolu standart komut haline gelecek.
