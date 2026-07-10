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
            r'\b(stoğa|stoga|stoktan|stok|ekle|giriş|giris|çıkış|cikis|düş|dus|adet|tane|tl|lira|tahsilat|ödeme|odeme|al|yap|listele|göster|goster|bugünkü|bugunku|kritik|borcu|bakiye|kasaya|kasadan|müşteriden|musteriden|tedarikçiye|tedarikciye)\b',
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
    def _is_daily_sales(text):
        return any(phrase in text for phrase in ('bugünkü satış', 'bugunku satis', 'günlük satış', 'gunluk satis'))

    @staticmethod
    def _is_critical_stock(text):
        return 'kritik stok' in text or 'azalan stok' in text

    @staticmethod
    def _is_customer_balance(text):
        return any(word in text for word in ('bakiye', 'borcu', 'alacağı', 'alacagi'))
