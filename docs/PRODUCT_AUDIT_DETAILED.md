# Ürün Denetimi — Ayrıntılı Rapor

Tarih: 2 Haziran 2026

## Yönetici Özeti

Uygulama işlevsel bir ürün çekirdeğine sahip: ana modüller açılıyor, kritik ekranlarda sunucu hatası oluşmuyor ve mevcut otomasyon paketi başarılı çalışıyor. Buna rağmen ürün dış kullanıma ve gerçek finansal veriye açılmadan önce çözülmesi gereken güvenlik ve veri bütünlüğü riskleri bulunuyor.

**Canlıya çıkış kararı:** Kapalı pilot yapılabilir. Genel kullanıma açılış için P0 bulguları giderilmelidir.

## Kapsam ve Yöntem

- `127` Flask route ve `67` veri değiştirebilen endpoint statik olarak incelendi.
- `73` HTML şablonu kullanılabilirlik, mobil yapı ve erişilebilirlik açısından tarandı.
- Bellek içi SQLite veritabanıyla `36` kritik ekran açıldı; `5xx` yanıt görülmedi.
- Test paketi çalıştırıldı: `103 passed, 12 warnings`.
- Görsel cihaz testi ve ekran okuyucu testi bu statik denetimin kapsamında değildir; tarayıcı tabanlı ikinci tur önerilir.

## P0 — Canlı Öncesi Zorunlu

### 1. Sabit e-posta ile otomatik süper admin yükseltmesi

**Kategori:** Yetki açığı  
**Kanıt:** `app.py:2562`, `app.py:4209`, `app.py:4210`

`mehmetdurna@msn.com` adresiyle kayıt olan kullanıcı, e-posta sahipliği doğrulanmadan platform sahibi yetkisi alıyor. Bu kural geliştirme kolaylığı sağlasa da üretimde hesap ele geçirme veya yanlış kayıt riskini doğrudan platform yönetimine taşır.

**Öneri:** Üretimde otomatik yükseltmeyi kaldırın. İlk platform sahibini yalnızca tek kullanımlık CLI bootstrap komutu veya kontrollü veritabanı migration'ı ile oluşturun. E-posta doğrulaması ve MFA ekleyin.

### 2. Silme ve yedek oluşturma işlemleri `GET` isteğiyle çalışıyor

**Kategori:** Yetki açığı / veri kaybı  
**Kanıt:** `app.py:4934`, `app.py:5951`, `app.py:7747`, `app.py:9446`, `app.py:9486`

Cari, teklif ve ürün silme işlemleri ile yedek oluşturma işlemi `GET` route'ları üzerinden çalışıyor. CSRF koruması yalnızca veri değiştiren HTTP metotlarında devreye girdiği için bu endpointler link önizleme, bot taraması veya kötü niyetli sayfa yönlendirmesiyle tetiklenebilir.

**Öneri:** Tüm veri değiştiren route'ları `POST` veya `DELETE` yapın, CSRF zorunluluğu uygulayın ve silme işlemlerinde kullanıcı onayı gösterin. Çıkış ve destek modundan çıkış route'larını da aynı yaklaşımla `POST` yapın.

### 3. Tenant paylaşımı ekranlar arasında tutarsız

**Kategori:** Yetki modeli / kullanılabilirlik / veri bütünlüğü  
**Kanıt:** `app.py:4589`, `app.py:6068`, `app.py:6129`, `app.py:9044`, `app.py:9120`, `app.py:9409`, `app.py:9421`, `app.py:9448`

Liste ekranları organizasyondaki kullanıcıların ortak verisini gösterirken bazı detay, düzenleme ve işlem route'ları yalnızca kaydı oluşturan kullanıcıya izin veriyor. Örneğin ekip üyesi ortak ürünü listede görebiliyor ancak stok girişi, stok çıkışı veya ürün düzenleme sırasında reddedilebiliyor. Benzer kırılma cari ödeme ve tahsilatta da var.

**Öneri:** Tek bir tenant yetkilendirme politikası tanımlayın. Tüm route'larda `belongs_to_current_tenant()` benzeri ortak yardımcıları ve rol bazlı işlem izinlerini zorunlu kullanın.

### 4. Finansal alanlarda kayan noktalı sayı kullanılıyor

**Kategori:** Veri bütünlüğü  
**Kanıt:** `app.py:211`, `app.py:230`, `app.py:248`, `app.py:434`, `app.py:453`, `app.py:472`, `app.py:2970`

Fiyat, bakiye, tahsilat, kasa ve fatura alanları `db.Float` olarak saklanıyor. Kayan noktalı sayılar finansal hesaplarda zamanla kuruş farkları ve mutabakat sorunları üretebilir.

**Öneri:** Parasal alanları migration ile `Numeric(18, 2)` veya uygun hassasiyette `Decimal` tabanlı tipe taşıyın. Hesaplamalarda da `Decimal` kullanın.

### 5. Belge numarası üretimi eşzamanlı isteklere dayanıklı değil

**Kategori:** Veri bütünlüğü  
**Kanıt:** `app.py:3189`, `app.py:3196`, `app.py:9144`, `app.py:2965`

Fatura ve teklif numaraları son kaydın ID değerine bakılarak üretiliyor. İki eşzamanlı satış aynı numarayı hesaplayabilir; benzersiz alan nedeniyle işlemlerden biri hata verir. Stok çıkışı ve POS akışında iki ayrı numara formatı da kullanılıyor.

**Öneri:** Veritabanı sequence veya ayrı sayaç tablosu kullanın. Sayaç artışını transaction içinde kilitleyin. POS ve stok çıkışı için tek belge numarası servisi tanımlayın. Tekrarlanan istemci isteklerine karşı idempotency key ekleyin.

### 6. Teklif içeren yedek geri yükleme başarısız olabilir

**Kategori:** Veri bütünlüğü / operasyon  
**Kanıt:** `app.py:8555`, `app.py:8652`

Yedek geri yükleme kodu `Teklif` modelinde bulunmayan `ara_toplam`, `kdv_tutar` ve `iskonto` alanlarını kurucuya gönderiyor. Teklif içeren bir yedek geri yüklenirken işlem hata verebilir. Ayrıca geri yükleme kullanıcının mevcut verilerini önce sildiği için operasyon dikkatle ele alınmalıdır.

**Öneri:** Yedek şeması sürümlensin, yükleme öncesi tam doğrulama yapılsın, geçici veritabanında prova edilsin ve tek transaction içinde atomik olarak değiştirilsin. Geri yükleme testleri ekleyin.

## P1 — İlk Sürüm Güçlendirmeleri

### Tenant rol yetkileri

İş modüllerinin büyük kısmı yalnızca `@login_required` ile korunuyor. Organizasyon sahibi, yönetici, satış personeli ve görüntüleyici rollerinin işlem bazlı yetkileri route seviyesinde uygulanmalıdır.

### Personel fotoğrafı yükleme doğrulaması

**Kanıt:** `app.py:3903`, `app.py:3967`, `config.py:66`

Personel fotoğrafı yüklemesi dosyayı `.jpg` adıyla kaydediyor ancak gerçek içerik tipi ve görsel doğrulaması yapmıyor. Genel yükleme boyutu sınırı var; dosya türü doğrulaması eklenmelidir.

### Güvenlik başlıkları

**Kanıt:** `config.py:69`

`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` ve `Permissions-Policy` mevcut. Üretim reverse proxy katmanında HSTS, uygulamada nonce tabanlı Content Security Policy eklenmelidir.

### Erişilebilirlik temeli

**Kanıt:** `templates/_base.html:696`, `templates/_base.html:808`, `templates/_base.html:818`, `templates/_base.html:841`, `templates/_base.html:1259`, `templates/cari_hesaplar_yonetimi_turkce_.html:155`

- Taranan form etiketlerinin büyük çoğunluğunda `for` ilişkisi bulunmuyor.
- Ortak kabuktaki bazı ikon düğmelerinde erişilebilir ad yok.
- Klavye kısayolları ve cari modalları `role="dialog"`, `aria-modal`, başlangıç odağı ve odak tuzağı içermiyor.
- Modal kapandıktan sonra odağın tetikleyici düğmeye dönmesi garanti edilmiyor.

**Öneri:** WCAG 2.2 AA hedefi belirleyin. Önce ortak kabuğu ve ortak modal bileşenini düzeltin; ardından form alanlarını `label[for]` ve `input[id]` ile eşleyin.

### Mobil kullanılabilirlik

Ortak kabuk mobil sidebar, overlay ve duyarlı grid yapılarına sahip. Büyük tabloların bir kısmında yatay kaydırma var. Buna rağmen `settings.html` ve `super_admin/dashboard.html` tek sayfada yoğun işlev taşıyor; küçük ekranlarda görev odaklı sekmelere veya alt sayfalara ayrılmalıdır.

### Liste performansı

Kodda çok sayıda sınırsız `.all()` sorgusu bulunuyor. Veri hacmi büyüdüğünde ürün, cari ve hareket ekranları yavaşlayabilir.

**Öneri:** Ana liste ekranlarına sunucu taraflı sayfalama, filtre indeksleri ve varsayılan limit ekleyin.

### CSRF için JavaScript bağımlılığı

**Kanıt:** `templates/_base.html:604`

Ortak kabuk POST formlarına CSRF alanını sayfa yüklendikten sonra JavaScript ile ekliyor. Koruma mevcut ve çalışıyor; ancak JavaScript çalışmadığında formlar hata verir.

**Öneri:** Sunucudan üretilen formlara token'ı doğrudan HTML içinde koyun, JavaScript yamamasını dinamik formlar için yedek olarak tutun.

### Kodlama ve metin bütünlüğü

**Kanıt:** `app.py:143`, `app.py:3257`, `app.py:3514`, `app.py:9213`, `docs/DEPLOY_LINUX.md:128`

Bazı metinlerde bozuk Türkçe karakterler bulunuyor. Kaynak dosyalarını UTF-8 standardına getirip kullanıcıya gösterilen metinleri temizleyin.

## P2 — Ürün Kalitesi

### Şablon temizliği

`73` şablondan `15` tanesi doğrudan `render_template()` çağrısıyla kullanılmıyor. Bazıları base/include şablonu olabilir; kalan eski ekran varyantları doğrulandıktan sonra arşivlenmelidir. Özellikle boş veya eski görünen `profil_ayarlari.html`, `teklif_form_backup.html`, `teklif_form_simple.html` ve eski giriş ekranları temizlenmelidir.

### Otomasyon genişletme

- Tenant içindeki ikinci kullanıcıyla ürün, stok, cari, ödeme ve rapor akışlarını test edin.
- İki eşzamanlı POS satışı için yarış testi ekleyin.
- Yedek oluşturma ve geri yükleme için round-trip testi ekleyin.
- Playwright ile mobil ekran görüntüsü regresyonu ekleyin.
- Axe veya Pa11y ile erişilebilirlik testi ekleyin.

## Ekran Grubu Değerlendirmesi

| Ekran grubu | Durum | Ana bulgu |
| --- | --- | --- |
| Giriş, kayıt, parola sıfırlama | Riskli | Kayıtta doğrulamasız otomatik platform sahibi yükseltmesi var. |
| Dashboard ve başlangıç | İyi | Duman testi başarılı, responsive kabuk mevcut. |
| Ürün ve stok | Riskli | Tenant listeleme ile işlem yetkileri tutarsız; GET ile ürün silme var. |
| Cari ve finans | Riskli | GET ile cari silme, kullanıcı bazlı ödeme/tahsilat kısıtı ve Float alanları var. |
| POS, satış ve iade | Orta risk | Ana akış açılıyor; belge numarası yarışa açık ve idempotency yok. |
| Teklif ve raporlar | Riskli | GET ile teklif silme ve geri yükleme uyumsuzluğu var. |
| Ön muhasebe | Orta risk | Tenant kapsamı daha tutarlı; Decimal dönüşümü gerekli. |
| Personel | Orta risk | Hassas kişisel veri tutuluyor; fotoğraf doğrulaması ve rol ayrımı güçlendirilmeli. |
| Ayarlar ve yedekleme | Riskli | Geri yükleme şeması ve GET yedek oluşturma düzeltilmeli. |
| Destek | İyi | Ek indirmede ticket erişim kontrolü bulunuyor; yükleme sınırı uygulanıyor. |
| Süper admin | Orta risk | Yetki katmanı var; otomatik owner kuralı, MFA ve destek modu çıkışı düzeltilmeli. |

## Doğrulanan Güçlü Yönler

- Genel CSRF koruması ve istemci taraflı token ekleme mekanizması mevcut.
- Güvenlik başlıklarının temel seti uygulanıyor.
- Destek eki indirme akışında organizasyon erişim kontrolü bulunuyor.
- Ortak kabuk mobil sidebar ve koyu tema desteği içeriyor.
- Audit log, destek bileti, platform kilitleri ve süper admin izin altyapısı bulunuyor.
- `36` kritik ekran duman testinde açıldı; `5xx` hata görülmedi.
- Otomasyon paketi başarılı: `103 passed`.

## Önerilen Uygulama Sırası

1. Otomatik süper admin yükseltmesini güvenli bootstrap akışına taşıyın.
2. Tüm `GET` mutasyonlarını `POST` veya `DELETE` yapın.
3. Tenant yetki politikasını merkezileştirip stok ve cari akışlarını düzeltin.
4. Yedek geri yüklemeyi atomik ve testli hale getirin.
5. Finansal alanları `Decimal` tabanlı tipe taşıyın; belge numarası servisini birleştirin.
6. Ortak erişilebilir modal ve form bileşenlerini düzeltin.
7. Mobil yoğun ekranları görev odaklı alt sayfalara bölün.
8. PostgreSQL staging ortamında yük, yarış ve yedek geri dönüş testlerini çalıştırın.
