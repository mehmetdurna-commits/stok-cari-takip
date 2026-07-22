import pytest

from assistant_intent import AssistantCommandAnalyzer


COMMON_COMMANDS = [
    ('Ahmet’e 5 matkap veresiye sat.', 'pos_sale'),
    ('Mehmet’ten 8.000 TL tahsilat al.', 'collection'),
    ('Kasadan 750 TL kargo gideri yaz.', 'cash_movement'),
    ('16 mm matkap stokta kaç tane?', 'product_lookup'),
    ('Ahmet’in bize ne kadar borcu var?', 'customer_balance'),
    ('Stoğa 100 adet Selpak ekle.', 'stock_in'),
    ('Bugün ne oldu?', 'today_summary'),
    ('Demir Ticarete bankadan 15.000 TL öde.', 'supplier_payment'),
    ('Ahmet’e 20 çimento için teklif hazırla.', 'quote'),
    ('Bitmek üzere olan ürünleri göster.', 'critical_stock'),
    ('Param nerede?', 'account_overview'),
    ('POS’tan bankaya 12.000 TL aktar.', 'account_transfer'),
    ('Son satışı iptal et.', 'sale_cancel_return'),
    ('Selpak adında yeni ürün oluştur.', 'product_create'),
    ('Mehmet Yapı adında müşteri oluştur.', 'cari_create'),
    ('Bu ay en çok sattığım ürün hangisi?', 'report_query'),
    ('Matkabın satış fiyatını 2.500 TL yap.', 'price_update'),
    ('Mehmet’e 2.000 TL avans yaz.', 'personnel_action'),
    ('Bugün Ahmet’e yapılan satışları göster.', 'daily_sales_search'),
    ('Son satışın fişini tekrar yazdır.', 'receipt_reprint'),
    ('Son satış için irsaliye hazırla.', 'dispatch_note'),
    ('Ahmet’in son üç aylık ekstresini göster.', 'cari_statement'),
    ('Matkabın stok hareketlerini göster.', 'product_movements'),
    ('3 kırık ampulü stoktan düş.', 'stock_waste'),
    ('Ana depodan mağazaya 20 boya aktar.', 'warehouse_transfer'),
    ('Çimentonun alış fiyatını 180 TL yap.', 'price_update'),
    ('Ödemesi geciken müşteriler kim?', 'overdue_receivables'),
    ('Hangi tedarikçilere borcumuz var?', 'supplier_debts'),
    ('Ahmet’in son teklifini satışa çevir.', 'quote_to_sale'),
    ('Bugünün kasa durumunu kontrol et.', 'cash_reconciliation'),
]


@pytest.mark.parametrize(('command', 'expected_intent'), COMMON_COMMANDS)
def test_common_business_commands_are_classified(command, expected_intent):
    result = AssistantCommandAnalyzer().analyze(command)

    assert result['intent'] == expected_intent
    assert result['title']
    assert result['route_hint']


@pytest.mark.parametrize(
    ('command', 'expected_value'),
    [
        ('Kasadan 750 TL kargo gideri yaz.', 750),
        ('Mehmet’ten 8.000 TL tahsilat al.', 8000),
        ('Matkabın satış fiyatını 2.500,50 TL yap.', 2500.50),
    ],
)
def test_turkish_formatted_amounts_are_parsed(command, expected_value):
    result = AssistantCommandAnalyzer().analyze(command)
    values = {field['label']: field['value'] for field in result['fields']}
    amount_text = values.get('Tutar') or values.get('Yeni Fiyat')

    assert str(expected_value).rstrip('0').rstrip('.') in amount_text


@pytest.mark.parametrize(
    'command',
    [
        'POS’tan bankaya 12.000 TL aktar.',
        'Son satışı iptal et.',
        'Matkabın satış fiyatını 2.500 TL yap.',
        'Mehmet’e 2.000 TL avans yaz.',
        'Ahmet’in son teklifini satışa çevir.',
    ],
)
def test_new_workflows_remain_analysis_only(command):
    result = AssistantCommandAnalyzer().analyze(command)

    assert 'action' not in result

