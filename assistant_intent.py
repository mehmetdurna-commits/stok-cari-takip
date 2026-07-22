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

        extended_result = self._extended_intent_result(text, amount)
        if extended_result:
            return extended_result

        if self._is_cash_movement(text):
            return self._cash_movement_result(text, amount)

        if self._is_today_summary(text):
            return self._result(
                intent='today_summary',
                title='Bugün ne oldu?',
                confidence='Yüksek',
                summary='Bugünün işletme özeti hazırlanıyor.',
                fields=[
                    ('İşlem Türü', 'İşletme Özeti'),
                    ('Dönem', 'Bugün'),
                    ('Durum', 'Bilgi'),
                ],
                route_hint='/dashboard',
                note='Bu cevap sadece bilgi verir; kullanıcı onayı olmadan işlem yapılmaz.',
            )

        if self._is_receivables_overview(text):
            return self._result(
                intent='receivables_overview',
                title='Müşteri alacakları',
                confidence='Yüksek',
                summary='Müşterilerden alınacak açık bakiyeler hazırlanıyor.',
                fields=[
                    ('İşlem Türü', 'Bilgi Sorgusu'),
                    ('Konu', 'Müşteri Alacakları'),
                    ('Durum', 'Bilgi'),
                ],
                route_hint='/cariler',
                note='Bu ekran yalnızca mevcut cari bakiyeleri özetler; herhangi bir kayıt değiştirilmez.',
            )

        if self._is_account_overview(text):
            return self._result(
                intent='account_overview',
                title='Para hesapları özeti',
                confidence='Yüksek',
                summary='Kasa, banka ve POS hesaplarının güncel durumu hazırlanıyor.',
                fields=[
                    ('İşlem Türü', 'Bilgi Sorgusu'),
                    ('Konu', 'Para Hesapları'),
                    ('Durum', 'Bilgi'),
                ],
                route_hint='/onmuhasebe/hesaplar',
                note='POS bakiyesi bankaya aktarılmayı bekleyen tutardır; kullanılabilir kasa ve banka toplamından ayrı gösterilir.',
            )

        if self._is_business_priorities(text):
            return self._result(
                intent='business_priorities',
                title='İşletme öncelikleri',
                confidence='Yüksek',
                summary='Dikkat gerektiren işletme kayıtları önem sırasına göre hazırlanıyor.',
                fields=[
                    ('İşlem Türü', 'Kontrol Sorgusu'),
                    ('Konu', 'Günün Öncelikleri'),
                    ('Durum', 'Bilgi'),
                ],
                route_hint='/dashboard',
                note='Bu liste yalnızca karar desteği sağlar; herhangi bir kayıt otomatik değiştirilmez.',
            )

        if self._is_product_lookup(text):
            product = self._clean_product_query(text)
            return self._result(
                intent='product_lookup',
                title='Ürün bilgisi',
                confidence='Yüksek' if product else 'Orta',
                summary=f'{product or "Seçilecek ürün"} için stok ve fiyat bilgileri aranıyor.',
                fields=[
                    ('İşlem Türü', 'Ürün Bilgi Sorgusu'),
                    ('Ürün', product or 'Eksik'),
                    ('Durum', 'Bilgi'),
                ],
                route_hint='/urunler',
                note='Bu sorgu ürün bilgilerini gösterir; stok veya fiyat kaydı değiştirilmez.',
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
                note='Ürün eşleşmesini seçip onay verirseniz stok miktarı artırılır.',
                action={
                    'type': 'stock_in',
                    'amount': amount.get('value') if amount else None,
                    'warehouse': 'Ana Depo',
                    'description': 'Esstok Konuş stok girişi',
                },
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
                note='Cari eşleşmesini seçip onay verirseniz tahsilat kaydı oluşturulur.',
                action={
                    'type': 'cari_collection',
                    'amount': amount.get('value') if amount else None,
                    'payment_method': 'Nakit',
                    'description': 'Esstok Konuş tahsilat kaydı',
                },
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

        return self._result(**self._fallback_answer(text))

    def _extended_intent_result(self, text, amount):
        """Recognize specific high-value workflows before broad legacy rules."""
        amount_label = self._format_amount(amount, 'TL')
        quantity_label = self._format_amount(amount, 'adet')
        safe_note = 'Bu işlem yalnızca taslak olarak hazırlanır; kullanıcı onayı olmadan kayıt değiştirilmez.'

        def draft(intent, title, summary, fields, route_hint, confidence='Yüksek', note=safe_note):
            return self._result(
                intent=intent,
                title=title,
                confidence=confidence,
                summary=summary,
                fields=[*fields, ('Durum', 'Onay Bekliyor')],
                route_hint=route_hint,
                note=note,
            )

        if self._contains_any(text, ('fişini tekrar yazdır', 'fisini tekrar yazdir', 'fişi yeniden yazdır', 'fisi yeniden yazdir')):
            return draft('receipt_reprint', 'Fişi tekrar yazdır', 'Son satış fişi yeniden yazdırılmak üzere hazırlandı.', [('İşlem Türü', 'Fiş Yazdırma'), ('Satış', 'Son Satış')], '/gunluk-satislar')

        if 'irsaliye' in text and self._contains_any(text, ('hazırla', 'hazirla', 'oluştur', 'olustur', 'yazdır', 'yazdir')):
            return draft('dispatch_note', 'İrsaliye hazırlama taslağı', 'İlgili satış için irsaliye hazırlama adımı açılacak.', [('İşlem Türü', 'İrsaliye Hazırla'), ('Satış', 'Son Satış' if 'son' in text else 'Seçilecek Satış')], '/gunluk-satislar')

        if 'teklif' in text and self._contains_any(text, ('satışa çevir', 'satisa cevir', 'satış yap', 'satis yap')):
            cari = self._clean_special_entity(text, ('son', 'teklifini', 'teklifi', 'satışa', 'satisa', 'çevir', 'cevir'))
            return draft('quote_to_sale', 'Teklifi satışa çevir', f'{cari or "Seçilecek cari"} için teklif satışa dönüştürülmek üzere hazırlandı.', [('İşlem Türü', 'Teklifi Satışa Çevir'), ('Cari', cari or 'Eksik'), ('Teklif', 'Son Teklif')], '/teklifler')

        if self._contains_any(text, ('aktar', 'transfer')) and self._contains_any(text, ('pos', 'kasa', 'banka')):
            source = self._account_name(text, source=True)
            target = self._account_name(text, source=False)
            return draft('account_transfer', 'Hesaplar arası aktarım taslağı', f'{source or "Kaynak hesap"} hesabından {target or "hedef hesaba"} {amount_label} aktarım hazırlanıyor.', [('İşlem Türü', 'Hesaplar Arası Aktarım'), ('Kaynak Hesap', source or 'Eksik'), ('Hedef Hesap', target or 'Eksik'), ('Tutar', amount_label)], '/onmuhasebe/hesaplar')

        if self._contains_any(text, ('depodan', 'depo')) and self._contains_any(text, ('mağazaya', 'magazaya', 'depoya')) and self._contains_any(text, ('aktar', 'transfer')):
            product = self._clean_special_entity(text, ('ana', 'depodan', 'depo', 'mağazaya', 'magazaya', 'depoya', 'aktar', 'transfer'))
            return draft('warehouse_transfer', 'Depolar arası stok aktarımı', f'{product or "Seçilecek ürün"} için depolar arası aktarım taslağı hazırlandı.', [('İşlem Türü', 'Depolar Arası Aktarım'), ('Ürün', product or 'Eksik'), ('Miktar', quantity_label)], '/stok/cikis')

        if self._contains_any(text, ('satışı iptal', 'satisi iptal', 'satış iptal', 'satis iptal', 'satışı iade', 'satisi iade')):
            return draft('sale_cancel_return', 'Satış iptal/iade taslağı', 'Satışın stok, cari ve ödeme etkileri kontrol edilerek iptal/iade akışı hazırlanacak.', [('İşlem Türü', 'Satış İptali / İade'), ('Satış', 'Son Satış' if 'son' in text else 'Seçilecek Satış')], '/iade')

        if self._contains_any(text, ('yeni ürün', 'yeni urun')) and self._contains_any(text, ('oluştur', 'olustur', 'ekle', 'aç', 'ac')):
            product = self._clean_special_entity(text, ('adında', 'adinda', 'yeni', 'ürün', 'urun', 'oluştur', 'olustur', 'ekle', 'aç', 'ac'))
            return draft('product_create', 'Yeni ürün kartı taslağı', f'{product or "Yeni ürün"} için ürün kartı hazırlanıyor.', [('İşlem Türü', 'Ürün Oluştur'), ('Ürün', product or 'Eksik')], '/urun-ekle')

        if 'fiyat' in text and self._contains_any(text, ('yap', 'güncelle', 'guncelle', 'değiştir', 'degistir')):
            price_type = 'Alış Fiyatı' if self._contains_any(text, ('alış', 'alis')) else 'Satış Fiyatı'
            product = self._clean_special_entity(text, ('alış', 'alis', 'satış', 'satis', 'fiyatını', 'fiyatini', 'fiyatı', 'fiyati', 'fiyat', 'yap', 'güncelle', 'guncelle', 'değiştir', 'degistir'))
            return draft('price_update', 'Ürün fiyatı güncelleme taslağı', f'{product or "Seçilecek ürün"} için {price_type.lower()} güncellemesi hazırlanıyor.', [('İşlem Türü', 'Fiyat Güncelle'), ('Ürün', product or 'Eksik'), ('Fiyat Türü', price_type), ('Yeni Fiyat', amount_label)], '/urunler')

        if self._contains_any(text, ('avans', 'prim', 'izin')) and self._contains_any(text, ('yaz', 'ekle', 'gir', 'oluştur', 'olustur')):
            operation = 'Avans' if 'avans' in text else ('Prim' if 'prim' in text else 'İzin')
            employee = self._clean_special_entity(text, ('avans', 'prim', 'izin', 'yaz', 'ekle', 'gir', 'oluştur', 'olustur'))
            fields = [('İşlem Türü', f'Personel {operation} Kaydı'), ('Personel', employee or 'Eksik')]
            if operation != 'İzin':
                fields.append(('Tutar', amount_label))
            return draft('personnel_action', f'Personel {operation.lower()} taslağı', f'{employee or "Seçilecek personel"} için {operation.lower()} kaydı hazırlanıyor.', fields, '/personel')

        if 'ekstre' in text and self._contains_any(text, ('göster', 'goster', 'hazırla', 'hazirla', 'yazdır', 'yazdir')):
            cari = self._clean_special_entity(text, ('son', 'üç', 'uc', 'aylık', 'aylik', 'ekstresini', 'ekstreyi', 'ekstre', 'göster', 'goster', 'hazırla', 'hazirla', 'yazdır', 'yazdir'))
            return draft('cari_statement', 'Cari ekstre sorgusu', f'{cari or "Seçilecek cari"} için cari hesap dökümü hazırlanıyor.', [('İşlem Türü', 'Cari Ekstre'), ('Cari', cari or 'Eksik'), ('Dönem', 'Son 3 Ay' if self._contains_any(text, ('üç aylık', 'uc aylik', '3 aylık', '3 aylik')) else 'Tümü')], '/cariler')

        if self._contains_any(text, ('stok hareket', 'ürün hareket', 'urun hareket')):
            product = self._clean_special_entity(text, ('stok', 'ürün', 'urun', 'hareketlerini', 'hareketleri', 'hareket', 'göster', 'goster', 'listele'))
            return draft('product_movements', 'Ürün hareketleri sorgusu', f'{product or "Seçilecek ürün"} için stok hareketleri listelenecek.', [('İşlem Türü', 'Stok Hareketleri'), ('Ürün', product or 'Eksik')], '/urunler')

        if self._contains_any(text, ('kırık', 'kirik', 'bozuk', 'fire', 'zayi', 'hasarlı', 'hasarli')) and self._contains_any(text, ('stoktan düş', 'stoktan dus', 'çıkış', 'cikis')):
            product = self._clean_special_entity(text, ('kırık', 'kirik', 'bozuk', 'fire', 'zayi', 'hasarlı', 'hasarli', 'stoktan', 'stok', 'düş', 'dus', 'çıkış', 'cikis'))
            return draft('stock_waste', 'Fire/hasar stok çıkışı', f'{product or "Seçilecek ürün"} için fire stok çıkışı hazırlanıyor.', [('İşlem Türü', 'Fire / Hasar Çıkışı'), ('Ürün', product or 'Eksik'), ('Miktar', quantity_label)], '/stok/cikis')

        if self._contains_any(text, ('ödemesi geciken', 'odemesi geciken', 'gecikmiş alacak', 'gecikmis alacak', 'vadesi geçen', 'vadesi gecen')):
            return draft('overdue_receivables', 'Geciken müşteri alacakları', 'Vadesi geçmiş müşteri bakiyeleri listelenecek.', [('İşlem Türü', 'Geciken Alacak Sorgusu'), ('Filtre', 'Vadesi Geçenler')], '/cariler', note='Bu sorgu yalnızca bilgi verir; hiçbir cari kayıt değiştirilmez.')

        if self._contains_any(text, ('bitmek üzere', 'bitmek uzere', 'tükenmek üzere', 'tukenmek uzere')) and self._contains_any(text, ('ürün', 'urun', 'stok')):
            return draft('critical_stock', 'Kritik stok sorgusu', 'Bitmek üzere olan ürünler kritik stok listesinde gösterilecek.', [('İşlem Türü', 'Bilgi Sorgusu'), ('Filtre', 'Kritik Stok')], '/urunler', note='Bu sorgu yalnızca mevcut stok durumunu gösterir; hiçbir kayıt değiştirilmez.')

        if self._contains_any(text, ('tedarikçilere borc', 'tedarikcilere borc', 'tedarikçi borç', 'tedarikci borc', 'kime borcumuz', 'kimlere borcumuz')):
            return draft('supplier_debts', 'Tedarikçi borçları', 'Açık borcu bulunan tedarikçiler listelenecek.', [('İşlem Türü', 'Tedarikçi Borç Sorgusu'), ('Filtre', 'Açık Borçlar')], '/cariler', note='Bu sorgu yalnızca bilgi verir; hiçbir ödeme kaydı oluşturulmaz.')

        if self._contains_any(text, ('en çok sattığım', 'en cok sattigim', 'en çok satılan', 'en cok satilan', 'satış raporu', 'satis raporu')):
            period = 'Bu Ay' if self._contains_any(text, ('bu ay', 'aylık', 'aylik')) else 'Seçilecek Dönem'
            return draft('report_query', 'Satış raporu sorgusu', f'{period.lower()} için satış performansı hazırlanıyor.', [('İşlem Türü', 'Rapor Sorgusu'), ('Dönem', period), ('Rapor', 'En Çok Satan Ürünler')], '/raporlar', note='Bu sorgu yalnızca rapor üretir; hiçbir kayıt değiştirilmez.')

        if self._contains_any(text, ('kasa durumunu kontrol', 'kasa mutabakat', 'gün sonu', 'gun sonu')):
            return draft('cash_reconciliation', 'Kasa kontrolü', 'Günün kasa giriş, çıkış ve kalan para özeti hazırlanacak.', [('İşlem Türü', 'Kasa Mutabakatı'), ('Dönem', 'Bugün')], '/onmuhasebe/hesaplar', note='Bu kontrol yalnızca mevcut para hareketlerini karşılaştırır; otomatik kayıt oluşturmaz.')

        if self._contains_any(text, ('yapılan satışları göster', 'yapilan satislari goster', 'satışlarını göster', 'satislarini goster')):
            cari = self._clean_special_entity(text, ('bugün', 'bugun', 'yapılan', 'yapilan', 'satışları', 'satislari', 'satışlarını', 'satislarini', 'göster', 'goster'))
            return draft('daily_sales_search', 'Satışlarda cari araması', f'{cari or "Seçilecek cari"} için günlük satış kayıtları aranacak.', [('İşlem Türü', 'Satış Arama'), ('Cari', cari or 'Eksik'), ('Dönem', 'Bugün')], '/gunluk-satislar', note='Bu sorgu yalnızca satış kayıtlarını filtreler; işlem yapmaz.')

        if self._is_supplier_payment(text) and self._contains_any(text, ('bankadan', 'kasadan', 'tedarikçi', 'tedarikci', 'ticaret')):
            supplier = self._clean_special_entity(text, ('bankadan', 'kasadan', 'banka', 'kasa', 'öde', 'ode', 'ödeme', 'odeme', 'yap', 'tedarikçiye', 'tedarikciye'))
            return draft('supplier_payment', 'Tedarikçiye ödeme taslağı', f'{supplier or "Seçilecek tedarikçi"} için ödeme taslağı hazırlandı.', [('İşlem Türü', 'Tedarikçiye Ödeme'), ('Cari', supplier or 'Eksik'), ('Tutar', amount_label)], '/cariler')

        return None

    @staticmethod
    def _contains_any(text, phrases):
        return any(phrase in text for phrase in phrases)

    @staticmethod
    def _account_name(text, source=False):
        suffixes = ('tan', 'dan') if source else ('ya', 'ye', 'a', 'e')
        accounts = (('POS', 'pos'), ('Banka', 'banka'), ('Kasa', 'kasa'))
        for label, word in accounts:
            if any(re.search(rf'\b{word}\s*{suffix}\b', text) for suffix in suffixes):
                return label
        return ''

    @staticmethod
    def _clean_special_entity(text, words):
        cleaned = text or ''
        for word in sorted(words, key=len, reverse=True):
            cleaned = re.sub(rf'\b{re.escape(word)}\b', ' ', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?', ' ', cleaned)
        cleaned = re.sub(r'\b(tl|try|lira|adet|tane|için|icin)\b', ' ', cleaned, flags=re.IGNORECASE)
        return re.sub(r'\s+', ' ', cleaned).strip(' -')

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
            (
                ('şifre', 'sifre', 'parola', 'giriş yapamıyorum', 'giris yapamiyorum'),
                {
                    'intent': 'help_login',
                    'title': 'Giriş ve şifre işlemleri',
                    'confidence': 'Yüksek',
                    'summary': 'Giriş yapamıyorsanız e-posta adresinizi kontrol edin ve Giriş ekranındaki “Şifremi unuttum” bağlantısıyla yeni şifre belirleyin.',
                    'fields': [
                        ('1', 'E-posta adresini kontrol edin'),
                        ('2', 'Şifremi unuttum bağlantısını kullanın'),
                        ('3', 'Gelen e-postadaki bağlantıyla şifreyi yenileyin'),
                    ],
                    'route_hint': '/giris',
                    'note': 'Şifre sıfırlama e-postası gelmezse spam klasörünü kontrol edin veya destek talebi açın.',
                },
            ),
            (
                ('iade', 'ürün iadesi', 'urun iadesi'),
                {
                    'intent': 'help_return',
                    'title': 'İade işlemi nasıl yapılır?',
                    'confidence': 'Yüksek',
                    'summary': 'İade ekranında ilgili cari ve ürün seçilerek iade türü belirlenir; işlem cari hareketlere ve stok durumuna göre takip edilir.',
                    'fields': [
                        ('Cari', 'İadenin hangi müşteriye ait olduğunu belirtir'),
                        ('Ürün', 'İade edilen ürünü ve miktarı gösterir'),
                        ('İade Türü', 'Para iadesi, cari alacak veya değişim akışını belirler'),
                    ],
                    'route_hint': '/iade',
                    'note': 'İade kaydı oluşturmadan önce ürün ve cari bilgisini kontrol edin.',
                },
            ),
            (
                ('nakit', 'kasa', 'banka', 'pos hesabı', 'pos hesabi', 'para aktar'),
                {
                    'intent': 'help_cash',
                    'title': 'Kasa, banka ve POS nasıl takip edilir?',
                    'confidence': 'Yüksek',
                    'summary': 'Nakit Yönetimi ve Ön Muhasebe hesaplarıyla kasa giriş/çıkışlarını, banka hareketlerini ve POS aktarımını takip edebilirsiniz.',
                    'fields': [
                        ('Kasa', 'Nakit giriş ve çıkışları gösterir'),
                        ('Banka', 'Banka hesabına giren ve çıkan parayı izler'),
                        ('POS', 'Kart satışlarından bekleyen tutarları takip eder'),
                    ],
                    'route_hint': '/onmuhasebe/hesaplar',
                    'note': 'POS tahsilatları bankaya geçtiğinde hesaplar arası aktarım kullanılabilir.',
                },
            ),
            (
                ('paket', 'limit', 'yükselt', 'yukselt', 'lisans', 'fiyat'),
                {
                    'intent': 'help_package',
                    'title': 'Paket ve limit bilgileri',
                    'confidence': 'Yüksek',
                    'summary': 'Demo, Standart ve Profesyonel paketler ürün limiti ve kullanım kapsamına göre ayrılır. Paket yükseltme ekranından talep oluşturabilirsiniz.',
                    'fields': [
                        ('Demo', 'Deneme amaçlı sınırlı kullanım'),
                        ('Standart', 'Belirli ürün limitine kadar kullanım'),
                        ('Profesyonel', 'Sınırsız ürün ve geniş kullanım'),
                    ],
                    'route_hint': '/paket-yukselt',
                    'note': 'Paket yükseltme işlemi ödeme/talep akışına yönlendirir.',
                },
            ),
            (
                ('ayar', 'ayarlar', 'logo', 'firma bilgileri', 'bildirim'),
                {
                    'intent': 'help_settings',
                    'title': 'Firma ayarları nereden yapılır?',
                    'confidence': 'Yüksek',
                    'summary': 'Ayarlar ekranından firma bilgileri, logo, tercihler ve bildirim ayarları yönetilir.',
                    'fields': [
                        ('Firma Bilgileri', 'Ad, adres, telefon ve logo'),
                        ('Tercihler', 'Sayfa ve kullanım tercihleri'),
                        ('Bildirimler', 'Uyarı ve bilgilendirme tercihleri'),
                    ],
                    'route_hint': '/settings',
                    'note': 'Logo ve firma bilgileri teklif, ekstre ve bazı çıktılarda kullanılabilir.',
                },
            ),
            (
                ('personel', 'maaş', 'maas', 'izin', 'avans', 'prim'),
                {
                    'intent': 'help_personnel',
                    'title': 'Personel yönetimi nasıl kullanılır?',
                    'confidence': 'Yüksek',
                    'summary': 'Personel ekranından çalışan listesi, izin, avans, prim ve bordro akışları takip edilir.',
                    'fields': [
                        ('Personel', 'Çalışan kartlarını listeler'),
                        ('İzin', 'Personelin izin durumunu takip eder'),
                        ('Avans / Prim', 'Maaş dışı hareketleri gösterir'),
                    ],
                    'route_hint': '/personel',
                    'note': 'Personel kayıtları düzenli tutulursa bordro ve ödeme listeleri daha sağlıklı hazırlanır.',
                },
            ),
            (
                ('yazdır', 'yazdir', 'fiş', 'fis', 'irsaliye', 'ekstre'),
                {
                    'intent': 'help_print',
                    'title': 'Yazdırma işlemleri nereden yapılır?',
                    'confidence': 'Yüksek',
                    'summary': 'Fiş, irsaliye, teklif ve cari ekstre çıktıları ilgili ekranlarda bulunan yazdırma butonlarıyla alınır.',
                    'fields': [
                        ('Fiş', 'POS veya Günlük Satışlar ekranından yazdırılır'),
                        ('İrsaliye', 'Günlük Satışlar satış satırından alınır'),
                        ('Ekstre', 'Cari detay ekranından yazdırılır'),
                    ],
                    'route_hint': '/gunluk-satislar',
                    'note': 'Yazdırma penceresi açılmazsa tarayıcı pop-up izinlerini kontrol edin.',
                },
            ),
            (
                ('fatura', 'e-fatura', 'efatura', 'entegratör', 'entegrator'),
                {
                    'intent': 'help_invoice',
                    'title': 'Fatura ve entegrasyon durumu',
                    'confidence': 'Yüksek',
                    'summary': 'Esstok’ta satış, teklif, fiş, irsaliye ve cari kayıtları takip edilir. Resmi e-fatura/e-arşiv kesimi için entegratör bağlantısı ayrıca yapılandırılmalıdır.',
                    'fields': [
                        ('Bugün', 'Satış, fiş, irsaliye ve teklif çıktıları kullanılabilir'),
                        ('Entegrasyon', 'Fatura entegratörü bilgileriyle geliştirilebilir'),
                        ('Öneri', 'Canlı fatura kesmeden önce mali müşavir ve entegratör ayarları kontrol edilmelidir'),
                    ],
                    'route_hint': '/teklifler',
                    'note': 'Bu cevap bilgilendirme amaçlıdır; resmi mali belge üretimi için entegratör altyapısı gerekir.',
                },
            ),
        ]
        for keywords, result in help_topics:
            if any(keyword in text for keyword in keywords):
                return result
        return None

    def _cash_movement_result(self, text, amount):
        account_type = 'bank' if any(word in text for word in ('bankadan', 'bankaya', 'banka')) else 'cash'
        is_in = any(word in text for word in ('giriş', 'giris', 'yatır', 'yatir', 'geldi', 'ekle', 'kasaya', 'bankaya'))
        is_out = any(word in text for word in ('çıkış', 'cikis', 'çıkar', 'cikar', 'ödeme', 'odeme', 'öde', 'ode', 'masraf', 'gider', 'harcama', 'kasadan', 'bankadan'))
        movement = 'giris' if is_in and not is_out else 'cikis'
        account_label = 'Banka' if account_type == 'bank' else 'Kasa'
        description = self._clean_cash_description(text) or ('Para girişi' if movement == 'giris' else 'Para çıkışı')
        amount_label = self._format_amount(amount, 'TL')
        return self._result(
            intent='cash_movement',
            title=f'{account_label} {"girişi" if movement == "giris" else "çıkışı"} taslağı',
            confidence='Yüksek' if amount else 'Orta',
            summary=f'{account_label} hesabında {amount_label} {"giriş" if movement == "giris" else "çıkış"} işlemi için onay taslağı hazırlandı.',
            fields=[
                ('İşlem Türü', 'Para Girişi' if movement == 'giris' else 'Para Çıkışı'),
                ('Hesap Türü', account_label),
                ('Tutar', amount_label),
                ('Açıklama', description),
                ('Durum', 'Onay Bekliyor'),
            ],
            route_hint='/onmuhasebe/hesaplar',
            note='Onay verirseniz bu işlem ilgili kasa/banka hesabına kaydedilir.',
            action={
                'type': 'cash_transaction',
                'account_type': account_type,
                'islem_tipi': movement,
                'amount': amount.get('value') if amount else None,
                'description': description,
            },
        )

    @staticmethod
    def _clean_cash_description(text):
        cleaned = re.sub(
            r'\b(kasadan|kasaya|kasa|bankadan|bankaya|banka|para|giriş|girişi|giris|girisi|çıkış|çıkışı|cikis|cikisi|çıkar|cikar|yatır|yatir|ödeme|odeme|öde|ode|yap|kaydet|tl|lira)\b',
            ' ',
            text or '',
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r'\d+(?:[.,]\d+)?', ' ', cleaned)
        return re.sub(r'\s+', ' ', cleaned).strip()

    @staticmethod
    def _fallback_answer(text):
        return {
            'intent': 'help_general',
            'title': 'Size nasıl yardımcı olabilirim?',
            'confidence': 'Orta',
            'summary': 'Bu soruyu tek bir ekrana net bağlayamadım; yine de Esstok içinde stok, cari, POS, teklif, iade, rapor, ayarlar ve personel konularında yardımcı olabilirim.',
            'fields': [
                ('Örnek', '“POS satışı nasıl yapılır?”'),
                ('Örnek', '“Cari hesap nasıl takip edilir?”'),
                ('Örnek', '“Stoğa 100 adet Selpak ekle”'),
                ('Destek', 'Yanıt yeterli olmazsa destek talebi oluşturabilirsiniz'),
            ],
            'route_hint': '/destek',
            'note': 'Bu cevap destek amaçlıdır; kullanıcı onayı olmadan hiçbir işlem yapılmaz.',
        }

    @staticmethod
    def _normalize(value):
        return re.sub(r'\s+', ' ', str(value or '').lower().replace('\u0307', '').replace('’', ' ').replace("'", ' ')).strip()

    @staticmethod
    def _extract_amount(text):
        match = re.search(r'(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(tl|lira|₺|adet|tane)?', text or '', re.IGNORECASE)
        if not match:
            return None
        raw_value = match.group(1)
        if '.' in raw_value and ',' in raw_value:
            raw_value = raw_value.replace('.', '').replace(',', '.')
        elif raw_value.count('.') >= 1 and all(len(part) == 3 for part in raw_value.split('.')[1:]):
            raw_value = raw_value.replace('.', '')
        else:
            raw_value = raw_value.replace(',', '.')
        return {
            'value': float(raw_value),
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
        text = re.sub(r'\b([a-zçğıöşü0-9]+)(dan|den|tan|ten)\b', r'\1', text or '', flags=re.IGNORECASE)
        cleaned = re.sub(
            r'\b(stoğa|stoga|stoktan|stok|ürün|urun|ekle|giriş|girişi|giris|girisi|çıkış|çıkışı|cikis|cikisi|düş|dus|adet|tane|tl|lira|tahsilat|ödeme|odeme|al|yap|sat|satış|satis|pos|listele|göster|goster|bugünkü|bugunku|kritik|borcu|bakiye|kasaya|kasadan|müşteriden|musteriden|tedarikçiye|tedarikciye|teklif|oluştur|olustur|hazırla|hazirla|cari|müşteri|musteri|ne|kadar|nedir|kaç|kac|var|mi|mı|mu|mü|in|ın|un|ün|dan|den|tan|ten)\b',
            ' ',
            text,
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
        return any(word in text for word in ('ödeme', 'odeme', 'öde', 'ode', 'tedarikçi', 'tedarikci'))

    @staticmethod
    def _is_cash_movement(text):
        account_word = any(word in text for word in ('kasa', 'kasadan', 'kasaya', 'banka', 'bankadan', 'bankaya'))
        movement_word = any(word in text for word in ('giriş', 'giris', 'çıkış', 'cikis', 'çıkar', 'cikar', 'yatır', 'yatir', 'masraf', 'gider', 'harcama', 'ödeme', 'odeme', 'öde', 'ode'))
        return account_word and movement_word

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
    def _is_today_summary(text):
        return any(phrase in text for phrase in (
            'bugün ne oldu',
            'bugun ne oldu',
            'bugünkü özet',
            'bugunku ozet',
            'işletme özeti',
            'isletme ozeti',
            'bugün durum',
            'bugun durum',
        ))

    @staticmethod
    def _is_receivables_overview(text):
        return any(phrase in text for phrase in (
            'kimden alacağım var',
            'kimden alacagim var',
            'en çok borcu olan',
            'en cok borcu olan',
            'müşteri borçları',
            'musteri borclari',
            'alacak listesi',
            'açık cari listesi',
            'acik cari listesi',
        ))

    @staticmethod
    def _is_account_overview(text):
        return any(phrase in text for phrase in (
            'param nerede',
            'kasam ne durumda',
            'kasa banka pos durumu',
            'hesap bakiyeleri',
            'para hesapları',
            'para hesaplari',
            'ne kadar param var',
        ))

    @staticmethod
    def _is_business_priorities(text):
        return any(phrase in text for phrase in (
            'bugün neye dikkat etmeliyim',
            'bugun neye dikkat etmeliyim',
            'önceliklerim neler',
            'onceliklerim neler',
            'ne yapmam gerekiyor',
            'işletmede sorun var mı',
            'isletmede sorun var mi',
            'kontrol etmem gerekenler',
        ))

    @staticmethod
    def _is_product_lookup(text):
        return any(phrase in text for phrase in (
            'stokta kaç',
            'stokta kac',
            'kaç tane var',
            'kac tane var',
            'kaç adet var',
            'kac adet var',
            'fiyatı ne',
            'fiyati ne',
            'satış fiyatı',
            'satis fiyati',
            'alış fiyatı',
            'alis fiyati',
            'barkodu ne',
            'ürün bilgisi',
            'urun bilgisi',
            'kritik mi',
        ))

    @staticmethod
    def _clean_product_query(text):
        cleaned = re.sub(
            r'\b(stokta|stok|kaç|kac|tane|adet|var|kaldı|kaldi|fiyatı|fiyati|fiyat|satış|satis|alış|alis|barkodu|barkod|ürün|urun|bilgisi|kritik|mi|mı|mu|mü|ne|nedir|göster|goster|söyle|soyle)\b',
            ' ',
            text or '',
            flags=re.IGNORECASE,
        )
        return re.sub(r'\s+', ' ', cleaned).strip()

    @staticmethod
    def _is_daily_sales(text):
        return any(phrase in text for phrase in ('bugünkü satış', 'bugunku satis', 'günlük satış', 'gunluk satis'))

    @staticmethod
    def _is_critical_stock(text):
        return 'kritik stok' in text or 'azalan stok' in text

    @staticmethod
    def _is_customer_balance(text):
        return any(word in text for word in ('bakiye', 'borcu', 'alacağı', 'alacagi'))
