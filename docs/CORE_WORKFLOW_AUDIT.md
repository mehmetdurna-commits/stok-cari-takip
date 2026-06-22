# Çekirdek İş Akışı Denetimi

Tarih: 2026-06-03

Kapsam: Süper admin hariç normal uygulama akışları.

## Test Edilen Kritik Akışlar

- Ürün/stok: ürün listeleme, ürün ekleme demo verisi, stok girişi, stok çıkışı, depo ürün aktarımı.
- POS satış: nakit satış, veresiye satış, yetersiz stok reddi, negatif iskonto reddi, yabancı tenant ürünü/cari reddi.
- Satış iptali: stok geri alma, cari alacak düzeltme, nakit/banka/POS ters kayıtları.
- Cari hesaplar: cari oluşturma, detay/ekstre, ödeme/tahsilat hareketi, banka hesabına tahsilat.
- Teklif: teklif oluşturma, kalem/toplam/KDV hesabı, teklif sayfalarının renderı.
- İade: ürün iadesi, stok geri alma, cari alacak düzeltme, nakit hareketi oluşturmama senaryosu.
- Ön muhasebe: varsayılan kasa/banka/POS hesapları, manuel işlem, hesaplar arası transfer, mutabakat fark kaydı.
- Personel: listeleme, arama, sayfalama, departman izolasyonu.
- Ayarlar/yedekleme: tercih kaydı, bildirim ayarları, yedek oluşturma, güvenlik denetimi.

## Bulunan ve Düzeltilen Mantık Hatası

- Veresiye POS satışı iptal edildiğinde uygulama gereksiz `CashTransaction` çıkış kaydı oluşturabiliyordu.
- Satış iptalinde ters nakit kaydı, orijinal satışın seçtiği kasa/banka/POS hesabını korumuyordu.
- Düzeltme: Satış iptalinde yalnızca gerçekten var olan satış nakit hareketleri terslenir; ters kayıt orijinal `account_id` ile yazılır.

## Doğrulama Sonucu

- Çekirdek iş akışı testleri: `17 passed`
- Tam test paketi: `109 passed, 14 warnings`

## Dikkat Edilmesi Gereken Ürün Noktaları

- Cari ekranında `ödeme` ve `tahsilat` terimleri kullanıcı için karışabilir. Muhasebe davranışı çalışıyor; fakat etiketlerin “müşteriden tahsilat” / “tedarikçiye ödeme” gibi daha netleştirilmesi önerilir.
- Demo veri araçları canlıya çıkmadan önce feature flag ile kapatılmalı veya yalnızca geliştirme/test modunda görünmelidir.
- POS fiş/yazdırma akışı otomatik testte sınırlı doğrulanıyor; gerçek termal yazıcıyla manuel kabul testi gerekir.
