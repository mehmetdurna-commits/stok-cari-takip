# Esstok E-Fatura / E-Arşiv Entegrasyon Çalışması

Bu doküman, Esstok içinde ileride e-fatura/e-arşiv entegrasyonu yapılırken mevcut satış, cari, stok ve kasa akışını bozmadan ilerlemek için hazırlanmıştır.

## Amaç

Esstok üzerinden yapılan satışların, kullanıcı isterse bir entegratör aracılığıyla resmi e-fatura/e-arşiv sürecine aktarılabilmesi.

İlk hedef doğrudan canlı fatura kesmek değil; güvenli, izlenebilir ve kullanıcıyı yormayan bir altyapı kurmaktır.

## Kullanıcı Akışı

1. Kullanıcı POS veya satış ekranından satışı tamamlar.
2. Esstok mevcut şekilde stok, cari ve kasa hareketlerini oluşturur.
3. Satış kaydı üzerinde fatura durumu görünür:
   - Fatura bekliyor
   - Gönderildi
   - Başarılı
   - Hata aldı
   - İptal / iade sürecinde
4. Kullanıcı isterse “Fatura Oluştur” veya “E-Arşiv Gönder” butonuna basar.
5. Entegratör cevabı Esstok içinde saklanır.
6. Başarılı işlemde kullanıcı PDF/HTML/XML bağlantısına ulaşır.

## İlk Aşamada Olması Gerekenler

### Satış Kaydı Üzerinde Alanlar

Satış modeline ileride şu bilgilerin eklenmesi gerekir:

- `invoice_status`: Fatura durumu
- `invoice_provider`: Kullanılan entegratör
- `invoice_type`: E-fatura / e-arşiv
- `invoice_external_id`: Entegratör tarafındaki kayıt numarası
- `invoice_uuid`: Resmi fatura UUID değeri
- `invoice_pdf_url`: PDF bağlantısı
- `invoice_error`: Son hata mesajı
- `invoice_sent_at`: Gönderim zamanı

### Entegrasyon Ayarları

Ayarlar içinde ayrı bir “E-Fatura Entegrasyonu” alanı olmalı:

- Entegratör seçimi
- Test / canlı modu
- API kullanıcı adı
- API anahtarı / parola
- Firma vergi bilgileri kontrolü
- Test gönderimi
- Son bağlantı durumu

### Firma Bilgileri Kontrolü

Fatura kesmeden önce firma tarafında şu bilgiler zorunlu kontrol edilmeli:

- Firma unvanı
- Vergi dairesi
- Vergi numarası veya T.C. kimlik numarası
- Adres
- İl / ilçe
- Telefon veya e-posta

Eksik bilgi varsa kullanıcıya “Fatura kesmeden önce firma bilgilerini tamamlayın” mesajı gösterilmeli.

## Entegratör Mantığı

Esstok doğrudan tek bir firmaya gömülmemeli. Adaptör mantığı kullanılmalı:

- `manual`: Şimdilik sadece durum takibi
- `fatura_entegrator`: Fatura Entegratör benzeri API
- `gib_portal`: İleride GİB portal mantığı
- `parasut`: İleride Paraşüt bağlantısı
- `qnb`: İleride QNB bağlantısı
- `mysoft`: İleride Mysoft bağlantısı

Bu yapı sayesinde kullanıcı ileride ayarlardan sağlayıcı seçebilir.

## Esstok İçin En Doğru İlk Sürüm

Canlıya zarar vermemek için ilk sürüm şu şekilde olmalı:

1. Fatura durum alanları eklensin.
2. Günlük satışlar ve satış detayında fatura durumu gösterilsin.
3. “Fatura Oluştur” butonu şimdilik test modunda çalışsın.
4. API bilgileri girilmeden canlı fatura gönderilmesin.
5. Hata alınırsa satış, stok, cari ve kasa kayıtları bozulmasın.

## Kullanıcı Dostu Mesajlar

Teknik hata yerine şu mesajlar kullanılmalı:

- “Fatura gönderilemedi. Satış kaydınız korunuyor.”
- “Firma vergi bilgileri eksik olduğu için fatura oluşturulamadı.”
- “Entegratör bağlantısı kurulamadı. API ayarlarınızı kontrol edin.”
- “Fatura başarıyla oluşturuldu.”

## Dikkat Edilecek Riskler

- Satış başarılı olup fatura başarısız olabilir. Bu durumda satış geri alınmamalı.
- Fatura başarısız olursa tekrar deneme yapılabilmeli.
- Aynı satış için yanlışlıkla iki kez fatura kesilmemeli.
- İade işlemleri fatura durumuyla bağlantılı düşünülmeli.
- API anahtarı/parola veritabanında açık şekilde gösterilmemeli.

## Önerilen Yol Haritası

### Faz 1: Hazırlık

- Fatura durum modelinin eklenmesi
- Günlük satışlarda fatura durum rozeti
- Satış detayında fatura geçmişi
- Ayarlarda entegrasyon ekranı taslağı

### Faz 2: Test Modu

- Sahte entegratör adaptörü
- Test fatura gönderimi
- Hata / başarı kayıtları
- Süper admin teşhis merkezinde entegrasyon testi

### Faz 3: Gerçek Entegrasyon

- Seçilecek sağlayıcının resmi API dokümanına göre adaptör
- Test ortamı
- Canlı ortam geçiş anahtarı
- Log ve hata takibi

### Faz 4: Ticari Paketleme

- Demo pakette kapalı
- Standart pakette manuel fatura durumu
- Profesyonel pakette e-fatura/e-arşiv entegrasyonu

## Şimdilik Karar

Bu çalışma mevcut uygulamaya doğrudan canlı e-fatura gönderimi eklemez. Önce sağlam bir altyapı, sonra sağlayıcı seçimi ve resmi API dokümanına göre entegrasyon yapılmalıdır.
