import re


class AssistantCommandAnalyzer:
    """Keyword-based first pass analyzer for Esstok Konuş.

    This class intentionally does not perform database writes. It only converts
    a free-form Turkish command into a safe draft that can be shown to the user.
    Future OpenAI/local LLM integration can replace or enrich `analyze` while
    keeping the returned contract stable.
    """

    DEFAULT_RESULT = {
        'intent': 'unknown',
        'title': 'Komutu netleştiremedim',
        'confidence': 'Düşük',
        'summary': 'Bu komutu güvenli şekilde işleme çevirmek için biraz daha açık yazman gerekiyor.',
        'fields': [
            {'label': 'İşlem Türü', 'value': 'Belirsiz'},
            {'label': 'Durum', 'value': 'Onay Bekliyor'},
        ],
        'route_hint': '',
        'note': 'Bu sürümde işlem yapılmaz, sadece analiz edilir.',
    }

    def analyze(self, command):
        text = self._normalize(command)
        amount = self._extract_amount(text)

        if not text:
            return self._result(
                summary='Önce bir komut yazmalı veya söylemelisin.',
                fields=[
                    ('İşlem Türü', 'Belirsiz'),
                    ('Durum', 'Komut Bekleniyor'),
                ],
            )

        help_result = self._help_answer(text)
        if help_result:
            return self._result(**help_result)

        if self._is_stock_in(text):
            product = self._clean_entity(text)
            return self._result(
                intent='stock_in',
                title='Stok girişi taslağı',
                confidence='Yüksek' if product and amount else 'Orta',
                summary=f'{product or "Seçilecek ürün"} için stok girişi taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Stok Girişi'),
                    ('Ürün', product or 'Eksik'),
                    ('Miktar', self._format_amount(amount, 'adet')),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/stok/giris',
            )

        if self._is_stock_out(text):
            product = self._clean_entity(text)
            return self._result(
                intent='stock_out',
                title='Stok çıkışı taslağı',
                confidence='Yüksek' if product and amount else 'Orta',
                summary=f'{product or "Seçilecek ürün"} için stok çıkışı taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Stok Çıkışı'),
                    ('Ürün', product or 'Eksik'),
                    ('Miktar', self._format_amount(amount, 'adet')),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/stok/cikis',
            )

        if self._is_collection(text):
            customer = self._clean_entity(text)
            return self._result(
                intent='collection',
                title='Müşteriden tahsilat taslağı',
                confidence='Yüksek' if customer and amount else 'Orta',
                summary=f'{customer or "Seçilecek cari"} için tahsilat taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Müşteriden Tahsilat'),
                    ('Cari', customer or 'Eksik'),
                    ('Tutar', self._format_amount(amount, 'TL')),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/cariler',
            )

        if self._is_supplier_payment(text):
            supplier = self._clean_entity(text)
            return self._result(
                intent='supplier_payment',
                title='Tedarikçiye ödeme taslağı',
                confidence='Yüksek' if supplier and amount else 'Orta',
                summary=f'{supplier or "Seçilecek tedarikçi"} için ödeme taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Tedarikçiye Ödeme'),
                    ('Cari', supplier or 'Eksik'),
                    ('Tutar', self._format_amount(amount, 'TL')),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/cariler',
            )

        if self._is_pos_sale(text):
            product = self._clean_entity(text)
            return self._result(
                intent='pos_sale',
                title='Hızlı satış taslağı',
                confidence='Yüksek' if product and amount else 'Orta',
                summary=f'{product or "Seçilecek ürün"} için POS satış taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Hızlı Satış'),
                    ('Ürün', product or 'Eksik'),
                    ('Miktar', self._format_amount(amount, 'adet')),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/pos',
            )

        if self._is_quote(text):
            customer = self._clean_entity(text)
            return self._result(
                intent='quote',
                title='Teklif oluşturma taslağı',
                confidence='Orta' if customer else 'Düşük',
                summary=f'{customer or "Seçilecek cari"} için teklif oluşturma taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Teklif Oluştur'),
                    ('Cari', customer or 'Eksik'),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/teklif/ekle',
            )

        if self._is_cari_create(text):
            customer = self._clean_entity(text)
            return self._result(
                intent='cari_create',
                title='Cari ekleme taslağı',
                confidence='Orta' if customer else 'Düşük',
                summary=f'{customer or "Yeni cari"} için cari kartı açma taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Cari Ekle'),
                    ('Cari', customer or 'Eksik'),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/cari-ekle',
            )

        if self._is_daily_sales(text):
            return self._result(
                intent='daily_sales',
                title='Günlük satış sorgusu',
                confidence='Yüksek',
                summary='Bugünkü satışlar için sorgu taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Bilgi Sorgusu'),
                    ('Ekran', 'Günlük Satışlar'),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/gunluk-satislar',
            )

        if self._is_critical_stock(text):
            return self._result(
                intent='critical_stock',
                title='Kritik stok sorgusu',
                confidence='Yüksek',
                summary='Kritik stoktaki ürünler için sorgu taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Bilgi Sorgusu'),
                    ('Filtre', 'Kritik Stok'),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/urunler',
            )

        if self._is_customer_balance(text):
            customer = self._clean_entity(text)
            return self._result(
                intent='customer_balance',
                title='Cari bakiye sorgusu',
                confidence='Orta' if customer else 'Düşük',
                summary=f'{customer or "Seçilecek cari"} için bakiye sorgusu taslağı hazırlandı.',
                fields=[
                    ('İşlem Türü', 'Cari Bakiye Sorgusu'),
                    ('Cari', customer or 'Eksik'),
                    ('Durum', 'Onay Bekliyor'),
                ],
                route_hint='/cariler',
            )

        return self._result()

    def _result(self, **overrides):
        result = dict(self.DEFAULT_RESULT)
        result.update(overrides)
        normalized_fields = []
        for field in result.get('fields', []):
            if isinstance(field, tuple):
                label, value = field
                normalized_fields.append({'label': label, 'value': value})
            elif isinstance(field, dict):
                normalized_fields.append(field)
        result['fields'] = normalized_fields
        return result

    @staticmethod
    def _help_answer(text):
        help_topics = [
            (
                ('nasıl satış', 'satis nasil', 'satış nasıl', 'satışı nasıl', 'satisi nasil', 'pos nasıl', 'pos nasil'),
                {
                    'intent': 'help_pos',
                    'title': 'POS satışı nasıl yapılır?',
                    'confidence': 'Yüksek',
                    'summary': 'POS ekranında ürünü barkodla okutun veya arayın, sepete ekleyin, ödeme tipini seçin ve satışı tamamlayın.',
                    'fields': [
                        ('1', 'Ürünü okut veya ara'),
                        ('2', 'Sepeti kontrol et'),
                        ('3', 'Nakit, kart veya veresiye seç'),
                        ('4', 'Satışı tamamla'),
                    ],
                    'route_hint': '/pos',
                    'note': 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.',
                },
            ),
            (
                ('stok nasıl', 'stok nasil', 'ürün nasıl', 'urun nasil'),
                {
                    'intent': 'help_stock',
                    'title': 'Stok nasıl yönetilir?',
                    'confidence': 'Yüksek',
                    'summary': 'Ürün kartlarını Ürünler ekranından açabilir, stok girişlerini Stok Girişi ekranından yapabilirsiniz.',
                    'fields': [
                        ('Ürün Kartı', 'Ürün adı, barkod, fiyat ve kritik stok bilgisi'),
                        ('Stok Girişi', 'Alınan ürün miktarını stoğa ekler'),
                        ('Kritik Stok', 'Azalan ürünleri takip etmeyi kolaylaştırır'),
                    ],
                    'route_hint': '/urunler',
                    'note': 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.',
                },
            ),
            (
                ('cari nasıl', 'cari nasil', 'cari hesap nasıl', 'cari hesap nasil', 'tahsilat nasıl', 'tahsilat nasil', 'müşteri borcu', 'musteri borcu'),
                {
                    'intent': 'help_cari',
                    'title': 'Cari hesap nasıl takip edilir?',
                    'confidence': 'Yüksek',
                    'summary': 'Cariler ekranında müşteri ve tedarikçileri takip eder, tahsilat ve ödeme hareketlerini kayıt altına alırsınız.',
                    'fields': [
                        ('Müşteri', 'Veresiye satış sonrası borç oluşur'),
                        ('Tahsilat', 'Müşteri borcunu azaltır'),
                        ('Ekstre', 'Tüm cari hareketleri tarih sırasıyla gösterir'),
                    ],
                    'route_hint': '/cariler',
                    'note': 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.',
                },
            ),
            (
                ('teklif nasıl', 'teklif nasil'),
                {
                    'intent': 'help_quote',
                    'title': 'Teklif nasıl hazırlanır?',
                    'confidence': 'Yüksek',
                    'summary': 'Teklifler ekranından cari seçip ürün kalemlerini eklersiniz; ardından yazdırılabilir teklif çıktısı alabilirsiniz.',
                    'fields': [
                        ('1', 'Cari seç'),
                        ('2', 'Ürün kalemlerini ekle'),
                        ('3', 'KDV ve geçerlilik bilgilerini kontrol et'),
                        ('4', 'Teklifi yazdır veya kaydet'),
                    ],
                    'route_hint': '/teklifler',
                    'note': 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.',
                },
            ),
            (
                ('rapor', 'bugün ne oldu', 'bugun ne oldu', 'özet', 'ozet'),
                {
                    'intent': 'help_reports',
                    'title': 'İşletme özeti nereden görülür?',
                    'confidence': 'Yüksek',
                    'summary': 'Ana Panel ve Raporlar ekranları satış, stok ve cari durumunu hızlıca görmeniz için hazırlanmıştır.',
                    'fields': [
                        ('Ana Panel', 'Güncel işletme durumunu gösterir'),
                        ('Raporlar', 'Satış, stok ve cari özetlerini derler'),
                    ],
                    'route_hint': '/dashboard',
                    'note': 'Bu cevap bilgilendirme amaçlıdır; işlem yapılmaz.',
                },
            ),
        ]
        for keywords, result in help_topics:
            if any(keyword in text for keyword in keywords):
                return result
        return None

    @staticmethod
    def _normalize(value):
        return re.sub(r'\s+', ' ', str(value or '').lower().replace('’', ' ').replace("'", ' ')).strip()

    @staticmethod
    def _extract_amount(text):
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*(tl|lira|₺|adet|tane)?', text or '', re.IGNORECASE)
        if not match:
            return None
        return {
            'value': float(match.group(1).replace(',', '.')),
            'unit': match.group(2) or '',
        }

    @staticmethod
    def _format_amount(amount, fallback_unit):
        if not amount:
            return 'Eksik'
        value = amount.get('value')
        if value == int(value):
            value = int(value)
        unit = fallback_unit or amount.get('unit') or ''
        return f'{value} {unit}'.strip()

    @staticmethod
    def _clean_entity(text):
        cleaned = re.sub(
            r'\b(stoğa|stoga|stoktan|stok|ürün|urun|ekle|giriş|giris|çıkış|cikis|düş|dus|adet|tane|tl|lira|tahsilat|ödeme|odeme|al|yap|sat|satış|satis|pos|listele|göster|goster|bugünkü|bugunku|kritik|borcu|bakiye|kasaya|kasadan|müşteriden|musteriden|tedarikçiye|tedarikciye|teklif|oluştur|olustur|hazırla|hazirla|cari|müşteri|musteri)\b',
            ' ',
            text or '',
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r'\d+(?:[.,]\d+)?', ' ', cleaned)
        return re.sub(r'\s+', ' ', cleaned).strip()

    @staticmethod
    def _is_stock_in(text):
        return ('stoğa' in text or 'stoga' in text or 'stok' in text) and any(word in text for word in ('ekle', 'giriş', 'giris'))

    @staticmethod
    def _is_stock_out(text):
        return ('stoktan' in text or 'stok' in text) and any(word in text for word in ('düş', 'dus', 'çıkış', 'cikis'))

    @staticmethod
    def _is_collection(text):
        return 'tahsilat' in text or ('müşteri' in text and 'al' in text)

    @staticmethod
    def _is_supplier_payment(text):
        return any(word in text for word in ('ödeme', 'odeme', 'tedarikçi', 'tedarikci'))

    @staticmethod
    def _is_pos_sale(text):
        if any(word in text for word in ('göster', 'goster', 'listele', 'bugünkü', 'bugunku', 'günlük', 'gunluk')):
            return False
        return any(word in text for word in ('satış', 'satis', 'sat ', ' pos')) or ('sat' in text and 'tahsilat' not in text)

    @staticmethod
    def _is_quote(text):
        return 'teklif' in text and any(word in text for word in ('oluştur', 'olustur', 'hazırla', 'hazirla', 'aç', 'ac'))

    @staticmethod
    def _is_cari_create(text):
        return ('cari' in text or 'müşteri' in text or 'musteri' in text) and any(word in text for word in ('ekle', 'oluştur', 'olustur', 'aç', 'ac'))

    @staticmethod
    def _is_daily_sales(text):
        return any(phrase in text for phrase in ('bugünkü satış', 'bugunku satis', 'günlük satış', 'gunluk satis'))

    @staticmethod
    def _is_critical_stock(text):
        return 'kritik stok' in text or 'azalan stok' in text

    @staticmethod
    def _is_customer_balance(text):
        return any(word in text for word in ('bakiye', 'borcu', 'alacağı', 'alacagi'))
