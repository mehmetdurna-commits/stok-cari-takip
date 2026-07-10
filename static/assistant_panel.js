(function () {
    'use strict';

    const DEFAULT_RESULT = {
        intent: 'unknown',
        title: 'Komutu netleştiremedim',
        confidence: 'Düşük',
        summary: 'Bu komutu güvenli şekilde işleme çevirmek için biraz daha açık yazman gerekiyor.',
        fields: [
            ['İşlem Türü', 'Belirsiz'],
            ['Durum', 'Onay Bekliyor']
        ],
        routeHint: '',
        note: 'Bu sürümde işlem yapılmaz, sadece analiz edilir.'
    };

    function normalizeCommand(value) {
        return String(value || '')
            .toLocaleLowerCase('tr-TR')
            .replace(/[’']/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function extractAmount(text) {
        const match = String(text || '').match(/(\d+(?:[.,]\d+)?)\s*(tl|lira|₺|adet|tane)?/i);
        if (!match) return null;
        return {
            value: Number(String(match[1]).replace(',', '.')),
            unit: match[2] || ''
        };
    }

    function cleanEntity(text) {
        return String(text || '')
            .replace(/\b([a-zçğıöşü0-9]+)(dan|den|tan|ten)\b/gi, '$1')
            .replace(/\b(stoğa|stoga|stoktan|stok|ürün|urun|ekle|giriş|girişi|giris|girisi|çıkış|çıkışı|cikis|cikisi|düş|dus|adet|tane|tl|lira|tahsilat|ödeme|odeme|al|yap|sat|satış|satis|pos|listele|göster|goster|bugünkü|bugunku|kritik|borcu|bakiye|kasaya|kasadan|müşteriden|musteriden|tedarikçiye|tedarikciye|teklif|oluştur|olustur|hazırla|hazirla|cari|müşteri|musteri|dan|den|tan|ten)\b/gi, ' ')
            .replace(/\d+(?:[.,]\d+)?/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function formatAmount(amount, fallbackUnit) {
        if (!amount) return 'Eksik';
        const unit = fallbackUnit || amount.unit || '';
        return `${amount.value} ${unit}`.trim();
    }

    function createAnalysisResult(overrides) {
        return Object.assign({}, DEFAULT_RESULT, overrides || {});
    }

    function assistantResultField(result, label) {
        const fields = result && Array.isArray(result.fields) ? result.fields : [];
        const row = fields.find((field) => {
            const fieldLabel = Array.isArray(field) ? field[0] : field.label;
            return fieldLabel === label;
        });
        if (!row) return '';
        return String(Array.isArray(row) ? row[1] : row.value || '').trim();
    }

    function parseQuantityValue(value) {
        const match = String(value || '').replace(',', '.').match(/(\d+(?:\.\d+)?)/);
        if (!match) return 1;
        const quantity = Number(match[1]);
        return Number.isFinite(quantity) && quantity > 0 ? quantity : 1;
    }

    function helpAnswer(text) {
        const topics = [
            {
                keywords: ['nasıl satış', 'satis nasil', 'satış nasıl', 'satışı nasıl', 'satisi nasil', 'pos nasıl', 'pos nasil'],
                result: {
                    intent: 'help_pos',
                    title: 'POS satışı nasıl yapılır?',
                    confidence: 'Yüksek',
                    summary: 'POS ekranında ürünü barkodla okutun veya arayın, sepete ekleyin, ödeme tipini seçin ve satışı tamamlayın.',
                    fields: [['1', 'Ürünü okut veya ara'], ['2', 'Sepeti kontrol et'], ['3', 'Ödeme tipini seç'], ['4', 'Satışı tamamla']],
                    routeHint: '/pos',
                    note: 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.'
                }
            },
            {
                keywords: ['stok nasıl', 'stok nasil', 'ürün nasıl', 'urun nasil'],
                result: {
                    intent: 'help_stock',
                    title: 'Stok nasıl yönetilir?',
                    confidence: 'Yüksek',
                    summary: 'Ürün kartlarını Ürünler ekranından açabilir, stok girişlerini Stok Girişi ekranından yapabilirsiniz.',
                    fields: [['Ürün Kartı', 'Ad, barkod, fiyat ve kritik stok'], ['Stok Girişi', 'Alınan ürün miktarını stoğa ekler'], ['Kritik Stok', 'Azalan ürünleri gösterir']],
                    routeHint: '/urunler',
                    note: 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.'
                }
            },
            {
                keywords: ['cari nasıl', 'cari nasil', 'cari hesap nasıl', 'cari hesap nasil', 'tahsilat nasıl', 'tahsilat nasil', 'müşteri borcu', 'musteri borcu'],
                result: {
                    intent: 'help_cari',
                    title: 'Cari hesap nasıl takip edilir?',
                    confidence: 'Yüksek',
                    summary: 'Cariler ekranında müşteri ve tedarikçileri takip eder, tahsilat ve ödeme hareketlerini kayıt altına alırsınız.',
                    fields: [['Müşteri', 'Veresiye satış sonrası borç oluşur'], ['Tahsilat', 'Müşteri borcunu azaltır'], ['Ekstre', 'Hareketleri tarih sırasıyla gösterir']],
                    routeHint: '/cariler',
                    note: 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.'
                }
            },
            {
                keywords: ['teklif nasıl', 'teklif nasil'],
                result: {
                    intent: 'help_quote',
                    title: 'Teklif nasıl hazırlanır?',
                    confidence: 'Yüksek',
                    summary: 'Teklifler ekranından cari seçip ürün kalemlerini eklersiniz; ardından yazdırılabilir teklif çıktısı alabilirsiniz.',
                    fields: [['1', 'Cari seç'], ['2', 'Ürün kalemlerini ekle'], ['3', 'KDV ve geçerlilik bilgisini kontrol et'], ['4', 'Kaydet veya yazdır']],
                    routeHint: '/teklifler',
                    note: 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.'
                }
            },
            {
                keywords: ['rapor', 'bugün ne oldu', 'bugun ne oldu', 'özet', 'ozet'],
                result: {
                    intent: 'help_reports',
                    title: 'İşletme özeti nereden görülür?',
                    confidence: 'Yüksek',
                    summary: 'Ana Panel ve Raporlar ekranları satış, stok ve cari durumunu hızlıca görmeniz için hazırlanmıştır.',
                    fields: [['Ana Panel', 'Güncel işletme durumunu gösterir'], ['Raporlar', 'Satış, stok ve cari özetlerini derler']],
                    routeHint: '/dashboard',
                    note: 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.'
                }
            },
            {
                keywords: ['şifre', 'sifre', 'parola', 'giriş yapamıyorum', 'giris yapamiyorum'],
                result: {
                    intent: 'help_login',
                    title: 'Giriş ve şifre işlemleri',
                    confidence: 'Yüksek',
                    summary: 'Giriş yapamıyorsanız e-posta adresinizi kontrol edin ve Giriş ekranındaki “Şifremi unuttum” bağlantısıyla yeni şifre belirleyin.',
                    fields: [['1', 'E-posta adresini kontrol edin'], ['2', 'Şifremi unuttum bağlantısını kullanın'], ['3', 'E-postadaki bağlantıyla şifreyi yenileyin']],
                    routeHint: '/giris',
                    note: 'Şifre sıfırlama e-postası gelmezse spam klasörünü kontrol edin veya destek talebi açın.'
                }
            },
            {
                keywords: ['iade', 'ürün iadesi', 'urun iadesi'],
                result: {
                    intent: 'help_return',
                    title: 'İade işlemi nasıl yapılır?',
                    confidence: 'Yüksek',
                    summary: 'İade ekranında ilgili cari ve ürün seçilerek iade türü belirlenir; işlem cari hareketlere ve stok durumuna göre takip edilir.',
                    fields: [['Cari', 'İadenin hangi müşteriye ait olduğunu belirtir'], ['Ürün', 'İade edilen ürünü ve miktarı gösterir'], ['İade Türü', 'Para iadesi, cari alacak veya değişim akışını belirler']],
                    routeHint: '/iade',
                    note: 'İade kaydı oluşturmadan önce ürün ve cari bilgisini kontrol edin.'
                }
            },
            {
                keywords: ['nakit', 'kasa', 'banka', 'pos hesabı', 'pos hesabi', 'para aktar'],
                result: {
                    intent: 'help_cash',
                    title: 'Kasa, banka ve POS nasıl takip edilir?',
                    confidence: 'Yüksek',
                    summary: 'Nakit Yönetimi ve Ön Muhasebe hesaplarıyla kasa giriş/çıkışlarını, banka hareketlerini ve POS aktarımını takip edebilirsiniz.',
                    fields: [['Kasa', 'Nakit giriş ve çıkışları gösterir'], ['Banka', 'Banka hesabına giren ve çıkan parayı izler'], ['POS', 'Kart satışlarından bekleyen tutarları takip eder']],
                    routeHint: '/onmuhasebe/hesaplar',
                    note: 'POS tahsilatları bankaya geçtiğinde hesaplar arası aktarım kullanılabilir.'
                }
            },
            {
                keywords: ['paket', 'limit', 'yükselt', 'yukselt', 'lisans', 'fiyat'],
                result: {
                    intent: 'help_package',
                    title: 'Paket ve limit bilgileri',
                    confidence: 'Yüksek',
                    summary: 'Demo, Standart ve Profesyonel paketler ürün limiti ve kullanım kapsamına göre ayrılır. Paket yükseltme ekranından talep oluşturabilirsiniz.',
                    fields: [['Demo', 'Deneme amaçlı sınırlı kullanım'], ['Standart', 'Belirli ürün limitine kadar kullanım'], ['Profesyonel', 'Sınırsız ürün ve geniş kullanım']],
                    routeHint: '/paket-yukselt',
                    note: 'Paket yükseltme işlemi ödeme/talep akışına yönlendirir.'
                }
            },
            {
                keywords: ['ayar', 'ayarlar', 'logo', 'firma bilgileri', 'bildirim'],
                result: {
                    intent: 'help_settings',
                    title: 'Firma ayarları nereden yapılır?',
                    confidence: 'Yüksek',
                    summary: 'Ayarlar ekranından firma bilgileri, logo, tercihler ve bildirim ayarları yönetilir.',
                    fields: [['Firma Bilgileri', 'Ad, adres, telefon ve logo'], ['Tercihler', 'Sayfa ve kullanım tercihleri'], ['Bildirimler', 'Uyarı ve bilgilendirme tercihleri']],
                    routeHint: '/settings',
                    note: 'Logo ve firma bilgileri teklif, ekstre ve bazı çıktılarda kullanılabilir.'
                }
            },
            {
                keywords: ['personel', 'maaş', 'maas', 'izin', 'avans', 'prim'],
                result: {
                    intent: 'help_personnel',
                    title: 'Personel yönetimi nasıl kullanılır?',
                    confidence: 'Yüksek',
                    summary: 'Personel ekranından çalışan listesi, izin, avans, prim ve bordro akışları takip edilir.',
                    fields: [['Personel', 'Çalışan kartlarını listeler'], ['İzin', 'Personelin izin durumunu takip eder'], ['Avans / Prim', 'Maaş dışı hareketleri gösterir']],
                    routeHint: '/personel',
                    note: 'Personel kayıtları düzenli tutulursa bordro ve ödeme listeleri daha sağlıklı hazırlanır.'
                }
            },
            {
                keywords: ['yazdır', 'yazdir', 'fiş', 'fis', 'irsaliye', 'ekstre'],
                result: {
                    intent: 'help_print',
                    title: 'Yazdırma işlemleri nereden yapılır?',
                    confidence: 'Yüksek',
                    summary: 'Fiş, irsaliye, teklif ve cari ekstre çıktıları ilgili ekranlarda bulunan yazdırma butonlarıyla alınır.',
                    fields: [['Fiş', 'POS veya Günlük Satışlar ekranından yazdırılır'], ['İrsaliye', 'Günlük Satışlar satış satırından alınır'], ['Ekstre', 'Cari detay ekranından yazdırılır']],
                    routeHint: '/gunluk-satislar',
                    note: 'Yazdırma penceresi açılmazsa tarayıcı pop-up izinlerini kontrol edin.'
                }
            },
            {
                keywords: ['fatura', 'e-fatura', 'efatura', 'entegratör', 'entegrator'],
                result: {
                    intent: 'help_invoice',
                    title: 'Fatura ve entegrasyon durumu',
                    confidence: 'Yüksek',
                    summary: 'Esstok’ta satış, teklif, fiş, irsaliye ve cari kayıtları takip edilir. Resmi e-fatura/e-arşiv kesimi için entegratör bağlantısı ayrıca yapılandırılmalıdır.',
                    fields: [['Bugün', 'Satış, fiş, irsaliye ve teklif çıktıları kullanılabilir'], ['Entegrasyon', 'Fatura entegratörü bilgileriyle geliştirilebilir'], ['Öneri', 'Canlı fatura kesmeden önce mali müşavir ve entegratör ayarları kontrol edilmelidir']],
                    routeHint: '/teklifler',
                    note: 'Bu cevap bilgilendirme amaçlıdır; resmi mali belge üretimi için entegratör altyapısı gerekir.'
                }
            }
        ];
        const topic = topics.find((item) => item.keywords.some((keyword) => text.includes(keyword)));
        return topic ? createAnalysisResult(topic.result) : null;
    }

    function fallbackAnswer() {
        return createAnalysisResult({
            intent: 'help_general',
            title: 'Size nasıl yardımcı olabilirim?',
            confidence: 'Orta',
            summary: 'Bu soruyu tek bir ekrana net bağlayamadım; yine de Esstok içinde stok, cari, POS, teklif, iade, rapor, ayarlar ve personel konularında yardımcı olabilirim.',
            fields: [
                ['Örnek', '“POS satışı nasıl yapılır?”'],
                ['Örnek', '“Cari hesap nasıl takip edilir?”'],
                ['Örnek', '“Stoğa 100 adet Selpak ekle”'],
                ['Destek', 'Yanıt yeterli olmazsa destek talebi oluşturabilirsiniz']
            ],
            routeHint: '/destek',
            note: 'Bu cevap destek amaçlıdır; kullanıcı onayı olmadan hiçbir işlem yapılmaz.'
        });
    }

    function analyzeCommand(command) {
        const raw = String(command || '').trim();
        const text = normalizeCommand(raw);
        const amount = extractAmount(text);

        if (!text) {
            return createAnalysisResult({
                summary: 'Önce bir komut yazmalı veya söylemelisin.',
                fields: [
                    ['İşlem Türü', 'Belirsiz'],
                    ['Durum', 'Komut Bekleniyor']
                ]
            });
        }

        if ((text.includes('kasa') || text.includes('kasadan') || text.includes('kasaya') || text.includes('banka') || text.includes('bankadan') || text.includes('bankaya'))
            && (text.includes('giriş') || text.includes('giris') || text.includes('çıkış') || text.includes('cikis') || text.includes('çıkar') || text.includes('cikar') || text.includes('masraf') || text.includes('gider') || text.includes('harcama') || text.includes('ödeme') || text.includes('odeme') || text.includes('öde') || text.includes('ode'))) {
            const isBank = text.includes('banka') || text.includes('bankadan') || text.includes('bankaya');
            const isIn = text.includes('giriş') || text.includes('giris') || text.includes('yatır') || text.includes('yatir') || text.includes('geldi') || text.includes('ekle') || text.includes('kasaya') || text.includes('bankaya');
            const isOut = text.includes('çıkış') || text.includes('cikis') || text.includes('çıkar') || text.includes('cikar') || text.includes('ödeme') || text.includes('odeme') || text.includes('öde') || text.includes('ode') || text.includes('masraf') || text.includes('gider') || text.includes('harcama') || text.includes('kasadan') || text.includes('bankadan');
            const movement = isIn && !isOut ? 'giris' : 'cikis';
            const accountLabel = isBank ? 'Banka' : 'Kasa';
            const description = cleanEntity(text).replace(/\b(para|giriş|girişi|giris|girisi|çıkış|çıkışı|cikis|cikisi|çıkar|cikar|yatır|yatir)\b/gi, ' ').replace(/\s+/g, ' ').trim() || (movement === 'giris' ? 'Para girişi' : 'Para çıkışı');
            return createAnalysisResult({
                intent: 'cash_movement',
                title: `${accountLabel} ${movement === 'giris' ? 'girişi' : 'çıkışı'} taslağı`,
                confidence: amount ? 'Yüksek' : 'Orta',
                summary: `${accountLabel} hesabında ${formatAmount(amount, 'TL')} ${movement === 'giris' ? 'giriş' : 'çıkış'} işlemi için onay taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', movement === 'giris' ? 'Para Girişi' : 'Para Çıkışı'],
                    ['Hesap Türü', accountLabel],
                    ['Tutar', formatAmount(amount, 'TL')],
                    ['Açıklama', description],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/onmuhasebe/hesaplar',
                note: 'Onay verirseniz bu işlem ilgili kasa/banka hesabına kaydedilir.',
                draftReady: Boolean(amount),
                executable: Boolean(amount),
                requiresConfirmation: true,
                confirmationTitle: 'Para hareketini onayla',
                confirmationMessage: `${accountLabel} hesabına ${formatAmount(amount, 'TL')} ${movement === 'giris' ? 'para girişi' : 'para çıkışı'} kaydedilecek.`,
                action: {
                    type: 'cash_transaction',
                    account_type: isBank ? 'bank' : 'cash',
                    islem_tipi: movement,
                    amount: amount ? amount.value : null,
                    description
                }
            });
        }

        const helpResult = helpAnswer(text);
        if (helpResult) return helpResult;

        if ((text.includes('stoğa') || text.includes('stoga') || text.includes('stok')) && (text.includes('ekle') || text.includes('giriş') || text.includes('giris'))) {
            const product = cleanEntity(text);
            return createAnalysisResult({
                intent: 'stock_in',
                title: 'Stok girişi taslağı',
                confidence: product && amount ? 'Yüksek' : 'Orta',
                summary: `${product || 'Seçilecek ürün'} için stok girişi taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Stok Girişi'],
                    ['Ürün', product || 'Eksik'],
                    ['Miktar', formatAmount(amount, 'adet')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/stok/giris'
            });
        }

        if ((text.includes('stoktan') || text.includes('stok')) && (text.includes('düş') || text.includes('dus') || text.includes('çıkış') || text.includes('cikis'))) {
            const product = cleanEntity(text);
            return createAnalysisResult({
                intent: 'stock_out',
                title: 'Stok çıkışı taslağı',
                confidence: product && amount ? 'Yüksek' : 'Orta',
                summary: `${product || 'Seçilecek ürün'} için stok çıkışı taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Stok Çıkışı'],
                    ['Ürün', product || 'Eksik'],
                    ['Miktar', formatAmount(amount, 'adet')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/stok/cikis'
            });
        }

        if (text.includes('tahsilat') || (text.includes('müşteri') && text.includes('al'))) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'collection',
                title: 'Müşteriden tahsilat taslağı',
                confidence: customer && amount ? 'Yüksek' : 'Orta',
                summary: `${customer || 'Seçilecek cari'} için tahsilat taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Müşteriden Tahsilat'],
                    ['Cari', customer || 'Eksik'],
                    ['Tutar', formatAmount(amount, 'TL')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cariler'
            });
        }

        if (text.includes('ödeme') || text.includes('odeme') || text.includes('tedarikçi') || text.includes('tedarikci')) {
            const supplier = cleanEntity(text);
            return createAnalysisResult({
                intent: 'supplier_payment',
                title: 'Tedarikçiye ödeme taslağı',
                confidence: supplier && amount ? 'Yüksek' : 'Orta',
                summary: `${supplier || 'Seçilecek tedarikçi'} için ödeme taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Tedarikçiye Ödeme'],
                    ['Cari', supplier || 'Eksik'],
                    ['Tutar', formatAmount(amount, 'TL')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cariler'
            });
        }

        const isSaleQuery = text.includes('göster') || text.includes('goster') || text.includes('listele') || text.includes('bugünkü') || text.includes('bugunku') || text.includes('günlük') || text.includes('gunluk');
        if (!isSaleQuery && (text.includes('satış') || text.includes('satis') || text.includes('pos') || /\bsat\b/.test(text))) {
            const product = cleanEntity(text);
            return createAnalysisResult({
                intent: 'pos_sale',
                title: 'Hızlı satış taslağı',
                confidence: product && amount ? 'Yüksek' : 'Orta',
                summary: `${product || 'Seçilecek ürün'} için POS satış taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Hızlı Satış'],
                    ['Ürün', product || 'Eksik'],
                    ['Miktar', formatAmount(amount, 'adet')],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/pos'
            });
        }

        if (text.includes('teklif') && (text.includes('oluştur') || text.includes('olustur') || text.includes('hazırla') || text.includes('hazirla') || text.includes('aç') || text.includes('ac'))) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'quote',
                title: 'Teklif oluşturma taslağı',
                confidence: customer ? 'Orta' : 'Düşük',
                summary: `${customer || 'Seçilecek cari'} için teklif oluşturma taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Teklif Oluştur'],
                    ['Cari', customer || 'Eksik'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/teklif/ekle'
            });
        }

        if ((text.includes('cari') || text.includes('müşteri') || text.includes('musteri')) && (text.includes('ekle') || text.includes('oluştur') || text.includes('olustur') || text.includes('aç') || text.includes('ac'))) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'cari_create',
                title: 'Cari ekleme taslağı',
                confidence: customer ? 'Orta' : 'Düşük',
                summary: `${customer || 'Yeni cari'} için cari kartı açma taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Cari Ekle'],
                    ['Cari', customer || 'Eksik'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cari-ekle'
            });
        }

        if (text.includes('bugünkü satış') || text.includes('bugunku satis') || text.includes('günlük satış') || text.includes('gunluk satis')) {
            return createAnalysisResult({
                intent: 'daily_sales',
                title: 'Günlük satış sorgusu',
                confidence: 'Yüksek',
                summary: 'Bugünkü satışlar için sorgu taslağı hazırlandı.',
                fields: [
                    ['İşlem Türü', 'Bilgi Sorgusu'],
                    ['Ekran', 'Günlük Satışlar'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/gunluk-satislar'
            });
        }

        if (text.includes('kritik stok') || text.includes('azalan stok')) {
            return createAnalysisResult({
                intent: 'critical_stock',
                title: 'Kritik stok sorgusu',
                confidence: 'Yüksek',
                summary: 'Kritik stoktaki ürünler için sorgu taslağı hazırlandı.',
                fields: [
                    ['İşlem Türü', 'Bilgi Sorgusu'],
                    ['Filtre', 'Kritik Stok'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/urunler'
            });
        }

        if (text.includes('bakiye') || text.includes('borcu') || text.includes('alacağı') || text.includes('alacagi')) {
            const customer = cleanEntity(text);
            return createAnalysisResult({
                intent: 'customer_balance',
                title: 'Cari bakiye sorgusu',
                confidence: customer ? 'Orta' : 'Düşük',
                summary: `${customer || 'Seçilecek cari'} için bakiye sorgusu taslağı hazırlandı.`,
                fields: [
                    ['İşlem Türü', 'Cari Bakiye Sorgusu'],
                    ['Cari', customer || 'Eksik'],
                    ['Durum', 'Onay Bekliyor']
                ],
                routeHint: '/cariler'
            });
        }

        return fallbackAnswer();
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    class AssistantPanel {
        constructor(options) {
            this.options = Object.assign({
                panelId: 'voice-assistant-panel',
                inputId: 'voice-assistant-input',
                resultId: 'voice-assistant-result',
                micId: 'voice-assistant-mic',
                listeningId: 'voice-assistant-listening',
                fabId: 'voice-assistant-fab'
            }, options || {});
            this.panel = document.getElementById(this.options.panelId);
            this.input = document.getElementById(this.options.inputId);
            this.result = document.getElementById(this.options.resultId);
            this.micButton = document.getElementById(this.options.micId);
            this.listening = document.getElementById(this.options.listeningId);
            this.fab = document.getElementById(this.options.fabId);
            this.analyzeButton = this.panel ? this.panel.querySelector('[data-assistant-action="analyze"]') : null;
            this.recognition = null;
            this.currentResult = null;
            this.selectedCandidate = null;
            this.historyKey = 'esstok_assistant_recent_commands';
            this.history = this.loadHistory();
            this.confirmModal = null;
        }

        init() {
            if (!this.panel || !this.input || !this.result) return;
            document.body.appendChild(this.panel);
            if (this.fab) document.body.appendChild(this.fab);
            this.bindEvents();
            this.renderWelcome();
            window.esstokAssistantPanel = this;
        }

        bindEvents() {
            document.querySelectorAll('[data-assistant-action]').forEach((element) => {
                element.addEventListener('click', () => {
                    const action = element.dataset.assistantAction;
                    if (action === 'open') this.open();
                    if (action === 'close') this.close();
                    if (action === 'toggle') this.toggle();
                    if (action === 'analyze') this.analyze();
                    if (action === 'example') this.fillExample(element.dataset.assistantExample || '');
                    if (action === 'mic') this.startListening();
                    if (action === 'clear') this.clear();
                });
            });

            this.result.addEventListener('click', (event) => {
                const candidateButton = event.target.closest('[data-assistant-candidate-index]');
                if (candidateButton) {
                    const index = Number(candidateButton.dataset.assistantCandidateIndex);
                    this.selectCandidate(index);
                    return;
                }

                const historyButton = event.target.closest('[data-assistant-history-index]');
                if (historyButton) {
                    const index = Number(historyButton.dataset.assistantHistoryIndex);
                    this.useHistory(index);
                    return;
                }

                const confirmButton = event.target.closest('[data-assistant-confirm]');
                if (confirmButton) {
                    this.openConfirmModal();
                    return;
                }

                const posDraftButton = event.target.closest('[data-assistant-pos-draft]');
                if (posDraftButton) {
                    this.preparePosDraft();
                }
            });

            this.input.addEventListener('keydown', (event) => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
                    event.preventDefault();
                    this.analyze();
                }
            });

            document.addEventListener('keydown', (event) => {
                if ((event.ctrlKey || event.metaKey) && event.code === 'Space') {
                    const target = event.target;
                    if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
                    event.preventDefault();
                    this.open();
                }
                if (event.key === 'Escape' && !this.panel.classList.contains('hidden')) {
                    this.close();
                }
            });
        }

        open() {
            this.panel.classList.remove('hidden');
            if (this.fab) this.fab.setAttribute('aria-expanded', 'true');
            setTimeout(() => this.input.focus(), 80);
        }

        close() {
            this.panel.classList.add('hidden');
            if (this.fab) this.fab.setAttribute('aria-expanded', 'false');
        }

        toggle() {
            if (this.panel.classList.contains('hidden')) this.open();
            else this.close();
        }

        fillExample(text) {
            this.input.value = text || '';
            this.analyze();
        }

        async analyze() {
            const command = this.input.value || '';
            this.setAnalyzing(true);
            const result = await this.analyzeWithApi(command);
            this.currentResult = result;
            this.selectedCandidate = null;
            this.saveHistory(command);
            this.setAnalyzing(false);
            this.renderResult(result);
            if (!command.trim() && window.showToast) {
                window.showToast('Önce bir komut yazın veya sesli komut verin.', 'warning', 3500);
            }
        }

        clear() {
            this.input.value = '';
            this.currentResult = null;
            this.selectedCandidate = null;
            this.renderWelcome();
            this.input.focus();
        }

        setAnalyzing(isAnalyzing) {
            if (!this.analyzeButton) return;
            this.analyzeButton.disabled = isAnalyzing;
            this.analyzeButton.classList.toggle('opacity-70', isAnalyzing);
            this.analyzeButton.classList.toggle('cursor-wait', isAnalyzing);
            this.analyzeButton.innerHTML = isAnalyzing
                ? '<span class="material-symbols-outlined text-lg animate-spin">progress_activity</span> Analiz Ediliyor'
                : '<span class="material-symbols-outlined text-lg">psychology</span> Analiz Et';
        }

        async analyzeWithApi(command) {
            try {
                const response = await fetch('/api/assistant/analyze', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({ command })
                });
                if (!response.ok) throw new Error(`Assistant API ${response.status}`);
                const payload = await response.json();
                if (payload && payload.success && payload.result) {
                    return this.normalizeApiResult(payload.result);
                }
            } catch (error) {
                console.warn('Assistant API kullanılamadı, yerel analiz devrede:', error);
            }
            return analyzeCommand(command);
        }

        renderWelcome() {
            this.result.innerHTML = `
                <div class="space-y-3 text-sm">
                    <div class="flex items-start gap-3 rounded-3xl bg-white/72 p-3 dark:bg-slate-950/30">
                        <span class="material-symbols-outlined rounded-2xl bg-primary-50 p-2 text-primary-600 dark:bg-primary-950/40 dark:text-primary-300">tips_and_updates</span>
                        <div>
                            <p class="font-black text-slate-800 dark:text-white">Esstok Konuş hazır.</p>
                            <p class="mt-1 leading-6">Komut yazın, soru sorun veya sesli deneyin. İşlem yapmadan önce sadece taslak gösterilir.</p>
                        </div>
                    </div>
                    <div class="grid gap-2">
                        <button type="button" data-assistant-history-index="-101" class="rounded-2xl border border-slate-200 bg-white/80 px-3 py-2 text-left text-xs font-bold text-slate-600 transition hover:border-primary-200 hover:text-primary-700 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-300">POS satışı nasıl yapılır?</button>
                        <button type="button" data-assistant-history-index="-102" class="rounded-2xl border border-slate-200 bg-white/80 px-3 py-2 text-left text-xs font-bold text-slate-600 transition hover:border-primary-200 hover:text-primary-700 dark:border-slate-800 dark:bg-slate-900/60 dark:text-slate-300">Cari hesap nasıl takip edilir?</button>
                    </div>
                </div>
            `;
        }

        normalizeApiResult(result) {
            return {
                intent: result.intent || 'unknown',
                title: result.title || 'Komut analizi',
                confidence: result.confidence || 'Düşük',
                summary: result.summary || '',
                fields: Array.isArray(result.fields) ? result.fields.map((field) => {
                    if (Array.isArray(field)) return field;
                    return [field.label || '', field.value || ''];
                }) : [],
                routeHint: result.route_hint || result.routeHint || '',
                note: result.note || 'Bu sürümde işlem yapılmaz, sadece analiz edilir.',
                matchStatus: result.match_status || '',
                candidateType: result.candidate_type || '',
                candidates: Array.isArray(result.candidates) ? result.candidates : [],
                missingFields: Array.isArray(result.missing_fields) ? result.missing_fields : [],
                requiresMatch: Boolean(result.requires_match),
                draftReady: Boolean(result.draft_ready),
                executable: Boolean(result.executable),
                requiresConfirmation: Boolean(result.requires_confirmation),
                confirmationTitle: result.confirmation_title || 'İşlemi onayla',
                confirmationMessage: result.confirmation_message || '',
                action: result.action || null
            };
        }

        selectCandidate(index) {
            if (!this.currentResult || !Array.isArray(this.currentResult.candidates)) return;
            const candidate = this.currentResult.candidates[index];
            if (!candidate) return;
            this.selectedCandidate = candidate;
            this.renderResult(this.currentResult);
        }

        renderResult(result) {
            const confidenceClass = result.confidence === 'Yüksek'
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : (result.confidence === 'Orta'
                    ? 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300'
                    : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300');
            const fieldsHtml = (result.fields || []).map((field) => {
                const label = Array.isArray(field) ? field[0] : field.label;
                const value = Array.isArray(field) ? field[1] : field.value;
                return `
                <div class="flex items-center justify-between gap-3 rounded-2xl bg-slate-50 px-3 py-2 text-xs dark:bg-slate-950/50">
                    <span class="font-black uppercase tracking-wide text-slate-400">${escapeHtml(label)}</span>
                    <span class="text-right font-bold text-slate-900 dark:text-white">${escapeHtml(value)}</span>
                </div>
            `;
            }).join('');
            const routeHtml = result.routeHint ? `
                <a href="${escapeHtml(this.safeInternalRoute(result.routeHint))}" class="flex w-full min-w-0 items-center justify-between gap-3 rounded-2xl border border-blue-100 bg-blue-50 px-3 py-2 text-xs font-bold text-blue-700 transition hover:bg-blue-100 dark:border-blue-900/40 dark:bg-blue-950/25 dark:text-blue-300 dark:hover:bg-blue-950/40">
                    <span class="min-w-0">
                        <span class="block text-[10px] font-black uppercase tracking-[0.14em] text-blue-400 dark:text-blue-500">Önerilen ekran</span>
                        <span class="block truncate font-black">${escapeHtml(result.routeHint)}</span>
                    </span>
                    <span class="material-symbols-outlined shrink-0 text-base">open_in_new</span>
                </a>
            ` : '';
            const confirmHtml = this.canConfirmResult(result) ? `
                <button type="button" data-assistant-confirm="1" class="flex w-full items-center justify-center gap-2 rounded-2xl bg-emerald-600 px-4 py-3 text-sm font-black text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700">
                    <span class="material-symbols-outlined text-lg">verified</span>
                    Onay Ekranını Aç
                </button>
            ` : '';
            const posDraftHtml = this.renderPosDraftButton(result);
            const candidatesHtml = this.renderCandidates(result);
            const selectedHtml = this.renderSelectedCandidate();
            this.result.innerHTML = `
                <div class="space-y-3">
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <p class="text-xs font-black uppercase tracking-[0.18em] text-primary-600 dark:text-primary-300">Anladığım İşlem</p>
                            <h3 class="mt-1 text-lg font-black tracking-tight text-slate-950 dark:text-white">${escapeHtml(result.title)}</h3>
                        </div>
                        <span class="shrink-0 rounded-full px-2.5 py-1 text-[11px] font-black ${confidenceClass}">${escapeHtml(result.confidence)}</span>
                    </div>
                    <div class="rounded-2xl bg-slate-900 px-4 py-3 text-sm font-bold leading-6 text-white dark:bg-white dark:text-slate-950">${escapeHtml(result.summary)}</div>
                    <div class="grid gap-2">${fieldsHtml}</div>
                    ${candidatesHtml}
                    ${selectedHtml}
                    ${posDraftHtml}
                    ${confirmHtml}
                    ${routeHtml}
                    <div class="rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/25 dark:text-amber-200">
                        <span class="font-black">Güvenlik:</span> Kullanıcı onayı olmadan hiçbir stok, cari veya kasa işlemi yapılmaz.
                    </div>
                    <p class="text-xs font-semibold leading-5 text-slate-500 dark:text-slate-400">${escapeHtml(result.note)}</p>
                </div>
            `;
        }

        ensureConfirmModal() {
            if (this.confirmModal) return this.confirmModal;
            const modal = document.createElement('div');
            modal.className = 'fixed inset-0 z-[140] hidden items-center justify-center bg-slate-950/45 px-4 backdrop-blur-sm';
            modal.innerHTML = `
                <div class="w-full max-w-md rounded-[2rem] border border-slate-200 bg-white p-5 shadow-2xl dark:border-slate-800 dark:bg-slate-900">
                    <div class="flex items-start gap-3">
                        <span class="material-symbols-outlined rounded-2xl bg-emerald-50 p-2 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-300">verified_user</span>
                        <div class="min-w-0">
                            <h3 data-confirm-title class="text-lg font-black text-slate-950 dark:text-white">İşlemi onayla</h3>
                            <p data-confirm-message class="mt-2 text-sm font-semibold leading-6 text-slate-600 dark:text-slate-300"></p>
                        </div>
                    </div>
                    <div data-confirm-details class="mt-4 space-y-2 rounded-3xl bg-slate-50 p-3 text-sm dark:bg-slate-950/40"></div>
                    <div class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs font-bold leading-5 text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/25 dark:text-amber-200">
                        Bu işlem onaydan sonra veritabanına kaydedilir ve işlem geçmişine yazılır.
                    </div>
                    <div class="mt-5 grid grid-cols-2 gap-2">
                        <button type="button" data-confirm-cancel class="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm font-black text-slate-700 transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800">Vazgeç</button>
                        <button type="button" data-confirm-approve class="rounded-2xl bg-emerald-600 px-4 py-3 text-sm font-black text-white shadow-lg shadow-emerald-600/20 transition hover:bg-emerald-700">Onayla</button>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
            modal.querySelector('[data-confirm-cancel]').addEventListener('click', () => this.closeConfirmModal());
            modal.addEventListener('click', (event) => {
                if (event.target === modal) this.closeConfirmModal();
            });
            modal.querySelector('[data-confirm-approve]').addEventListener('click', () => this.executeCurrentAction());
            this.confirmModal = modal;
            return modal;
        }

        openConfirmModal() {
            if (!this.canConfirmResult(this.currentResult)) return;
            const modal = this.ensureConfirmModal();
            modal.querySelector('[data-confirm-title]').textContent = this.confirmationTitle();
            modal.querySelector('[data-confirm-message]').textContent = this.confirmationMessage();
            const detailFields = this.confirmationFields();
            const detailRows = detailFields.filter((field) => {
                const label = Array.isArray(field) ? field[0] : field.label;
                return label !== 'Durum';
            }).map((field) => {
                const label = Array.isArray(field) ? field[0] : field.label;
                const value = Array.isArray(field) ? field[1] : field.value;
                return `
                    <div class="flex items-center justify-between gap-3 rounded-2xl bg-white px-3 py-2 dark:bg-slate-900">
                        <span class="text-xs font-black uppercase tracking-wide text-slate-400">${escapeHtml(label)}</span>
                        <span class="text-right text-sm font-black text-slate-900 dark:text-white">${escapeHtml(value)}</span>
                    </div>
                `;
            }).join('');
            modal.querySelector('[data-confirm-details]').innerHTML = detailRows;
            modal.classList.remove('hidden');
            modal.classList.add('flex');
        }

        closeConfirmModal() {
            if (!this.confirmModal) return;
            this.confirmModal.classList.add('hidden');
            this.confirmModal.classList.remove('flex');
        }

        async executeCurrentAction() {
            if (!this.canConfirmResult(this.currentResult)) return;
            const approveButton = this.confirmModal ? this.confirmModal.querySelector('[data-confirm-approve]') : null;
            if (approveButton) {
                approveButton.disabled = true;
                approveButton.classList.add('opacity-70', 'cursor-wait');
                approveButton.textContent = 'Kaydediliyor...';
            }
            try {
                const response = await fetch('/api/assistant/execute', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({
                        command: this.input.value || '',
                        selected_candidate_id: this.selectedCandidate ? this.selectedCandidate.id : null
                    })
                });
                const payload = await response.json();
                if (!response.ok || !payload.success) {
                    throw new Error(payload.message || 'İşlem tamamlanamadı.');
                }
                this.closeConfirmModal();
                if (window.showToast) window.showToast(payload.message || 'İşlem kaydedildi.', 'success', 4500);
                this.renderExecutionSuccess(payload);
            } catch (error) {
                if (window.showToast) window.showToast(error.message || 'İşlem tamamlanamadı.', 'error', 5000);
            } finally {
                if (approveButton) {
                    approveButton.disabled = false;
                    approveButton.classList.remove('opacity-70', 'cursor-wait');
                    approveButton.textContent = 'Onayla';
                }
            }
        }

        renderExecutionSuccess(payload) {
            this.result.innerHTML = `
                <div class="space-y-3">
                    <div class="rounded-3xl border border-emerald-200 bg-emerald-50 p-4 text-emerald-800 dark:border-emerald-900/40 dark:bg-emerald-950/25 dark:text-emerald-200">
                        <div class="flex items-start gap-3">
                            <span class="material-symbols-outlined rounded-2xl bg-white/80 p-2 text-emerald-600 dark:bg-slate-900/70 dark:text-emerald-300">check_circle</span>
                            <div>
                                <p class="font-black">İşlem kaydedildi</p>
                                <p class="mt-1 text-sm font-semibold leading-6">${escapeHtml(payload.message || 'Para hareketi başarıyla kaydedildi.')}</p>
                            </div>
                        </div>
                    </div>
                    <a href="${escapeHtml(this.safeInternalRoute(payload.redirect_url || '/onmuhasebe/hesaplar'))}" class="flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-950 px-4 py-3 text-sm font-black text-white transition hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100">
                        <span class="material-symbols-outlined text-lg">open_in_new</span>
                        İlgili ekrana git
                    </a>
                </div>
            `;
        }

        canConfirmResult(result) {
            if (!result) return false;
            if (result.intent === 'cash_movement') return Boolean(result.executable && result.draftReady);
            if (result.intent === 'collection' || result.intent === 'stock_in') {
                return Boolean(result.draftReady && (!result.requiresMatch || this.selectedCandidate || (result.candidates || []).length === 1));
            }
            return false;
        }

        confirmationTitle() {
            if (!this.currentResult) return 'İşlemi onayla';
            if (this.currentResult.intent === 'collection') return 'Tahsilatı onayla';
            if (this.currentResult.intent === 'stock_in') return 'Stok girişini onayla';
            return this.currentResult.confirmationTitle || 'İşlemi onayla';
        }

        confirmationMessage() {
            if (!this.currentResult) return '';
            if (this.currentResult.intent === 'collection') {
                const candidate = this.selectedCandidate || ((this.currentResult.candidates || []).length === 1 ? this.currentResult.candidates[0] : null);
                const amount = assistantResultField(this.currentResult, 'Tutar') || 'Belirtilen tutar';
                return `${candidate ? candidate.label : 'Seçili cari'} için ${amount} tahsilat kaydedilecek.`;
            }
            if (this.currentResult.intent === 'stock_in') {
                const candidate = this.selectedCandidate || ((this.currentResult.candidates || []).length === 1 ? this.currentResult.candidates[0] : null);
                const quantity = assistantResultField(this.currentResult, 'Miktar') || 'Belirtilen miktar';
                return `${candidate ? candidate.label : 'Seçili ürün'} stoğuna ${quantity} giriş kaydedilecek.`;
            }
            return this.currentResult.confirmationMessage || this.currentResult.summary || '';
        }

        confirmationFields() {
            const fields = this.currentResult && Array.isArray(this.currentResult.fields) ? [...this.currentResult.fields] : [];
            if (this.currentResult && this.currentResult.intent === 'collection') {
                const candidate = this.selectedCandidate || ((this.currentResult.candidates || []).length === 1 ? this.currentResult.candidates[0] : null);
                if (candidate) fields.splice(1, 0, ['Seçili Cari', candidate.label]);
            }
            if (this.currentResult && this.currentResult.intent === 'stock_in') {
                const candidate = this.selectedCandidate || ((this.currentResult.candidates || []).length === 1 ? this.currentResult.candidates[0] : null);
                if (candidate) fields.splice(1, 0, ['Seçili Ürün', candidate.label]);
            }
            return fields;
        }

        getActiveProductCandidate() {
            if (!this.currentResult || this.currentResult.candidateType !== 'product') return null;
            if (this.selectedCandidate) return this.selectedCandidate;
            const candidates = this.currentResult.candidates || [];
            return candidates.length === 1 ? candidates[0] : null;
        }

        renderPosDraftButton(result) {
            if (!result || result.intent !== 'pos_sale') return '';
            const product = this.getActiveProductCandidate();
            const quantity = parseQuantityValue(assistantResultField(result, 'Miktar'));
            const canTransfer = Boolean(result.draftReady && product && quantity > 0);
            return `
                <div class="rounded-3xl border border-blue-100 bg-blue-50/70 p-3 dark:border-blue-900/40 dark:bg-blue-950/20">
                    <div class="flex items-start gap-3">
                        <span class="material-symbols-outlined rounded-2xl bg-white p-2 text-blue-600 dark:bg-slate-900 dark:text-blue-300">point_of_sale</span>
                        <div class="min-w-0 flex-1">
                            <p class="text-xs font-black uppercase tracking-[0.14em] text-blue-500 dark:text-blue-300">POS Sepet Hazırlığı</p>
                            <p class="mt-1 text-sm font-bold leading-5 text-slate-700 dark:text-slate-200">
                                ${canTransfer
                                    ? `${escapeHtml(product.label)} ürünü ${escapeHtml(quantity)} adet POS sepetine eklenecek. Satışı kullanıcı tamamlar.`
                                    : 'POS sepetine aktarım için ürün eşleşmesi ve miktar net olmalı.'}
                            </p>
                        </div>
                    </div>
                    <button type="button" data-assistant-pos-draft="1" ${canTransfer ? '' : 'disabled'} class="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl px-4 py-3 text-sm font-black transition ${canTransfer ? 'bg-slate-950 text-white hover:bg-slate-800 dark:bg-white dark:text-slate-950 dark:hover:bg-slate-100' : 'cursor-not-allowed bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400'}">
                        <span class="material-symbols-outlined text-lg">shopping_cart_checkout</span>
                        POS’a Aktar ve Beklet
                    </button>
                </div>
            `;
        }

        preparePosDraft() {
            const product = this.getActiveProductCandidate();
            if (!this.currentResult || this.currentResult.intent !== 'pos_sale' || !product) {
                if (window.showToast) window.showToast('POS için önce doğru ürünü seçin.', 'warning', 4000);
                return;
            }
            const quantity = parseQuantityValue(assistantResultField(this.currentResult, 'Miktar'));
            if (!quantity || quantity <= 0) {
                if (window.showToast) window.showToast('POS aktarımı için geçerli miktar gerekli.', 'warning', 4000);
                return;
            }
            const draft = {
                source: 'assistant',
                productId: String(product.id),
                productName: product.label || assistantResultField(this.currentResult, 'Ürün') || '',
                quantity,
                command: this.input.value || '',
                createdAt: new Date().toISOString()
            };
            try {
                localStorage.setItem('esstokAssistantPosDraft', JSON.stringify(draft));
            } catch (error) {
                if (window.showToast) window.showToast('POS taslağı hazırlanamadı.', 'error', 4500);
                return;
            }
            if (window.showToast) window.showToast('POS açılıyor; ürün sepete hazırlanacak.', 'success', 2500);
            window.location.href = '/pos?assistant=pos_draft';
        }

        loadHistory() {
            try {
                const parsed = JSON.parse(localStorage.getItem(this.historyKey) || '[]');
                return Array.isArray(parsed) ? parsed.filter(Boolean).slice(0, 5) : [];
            } catch (error) {
                return [];
            }
        }

        saveHistory(command) {
            const value = String(command || '').trim();
            if (!value) return;
            this.history = [value]
                .concat(this.history.filter((item) => item !== value))
                .slice(0, 5);
            try {
                localStorage.setItem(this.historyKey, JSON.stringify(this.history));
            } catch (error) {
                console.warn('Asistan komut geçmişi kaydedilemedi:', error);
            }
        }

        useHistory(index) {
            if (index === -101) {
                this.input.value = 'POS satışı nasıl yapılır?';
                this.analyze();
                return;
            }
            if (index === -102) {
                this.input.value = 'Cari hesap nasıl takip edilir?';
                this.analyze();
                return;
            }
            const command = this.history[index];
            if (!command) return;
            this.input.value = command;
            this.analyze();
        }

        renderHistory() {
            if (!this.history.length) return '';
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Son Komutlar</p>
                        <span class="rounded-full bg-slate-100 px-2.5 py-1 text-[11px] font-black text-slate-500 dark:bg-slate-800 dark:text-slate-300">Bu cihaz</span>
                    </div>
                    <div class="flex flex-wrap gap-2">
                        ${this.history.map((item, index) => `
                            <button type="button" data-assistant-history-index="${index}" class="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-left text-xs font-bold text-slate-600 transition hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-primary-900/60 dark:hover:bg-primary-950/20 dark:hover:text-primary-300">
                                ${escapeHtml(item)}
                            </button>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        renderReadiness(result) {
            const missing = result.missingFields || [];
            const matchNeeded = result.requiresMatch && !this.selectedCandidate;
            const ready = result.draftReady && !matchNeeded;
            const statusClass = ready
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300';
            const items = [];
            if (missing.length) {
                missing.forEach((field) => items.push(`Eksik alan: ${field}`));
            }
            if (matchNeeded) {
                items.push(result.candidateType === 'product' ? 'Ürün eşleşmesi seçilmeli' : 'Cari eşleşmesi seçilmeli');
            }
            if (!items.length) {
                items.push('Taslak analiz için yeterli görünüyor');
            }
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Taslak Kontrolü</p>
                        <span class="rounded-full px-2.5 py-1 text-[11px] font-black ${statusClass}">${ready ? 'Hazır' : 'Kontrol Gerekli'}</span>
                    </div>
                    <div class="space-y-1.5">
                        ${items.map((item) => `
                            <div class="flex items-center gap-2 text-xs font-bold text-slate-600 dark:text-slate-300">
                                <span class="material-symbols-outlined text-base ${ready ? 'text-emerald-500' : 'text-amber-500'}">${ready ? 'check_circle' : 'info'}</span>
                                ${escapeHtml(item)}
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        renderCandidates(result) {
            if (!result.matchStatus && (!result.candidates || !result.candidates.length)) return '';
            const title = result.candidateType === 'product'
                ? 'Olası ürün eşleşmeleri'
                : (result.candidateType === 'cari' ? 'Olası cari eşleşmeleri' : 'Eşleşme durumu');
            const statusClass = result.candidates && result.candidates.length
                ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300'
                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300';
            const items = (result.candidates || []).map((candidate, index) => {
                const isSelected = this.selectedCandidate && String(this.selectedCandidate.id) === String(candidate.id);
                return `
                <button type="button" data-assistant-candidate-index="${index}" class="w-full rounded-2xl border ${isSelected ? 'border-primary-300 bg-primary-50 ring-2 ring-primary-500/10 dark:border-primary-800 dark:bg-primary-950/20' : 'border-slate-200 bg-white hover:border-primary-200 hover:bg-blue-50/50 dark:border-slate-800 dark:bg-slate-900 dark:hover:border-primary-900/60 dark:hover:bg-primary-950/10'} px-3 py-2 text-left transition">
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <p class="truncate text-sm font-black text-slate-900 dark:text-white">${escapeHtml(candidate.label)}</p>
                            <p class="mt-0.5 truncate text-xs font-semibold text-slate-500 dark:text-slate-400">${escapeHtml(candidate.subtitle)}</p>
                        </div>
                        <div class="flex shrink-0 items-center gap-2">
                            ${candidate.meta ? `<span class="rounded-full bg-slate-100 px-2 py-1 text-[10px] font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-300">${escapeHtml(candidate.meta)}</span>` : ''}
                            <span class="material-symbols-outlined text-base ${isSelected ? 'text-primary-600' : 'text-slate-300'}">${isSelected ? 'check_circle' : 'radio_button_unchecked'}</span>
                        </div>
                    </div>
                </button>
            `;
            }).join('');
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="mb-2 flex items-center justify-between gap-3">
                        <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">${title}</p>
                        <span class="rounded-full px-2.5 py-1 text-[11px] font-black ${statusClass}">${escapeHtml(result.matchStatus || 'Kontrol')}</span>
                    </div>
                    ${items || '<p class="text-xs font-semibold leading-5 text-slate-500 dark:text-slate-400">Bu komuta uygun kayıt bulunamadı. Daha net ürün/cari adı yazılırsa eşleşme güçlenir.</p>'}
                </div>
            `;
        }

        renderSelectedCandidate() {
            if (!this.selectedCandidate) return '';
            return `
                <div class="rounded-3xl border border-primary-100 bg-gradient-to-r from-primary-50 to-cyan-50 p-3 dark:border-primary-900/40 dark:from-primary-950/25 dark:to-cyan-950/20">
                    <p class="text-xs font-black uppercase tracking-[0.14em] text-primary-600 dark:text-primary-300">Seçili kayıt</p>
                    <div class="mt-2 flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <p class="truncate text-sm font-black text-slate-950 dark:text-white">${escapeHtml(this.selectedCandidate.label)}</p>
                            <p class="mt-0.5 truncate text-xs font-semibold text-slate-600 dark:text-slate-300">${escapeHtml(this.selectedCandidate.subtitle)}</p>
                        </div>
                        <span class="material-symbols-outlined shrink-0 text-primary-600 dark:text-primary-300">verified</span>
                    </div>
                </div>
            `;
        }

        renderActionPreview(result) {
            if (!result || result.intent === 'unknown') return '';
            const isReady = (result.draftReady && (!result.requiresMatch || Boolean(this.selectedCandidate)));
            const safeRoute = this.safeInternalRoute(result.routeHint);
            const routeButton = result.routeHint ? `
                <a href="${escapeHtml(safeRoute)}" class="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-2xl border border-primary-100 bg-primary-50 px-3 py-2 text-xs font-black text-primary-700 transition hover:bg-primary-100 dark:border-primary-900/40 dark:bg-primary-950/25 dark:text-primary-300">
                    <span class="material-symbols-outlined text-base">open_in_new</span>
                    Ekrana Git
                </a>
            ` : '';
            return `
                <div class="rounded-3xl border border-slate-200 bg-white/80 p-3 dark:border-slate-800 dark:bg-slate-950/30">
                    <div class="flex items-center justify-between gap-3">
                        <div>
                            <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Sonraki Faz Önizlemesi</p>
                            <p class="mt-1 text-sm font-bold text-slate-700 dark:text-slate-200">${isReady ? 'Bu taslak ileride onay kartına dönüşebilir.' : 'Önce doğru kayıt seçilmelidir.'}</p>
                        </div>
                        <div class="flex shrink-0 flex-col gap-2 sm:flex-row">
                            ${routeButton}
                            <button type="button" disabled class="rounded-2xl bg-slate-200 px-3 py-2 text-xs font-black text-slate-500 opacity-70 dark:bg-slate-800 dark:text-slate-400">
                                Onayla Pasif
                            </button>
                        </div>
                    </div>
                </div>
            `;
        }

        safeInternalRoute(route) {
            const value = String(route || '').trim();
            if (!value.startsWith('/') || value.startsWith('//')) return '#';
            return value;
        }

        startListening() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                if (window.showToast) {
                    window.showToast('Bu tarayıcı sesli komutu desteklemiyor. Şimdilik komutu yazarak analiz edebilirsin.', 'warning', 5000);
                }
                return;
            }
            this.recognition = new SpeechRecognition();
            this.recognition.lang = 'tr-TR';
            this.recognition.interimResults = false;
            this.recognition.maxAlternatives = 1;
            if (this.listening) this.listening.classList.remove('hidden');
            if (this.micButton) this.micButton.classList.add('animate-pulse');
            this.recognition.onresult = (event) => {
                const transcript = event.results && event.results[0] && event.results[0][0] ? event.results[0][0].transcript : '';
                if (transcript) this.input.value = transcript;
                this.analyze();
            };
            this.recognition.onerror = () => {
                if (window.showToast) window.showToast('Ses alınamadı. Tekrar deneyin veya komutu yazarak analiz edin.', 'warning', 4500);
            };
            this.recognition.onend = () => {
                if (this.listening) this.listening.classList.add('hidden');
                if (this.micButton) this.micButton.classList.remove('animate-pulse');
            };
            this.recognition.start();
        }
    }

    window.AssistantPanel = AssistantPanel;
    window.EsstokAssistantParser = { analyzeCommand };

    document.addEventListener('DOMContentLoaded', () => {
        const assistant = new AssistantPanel();
        assistant.init();
    });
})();
