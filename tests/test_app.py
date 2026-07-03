import pytest
import ast
import json
import os
import re
from io import BytesIO
from datetime import date, datetime, timezone
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import (
    app,
    db,
    User,
    Organization,
    Urun,
    Warehouse,
    StokHareket,
    Cari,
    Satis,
    SatisKalemi,
    Teklif,
    TeklifKalemi,
    AuditLog,
    SystemSettings,
    SupportTicket,
    SupportTicketMessage,
    ActionItem,
    ActionItemEvent,
    SubscriptionPayment,
    BackupLog,
    Account,
    CashTransaction,
    AccountReconciliation,
    Iade,
    CariHareket,
    Departman,
    Personel,
    Izin,
    Avans,
    Prim,
    MaasKaydi,
    bootstrap_platform_admins,
    ensure_user_organization,
    ensure_default_accounts_for_user,
    generate_password_reset_token,
    platform_can,
    parse_module_permissions,
    user_display_name,
    default_account_for_payment_method,
    normalize_payment_method,
    backup_dir_for_user,
    build_cari_ekstre_context,
    format_tr_datetime,
    parse_iso_datetime,
)


def primary_test_user_backup_dir():
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        return Path(backup_dir_for_user(user))


def enable_platform_pos_integration_for_users():
    with app.app_context():
        db.session.add(SystemSettings(
            key='platform.pos_integration_enabled_for_users',
            value='on',
            description='Test POS entegrasyon gorunurlugu'
        ))
        db.session.commit()


@pytest.fixture(scope='function')
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        db.drop_all()
        db.create_all()
        user = User(
            email='test@example.com',
            password=generate_password_hash('password123'),
            firma_adi='Test Firma'
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
        other_user = User(
            email='other@example.com',
            password=generate_password_hash('password123'),
            firma_adi='Other Firma'
        )
        db.session.add(other_user)
        db.session.commit()
        other_user_id = other_user.id

        product = Urun(
            barkod='1234567890123',
            urun_adi='Test Urun',
            kategori='Elektronik',
            birim='Adet',
            alis_fiyati=50.0,
            satis_fiyati=100.0,
            stok_miktari=20.0,
            kritik_stok=5.0,
            depo_adi='Ana Depo',
            user_id=user_id
        )
        db.session.add(product)
        db.session.add(Cari(unvan='Test Cari', user_id=user_id))
        db.session.add(Cari(unvan='Other Cari', user_id=other_user_id))
        db.session.add(Warehouse(name='Ana Depo', user_id=user_id))
        db.session.add(Warehouse(name='Merkez Depo', user_id=user_id))
        db.session.commit()
        product_id = product.id

    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
            sess['_fresh'] = True
        yield client


def test_security_audit(client):
    response = client.post('/api/settings/security-audit', json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert 'results' in data


def test_turkish_money_filters_use_thousand_separator(client):
    assert app.jinja_env.filters['tr_number'](22580) == '22.580,00'
    assert app.jinja_env.filters['money'](22580) == '₺22.580,00'


def test_iso_datetime_is_displayed_in_turkey_time(client):
    parsed = parse_iso_datetime('2026-07-02T09:06:00.000Z')

    assert parsed.tzinfo is None
    assert format_tr_datetime(parsed) == '02.07.2026 12:06'


def test_daily_sales_filter_uses_turkey_day_bounds(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        db.session.add(Satis(
            fatura_no='POS-LOCAL-DAY',
            user_id=owner.id,
            tarih=datetime(2026, 7, 1, 21, 30),
            genel_toplam=575,
            durum='tamamlandi',
        ))
        db.session.commit()

    response = client.get('/gunluk-satislar?tarih=2026-07-02')

    assert response.status_code == 200
    assert b'POS-LOCAL-DAY' in response.data


def test_public_pricing_page_renders_packages(client):
    response = client.get('/fiyatlar')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Demo' in text
    assert 'Standart' in text
    assert 'Profesyonel' in text
    assert '₺3.900 + KDV' in text
    assert 'Günlük sadece ₺10,68 + KDV' in text
    assert '₺5.900 + KDV' in text
    assert 'Günlük sadece ₺16,16 + KDV' in text
    assert '/kayit?paket=standart&amp;odeme=1' in text

    sitemap = client.get('/sitemap.xml').get_data(as_text=True)
    assert '/fiyatlar' in sitemap


def test_package_upgrade_page_renders_usage_and_request_options(client):
    response = client.get('/paket-yukselt?reason=product_limit')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Paket yükseltme' in text
    assert 'Ürün kullanımı' in text
    assert 'Standart' in text
    assert 'Profesyonel' in text
    assert 'Satın Alma Talebi Oluştur' in text


def test_demo_product_limit_redirects_to_package_upgrade(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        owner.paket_tipi = 'demo'
        owner.urun_limiti = 10
        organization = ensure_user_organization(owner)
        organization.plan = 'demo'
        organization.product_limit = 10
        current_count = Urun.query.filter_by(user_id=owner.id).count()
        for index in range(current_count, 10):
            db.session.add(Urun(
                urun_adi=f'Limit Urun {index}',
                kategori='Test',
                birim='Adet',
                satis_fiyati=1,
                stok_miktari=1,
                user_id=owner.id,
            ))
        db.session.commit()

    response = client.post('/urun-ekle', data={
        'urun_adi': 'Limit Sonrasi Urun',
        'kategori': 'Test',
        'birim': 'Adet',
        'alis_fiyati': '0',
        'satis_fiyati': '10',
        'stok_miktari': '1',
        'kritik_stok': '1',
        'depo_adi': 'Ana Depo',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '/paket-yukselt' in response.headers['Location']


def test_pos_quick_product_respects_package_limit(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        owner.paket_tipi = 'demo'
        owner.urun_limiti = 10
        organization = ensure_user_organization(owner)
        organization.plan = 'demo'
        organization.product_limit = 10
        current_count = Urun.query.filter_by(user_id=owner.id).count()
        for index in range(current_count, 10):
            db.session.add(Urun(
                urun_adi=f'POS Limit Urun {index}',
                kategori='Test',
                birim='Adet',
                satis_fiyati=1,
                stok_miktari=1,
                user_id=owner.id,
            ))
        db.session.commit()

    response = client.post('/api/pos/products', json={
        'urun_adi': 'POS Limit Sonrasi',
        'satis_fiyati': 10,
        'stok_miktari': 1,
    })
    data = response.get_json()

    assert response.status_code == 200
    assert data['success'] is False
    assert 'limitiniz doldu' in data['message']
    assert data['upgrade_url'].startswith('/paket-yukselt')


def test_register_with_paid_plan_creates_billing_ticket(client):
    with client.session_transaction() as sess:
        sess.clear()

    response = client.post('/kayit', data={
        'requested_plan': 'standart',
        'firma_adi': 'Talep Firma',
        'yetkili_adi': 'Talep Sahibi',
        'email': 'talep@example.com',
        'telefon': '05550000000',
        'password': 'password123',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email='talep@example.com').first()
        assert user is not None
        assert user.paket_tipi == 'demo'
        ticket = SupportTicket.query.filter_by(organization_id=user.organization_id, category='billing').first()
        assert ticket is not None
        assert 'Standart paket' in ticket.subject


def test_settings_preferences_are_persisted(client):
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/preferences', json={
            'language': 'tr',
            'theme': 'dark',
            'items_per_page': '50',
            'currency': 'TRY',
            'default_vat_rate': 20,
            'stock_warning_threshold': 7,
            'auto_backup_enabled': False,
            'compact_view': True,
            'card_view': False,
            'pinned_sidebar': True,
            'date_format': 'dd.MM.yyyy',
            'time_format': '24',
            'timezone': 'Europe/Istanbul',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        saved = json.loads(settings_path.read_text(encoding='utf-8'))
        assert saved['theme'] == 'dark'
        assert saved['items_per_page'] == '50'
        assert saved['default_vat_rate'] == 20
        assert saved['compact_view'] is True
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_product_table_uses_items_per_page_preference(client):
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/preferences', json={'items_per_page': '10'})
        assert response.status_code == 200
        assert response.get_json()['success'] is True

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            for index in range(12):
                db.session.add(Urun(
                    barkod=f'PAGE-{index:02d}',
                    urun_adi=f'Ayar Urun {index:02d}',
                    kategori='Sayfalama',
                    birim='Adet',
                    alis_fiyati=1,
                    satis_fiyati=2,
                    stok_miktari=10,
                    kritik_stok=1,
                    depo_adi='Ana Depo',
                    user_id=user.id,
                ))
            db.session.commit()

        first_page = client.get('/urunler')
        assert first_page.status_code == 200
        assert 'Sayfa başına 10'.encode('utf-8') in first_page.data
        assert b'Ayar Urun 00' in first_page.data
        assert b'Ayar Urun 09' in first_page.data
        assert b'Ayar Urun 10' not in first_page.data

        second_page = client.get('/urunler?page=2')
        assert second_page.status_code == 200
        assert b'Ayar Urun 10' in second_page.data
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_settings_profile_uploads_company_logo(client):
    response = client.post('/api/settings/profile', data={
        'firma_adi': 'Logo Test Firma',
        'yetkili_adi': 'Mehmet Durna',
        'telefon': '555',
        'firma_logo': (BytesIO(b'fake image bytes'), 'logo.png'),
    }, content_type='multipart/form-data')

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert 'uploads/company_logos/firma_logo_' in data['logo_url']

    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        assert user.firma_adi == 'Logo Test Firma'
        assert user.firma_logo.startswith('uploads/company_logos/firma_logo_')
        logo_path = Path(app.static_folder) / user.firma_logo
        assert logo_path.exists()
        logo_path.unlink()


def test_settings_notifications_are_persisted(client):
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/notifications', json={
            'notify_stock_alerts': True,
            'notify_customer_activity': False,
            'notify_quote_status': True,
            'notification_summary_frequency': 'daily',
            'notification_report_frequency': 'monthly',
            'quiet_hours_start': '21:30',
            'quiet_hours_end': '08:15',
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        saved = json.loads(settings_path.read_text(encoding='utf-8'))
        assert saved['notify_customer_activity'] is False
        assert saved['notification_summary_frequency'] == 'daily'
        assert saved['quiet_hours_start'] == '21:30'
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_pos_integration_settings_are_persisted_and_validated(client):
    enable_platform_pos_integration_for_users()
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/pos-integration', json={
            'mode': 'integrated',
            'provider': 'pavo',
            'environment': 'test',
            'connection_type': 'ip',
            'bank_name': 'Test Bankas?',
            'terminal_id': 'TERM-001',
            'merchant_id': 'MERCHANT-001',
            'device_ip': '192.168.1.50',
            'device_port': '8080',
            'device_serial': 'SN-001',
            'service_url': 'http://192.168.1.50:8080',
            'username': 'servis',
            'api_key': 'secret-key',
            'timeout_seconds': 30,
            'test_amount': 1,
            'installer_name': 'POS Teknik',
            'installer_phone': '5550000000',
            'activation_code': 'ACT-001',
            'auto_send_amount': True,
            'require_success': True,
            'print_receipt': False,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        saved = json.loads(settings_path.read_text(encoding='utf-8'))
        assert saved['pos_integration']['provider'] == 'pavo'
        assert saved['pos_integration']['terminal_id'] == 'TERM-001'
        assert saved['pos_integration']['api_key'] == 'secret-key'

        test_response = client.post('/api/settings/pos-integration/test', json={
            'mode': 'integrated',
            'provider': 'pavo',
            'environment': 'test',
            'connection_type': 'ip',
            'bank_name': 'Test Bankas?',
            'terminal_id': 'TERM-001',
            'merchant_id': 'MERCHANT-001',
            'device_ip': '192.168.1.50',
            'device_port': '8080',
            'device_serial': 'SN-001',
            'service_url': 'http://192.168.1.50:8080',
            'username': 'servis',
            'timeout_seconds': 30,
            'test_amount': 1,
            'auto_send_amount': True,
            'require_success': True,
        })
        assert test_response.status_code == 200
        assert test_response.get_json()['status'] == 'configured'

        settings_response = client.get('/settings')
        assert settings_response.status_code == 200
        assert b'secret-key' not in settings_response.data
        assert 'Kayıtlı anahtar korunur'.encode('utf-8') in settings_response.data
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_manual_pos_integration_accepts_empty_numeric_fields(client):
    enable_platform_pos_integration_for_users()
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/pos-integration', json={
            'mode': 'manual',
            'provider': 'manual',
            'timeout_seconds': '',
            'test_amount': '',
            'auto_send_amount': False,
            'require_success': False,
            'print_receipt': True,
        })

        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True

        saved = json.loads(settings_path.read_text(encoding='utf-8'))
        assert saved['pos_integration']['mode'] == 'manual'
        assert saved['pos_integration']['enabled'] is False
        assert saved['pos_integration']['timeout_seconds'] == 30
        assert saved['pos_integration']['test_amount'] == 1
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_pos_integration_is_hidden_for_regular_users_by_default(client):
    settings_response = client.get('/settings')
    assert settings_response.status_code == 200
    assert 'POS Entegrasyon'.encode('utf-8') not in settings_response.data

    api_response = client.post('/api/settings/pos-integration', json={
        'mode': 'manual',
        'provider': 'manual',
    })
    assert api_response.status_code == 403
    assert api_response.get_json()['success'] is False


def test_pos_integration_is_visible_for_platform_owner(client):
    with app.app_context():
        owner = User(
            email='owner@example.com',
            password=generate_password_hash('password123'),
            firma_adi='Platform Ekibi',
            role='platform_staff',
            is_platform_admin=True,
            platform_role='owner',
            aktif=True,
        )
        db.session.add(owner)
        db.session.commit()
        owner_id = owner.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(owner_id)
        sess['_fresh'] = True

    settings_response = client.get('/settings')
    assert settings_response.status_code == 200
    assert 'POS Entegrasyon'.encode('utf-8') in settings_response.data

    api_response = client.post('/api/settings/pos-integration', json={
        'mode': 'manual',
        'provider': 'manual',
    })
    assert api_response.status_code == 200
    assert api_response.get_json()['success'] is True


def test_settings_backup_creates_backup_log(client):
    response = client.post('/api/settings/backup', json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    filename = data['filename']
    assert filename.endswith('.json')

    backup_path = primary_test_user_backup_dir() / filename
    assert backup_path.exists()

    with app.app_context():
        log = BackupLog.query.order_by(BackupLog.created_at.desc()).first()
        assert log is not None
        assert log.filename == filename


def test_super_admin_can_run_auto_backups(client):
    with app.app_context():
        customer = User.query.filter_by(email='test@example.com').first()
        assert customer is not None
        ensure_user_organization(customer)
        customer_id = customer.id
        customer_backup_dir = Path(backup_dir_for_user(customer))

        platform_owner = User(
            email='platform-owner@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform',
            yetkili_adi='Owner',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='owner',
        )
        db.session.add(platform_owner)
        db.session.commit()
        platform_owner_id = platform_owner.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(platform_owner_id)
        sess['_fresh'] = True

    response = client.post('/super-admin/backups/run-auto', follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        log = BackupLog.query.filter_by(user_id=customer_id, backup_type='auto', status='completed').order_by(BackupLog.created_at.desc()).first()
        assert log is not None
        backup_path = customer_backup_dir / log.filename
        assert backup_path.exists()


def test_super_admin_auto_backup_includes_customer_owner_who_is_platform_admin(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        owner_id = owner.id
        owner_backup_dir = Path(backup_dir_for_user(owner))
        db.session.commit()

    response = client.post('/super-admin/backups/run-auto', follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        log = BackupLog.query.filter_by(user_id=owner_id, backup_type='auto', status='completed').order_by(BackupLog.created_at.desc()).first()
        assert log is not None
        backup_path = owner_backup_dir / log.filename
        assert backup_path.exists()


def test_super_admin_owner_can_download_backup_file(client):
    with app.app_context():
        customer = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(customer)
        customer_id = customer.id

        platform_owner = User(
            email='platform-owner-download@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform',
            yetkili_adi='Owner',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='owner',
        )
        db.session.add(platform_owner)
        db.session.commit()
        platform_owner_id = platform_owner.id

        # Create a backup file + log for the customer
        response = client.post('/api/settings/backup', json={})
        assert response.status_code == 200
        data = response.get_json()
        filename = data['filename']
        log = BackupLog.query.filter_by(user_id=customer_id, filename=filename).first()
        assert log is not None
        backup_id = log.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(platform_owner_id)
        sess['_fresh'] = True

    resp = client.get(f'/super-admin/backups/download/{backup_id}', follow_redirects=False)
    assert resp.status_code == 200
    assert resp.headers.get('Content-Disposition')


def test_settings_password_rejects_invalid_payloads(client):
    response = client.post('/api/settings/password', json={
        'current_password': 'password123',
        'new_password': 'short',
    })

    assert response.status_code == 400
    data = response.get_json()
    assert data['success'] is False


def test_settings_password_updates_with_valid_payload(client):
    response = client.post('/api/settings/password', json={
        'current_password': 'password123',
        'new_password': 'newpassword123',
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True

    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        assert check_password_hash(user.password, 'newpassword123')


def test_health_check_returns_operational_status(client):
    response = client.get('/health')
    data = response.get_json()

    assert response.status_code == 200
    assert data['status'] == 'ok'
    assert data['service'] == 'stokcari'
    assert data['checks']['database'] == 'ok'


def test_routed_templates_do_not_embed_duplicate_app_shells():
    source = Path('app.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    templates = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'render_template':
            if node.args and isinstance(node.args[0], ast.Constant):
                templates.add(node.args[0].value)

    allowed_standalone = {
        'error.html',
        'pos_urun_secimi_ve_sepet.html',
        'satis_fis_yazdir.html',
        'cari_ekstre_yazdir.html',
        'personel/personel_bordro.html',
    }
    for template in templates - allowed_standalone:
        text = Path('templates', template).read_text(encoding='utf-8', errors='replace')
        assert '<aside' not in text
        assert '<body' not in text
        assert '</body>' not in text
        assert '<html' not in text
        assert '</html>' not in text


def test_collapsed_sidebar_toggle_does_not_overlap_header():
    html = Path('templates', '_base.html').read_text(encoding='utf-8')
    collapsed_logo_rule_start = html.index('.sidebar-collapsed .sidebar-logo-container')

    assert 'class="sidebar-header h-16 flex items-center justify-between' in html
    assert 'class="sidebar-nav flex-1 overflow-y-auto overflow-x-hidden' in html
    assert '.sidebar-collapsed .sidebar-header' in html
    assert '.sidebar-collapsed .sidebar-nav' in html
    assert 'padding-left: 0.75rem;' in html
    assert 'padding-right: 0.75rem;' in html
    assert 'overflow-x: hidden;' in html
    assert 'display: none;' in html[collapsed_logo_rule_start:]


def test_user_profile_menu_is_in_header_not_sidebar(client):
    response = client.get('/dashboard')

    assert response.status_code == 200
    assert b'id="profile-menu-toggle"' in response.data
    assert b'id="profile-menu-dropdown"' in response.data
    assert b'toggleProfileMenu()' in response.data
    assert 'Çıkış Yap'.encode('utf-8') in response.data
    assert b'<!-- Footer / User Menu -->' not in response.data


def assert_active_nav(response, nav_key):
    html = response.data.decode('utf-8')
    pattern = rf'<a[^>]+data-nav-key="{re.escape(nav_key)}"[^>]+class="[^"]*active-nav'
    assert re.search(pattern, html), f'{nav_key} navigation item is not active'


def test_main_navigation_marks_accounting_personnel_and_support_active(client):
    cases = [
        ('/onmuhasebe/hesaplar', 'onmuhasebe_hesaplar'),
        ('/personel_yonetimi', 'personel_yonetimi'),
        ('/destek', 'support_tickets'),
    ]

    for url, nav_key in cases:
        response = client.get(url)
        assert response.status_code == 200
        assert_active_nav(response, nav_key)


def test_super_admin_navigation_item_marks_active(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        user.is_platform_admin = True
        user.platform_role = 'owner'
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert_active_nav(response, 'super_admin_dashboard')


def test_login_page_renders_professional_auth_actions(client):
    with client.session_transaction() as sess:
        sess.clear()

    response = client.get('/giris')

    assert response.status_code == 200
    assert b'Giri' in response.data
    assert b'Sifremi' in response.data or 'Şifremi'.encode('utf-8') in response.data
    assert b'toggle-password' in response.data
    assert b'Yeni kay' in response.data
    assert b'auth-feature-card' in response.data
    assert "H\u0131zl\u0131 sat\u0131\u015f".encode('utf-8') in response.data
    assert "Cari takip".encode('utf-8') in response.data
    assert "Veri izolasyonu".encode('utf-8') in response.data
    assert "personel ve \u00f6n muhasebe".encode('utf-8') in response.data


def test_platform_identity_and_seo_defaults_are_dynamic(client):
    with client.session_transaction() as sess:
        sess.clear()

    with app.app_context():
        db.session.add(SystemSettings(key='platform.platform_name', value='BulutPOS Panel'))
        db.session.add(SystemSettings(key='platform.site_url', value='https://bulutpos.example'))
        db.session.add(SystemSettings(key='platform.site_name', value='BulutPOS Web'))
        db.session.add(SystemSettings(key='platform.site_description', value='Dinamik SEO aciklamasi'))
        db.session.add(SystemSettings(key='platform.site_og_image', value='https://cdn.example/og.png'))
        db.session.commit()

    response = client.get('/')

    assert response.status_code == 200
    assert b'BulutPOS Web' in response.data
    assert b'Dinamik SEO aciklamasi' in response.data
    assert b'https://bulutpos.example/' in response.data
    assert b'https://cdn.example/og.png' in response.data

    login_response = client.get('/giris')
    assert login_response.status_code == 200
    assert b'BulutPOS Panel' in login_response.data

    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    dashboard_response = client.get('/dashboard')
    assert dashboard_response.status_code == 200
    assert b'BulutPOS Panel' in dashboard_response.data


def test_password_reset_flow_updates_password(client):
    with client.session_transaction() as sess:
        sess.clear()

    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        token = generate_password_reset_token(user)

    response = client.post(f'/sifre-sifirla/{token}', data={
        'password': 'newpassword123',
        'confirm_password': 'newpassword123'
    }, follow_redirects=False)

    assert response.status_code == 302

    login_response = client.post('/giris', data={
        'email': 'test@example.com',
        'password': 'newpassword123'
    }, follow_redirects=False)
    assert login_response.status_code == 302
    assert '/dashboard' in login_response.headers['Location']


def test_login_remember_me_sets_persistent_cookie(client):
    with client.session_transaction() as sess:
        sess.clear()

    response = client.post('/giris', data={
        'email': 'test@example.com',
        'password': 'password123',
        'remember': 'on'
    }, follow_redirects=False)

    cookies = response.headers.getlist('Set-Cookie')
    assert response.status_code == 302
    assert any(cookie.startswith('remember_token=') for cookie in cookies)


def test_deleted_session_user_is_logged_out_instead_of_500(client):
    with client.session_transaction() as sess:
        sess['_user_id'] = '999999'
        sess['_fresh'] = True

    response = client.get('/urun-ekle', follow_redirects=False)

    assert response.status_code == 302
    assert '/giris' in response.headers['Location']


def test_registration_creates_company_tenant(client):
    with client.session_transaction() as sess:
        sess.clear()

    response = client.post('/kayit', data={
        'email': 'newco@example.com',
        'password': 'password123',
        'firma_adi': 'Yeni Firma',
        'yetkili_adi': 'Yeni Yetkili'
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email='newco@example.com').first()
        assert user is not None
        assert user.organization_id is not None
        assert db.session.get(Organization, user.organization_id).name == 'Yeni Firma'


def test_same_company_users_share_products_and_customers(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        teammate = User.query.filter_by(email='other@example.com').first()
        organization = ensure_user_organization(owner)
        teammate.organization_id = organization.id
        teammate.role = 'staff'
        db.session.commit()
        teammate_id = teammate.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(teammate_id)
        sess['_fresh'] = True

    products_response = client.get('/urunler')
    customers_response = client.get('/cariler')

    assert products_response.status_code == 200
    assert customers_response.status_code == 200
    assert b'Test Urun' in products_response.data
    assert b'Test Cari' in customers_response.data


def test_super_admin_requires_platform_owner_permission(client):
    response = client.get('/super-admin', follow_redirects=False)

    assert response.status_code == 302
    assert '/dashboard' in response.headers['Location']


def test_super_admin_dashboard_renders_for_platform_admin(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        organization.subscription_end = date(2026, 1, 1)
        organization.subscription_status = 'active'
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert b'Super Admin' in response.data
    assert b'Aksiyon Merkezi' in response.data
    assert b'Destek Talepleri' in response.data
    assert b'Firma Yonetimi' in response.data
    assert b'Suresi doldu' in response.data
    assert b'id="platform-settings-tab"' not in response.data


def test_super_admin_logs_show_turkish_audit_labels(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.add(AuditLog(
            user_id=owner.id,
            action='PLATFORM_ORGANIZATION_UPDATE',
            resource_type='Organization',
            resource_id=1,
            details='Organization islem yapildi: PLATFORM_ORGANIZATION_UPDATE',
        ))
        db.session.commit()

    response = client.get('/super-admin/logs')

    assert response.status_code == 200
    assert b'Firma ayarlari guncellendi' in response.data
    assert b'Firma #1' in response.data
    assert b'PLATFORM_ORGANIZATION_UPDATE' not in response.data
    assert b'Organization #1' not in response.data


def test_super_admin_updates_platform_settings(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.commit()

    response = client.post('/super-admin/settings/update', data={
        'platform_name': 'StokCari Pro',
        'default_plan': 'profesyonel',
        'default_user_limit': '8',
        'default_product_limit': '750',
        'registrations_enabled': 'on',
        'min_password_length': '12',
        'session_lifetime_minutes': '720',
        'failed_login_limit': '6',
        'maintenance_message': 'Planli bakim devam ediyor.',
        'support_email': 'destek@example.com',
        'auto_backup_frequency': 'weekly',
        'backup_retention_days': '90',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-system' in response.headers['Location']
    with app.app_context():
        settings = {
            setting.key: setting.value
            for setting in SystemSettings.query.filter(SystemSettings.key.in_([
                'platform.platform_name',
                'platform.default_plan',
                'platform.default_user_limit',
                'platform.default_product_limit',
                'platform.registrations_enabled',
                'platform.min_password_length',
                'platform.session_lifetime_minutes',
                'platform.failed_login_limit',
                'platform.maintenance_message',
                'platform.support_email',
                'platform.auto_backup_frequency',
                'platform.backup_retention_days',
            ])).all()
        }
        assert settings['platform.platform_name'] == 'StokCari Pro'
        assert settings['platform.default_plan'] == 'profesyonel'
        assert settings['platform.default_user_limit'] == '8'
        assert settings['platform.default_product_limit'] == '750'
        assert settings['platform.min_password_length'] == '12'
        assert settings['platform.auto_backup_frequency'] == 'weekly'


def test_super_admin_can_create_platform_team_member_without_company(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.commit()

    response = client.post('/super-admin/platform-team/create', data={
        'name': 'Destek Uzmani',
        'email': 'destek@example.com',
        'platform_role': 'support',
        'password': 'TempPass123',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-team' in response.headers['Location']
    with app.app_context():
        member = User.query.filter_by(email='destek@example.com').first()
        assert member is not None
        assert member.is_platform_admin is True
        assert member.platform_role == 'support'
        assert member.organization_id is None
        assert member.firma_adi == 'Platform Ekibi'
        assert user_display_name(member) == 'Destek Uzmani'


def test_platform_staff_organization_is_hidden_from_company_management(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        staff = User(
            email='legacy-support@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Legacy Destek',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='support',
        )
        db.session.add(staff)
        db.session.flush()
        db.session.add(Organization(
            name='Yanlis Platform Ekibi Firmasi',
            slug='yanlis-platform-ekibi-firmasi',
            owner_user_id=staff.id,
            plan='profesyonel',
            product_limit=10,
            active=True,
        ))
        db.session.flush()
        staff.organization_id = Organization.query.filter_by(slug='yanlis-platform-ekibi-firmasi').first().id
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert 'Yanlis Platform Ekibi Firmasi'.encode('utf-8') not in response.data
    assert b'legacy-support@example.com' in response.data


def test_platform_team_update_detaches_legacy_company_link(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        staff = User(
            email='detached-support@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Destek',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='support',
        )
        db.session.add(staff)
        db.session.flush()
        organization = Organization(
            name='Eski Platform Firma Baglantisi',
            slug='eski-platform-firma-baglantisi',
            owner_user_id=staff.id,
            plan='profesyonel',
            product_limit=10,
            active=True,
        )
        db.session.add(organization)
        db.session.flush()
        staff.organization_id = organization.id
        staff_id = staff.id
        db.session.commit()

    response = client.post(f'/super-admin/platform-team/{staff_id}/update', data={
        'name': 'Destek Guncel',
        'platform_role': 'support',
        'aktif': 'on',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-team' in response.headers['Location']
    with app.app_context():
        staff = db.session.get(User, staff_id)
        assert staff.organization_id is None
        assert staff.role == 'platform_staff'


def test_platform_team_member_appears_in_action_owner_list(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        member = User(
            email='operasyon@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Operasyon',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='operations',
        )
        action = ActionItem(
            organization_id=organization.id,
            source_type='manual',
            source_id=778,
            title='Sahip listesi testi',
            description='Platform ekibi gorunmeli.',
            severity='medium',
            status='open',
        )
        db.session.add_all([member, action])
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert b'Platform Ekibi' in response.data
    assert b'operasyon@example.com' in response.data


def test_platform_team_permissions_restrict_team_management(client):
    with app.app_context():
        support_user = User(
            email='support-role@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Destek Yetkilisi',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='support',
        )
        db.session.add(support_user)
        db.session.commit()
        support_user_id = support_user.id
        assert platform_can('support_manage', support_user) is True
        assert platform_can('team_manage', support_user) is False

    with client.session_transaction() as sess:
        sess['_user_id'] = str(support_user_id)
        sess['_fresh'] = True

    response = client.post('/super-admin/platform-team/create', data={
        'name': 'Yetkisiz',
        'email': 'yetkisiz@example.com',
        'platform_role': 'viewer',
        'password': 'TempPass123',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        assert User.query.filter_by(email='yetkisiz@example.com').first() is None


def test_platform_registration_settings_apply_to_new_company(client):
    with app.app_context():
        db.session.add(SystemSettings(key='platform.default_plan', value='profesyonel'))
        db.session.add(SystemSettings(key='platform.default_user_limit', value='4'))
        db.session.add(SystemSettings(key='platform.default_product_limit', value='120'))
        db.session.add(SystemSettings(key='platform.min_password_length', value='10'))
        db.session.commit()
    with client.session_transaction() as sess:
        sess.pop('_user_id', None)
        sess.pop('_fresh', None)

    response = client.post('/kayit', data={
        'firma_adi': 'Yeni Kayit Firma',
        'yetkili_adi': 'Yetkili',
        'email': 'new-company@example.com',
        'telefon': '5555555555',
        'password': 'longpass123',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        user = User.query.filter_by(email='new-company@example.com').first()
        assert user is not None
        organization = db.session.get(Organization, user.organization_id)
        assert user.paket_tipi == 'profesyonel'
        assert user.urun_limiti == 120
        assert organization.plan == 'profesyonel'
        assert organization.user_limit == 4
        assert organization.product_limit == 120
        assert organization.subscription_end is not None


def test_super_admin_updates_organization_limits_and_modules(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        organization_id = organization.id
        db.session.commit()

    response = client.post(f'/super-admin/organizations/{organization_id}/update', data={
        'name': 'Yeni Platform Firma',
        'plan': 'profesyonel',
        'active': 'on',
        'user_limit': '7',
        'product_limit': '250',
        'subscription_start': '2026-05-13',
        'subscription_end': '2027-05-13',
        'subscription_status': 'active',
        'subscription_note': 'Yillik destek yenilendi.',
        'modules': ['dashboard', 'urunler', 'personel'],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        organization = db.session.get(Organization, organization_id)
        owner = User.query.filter_by(email='test@example.com').first()
        modules = parse_module_permissions(organization.module_permissions)
        assert organization.name == 'Yeni Platform Firma'
        assert organization.plan == 'profesyonel'
        assert organization.user_limit == 7
        assert organization.product_limit == 250
        assert organization.subscription_start == date(2026, 5, 13)
        assert organization.subscription_end == date(2027, 5, 13)
        assert organization.subscription_status == 'active'
        assert organization.subscription_note == 'Yillik destek yenilendi.'
        assert modules['personel'] is True
        assert modules['cariler'] is False
        assert owner.paket_tipi == 'profesyonel'
        assert owner.urun_limiti == 250


def test_super_admin_reset_organization_clears_operational_data(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        owner_email = owner.email
        organization_name = organization.name
        organization_id = organization.id

        account = Account(user_id=owner.id, type='cash', name='Test Kasa', currency='TRY', opening_balance=100)
        product = Urun(user_id=owner.id, urun_adi='Test Urun', satis_fiyati=100, stok_miktari=5)
        customer = Cari(user_id=owner.id, unvan='Test Musteri', tipi='Musteri', alacak=100)
        db.session.add_all([account, product, customer])
        db.session.flush()

        sale = Satis(
            user_id=owner.id,
            cari_id=customer.id,
            fatura_no='POS-RESET-001',
            ara_toplam=100,
            genel_toplam=100,
        )
        db.session.add(sale)
        db.session.flush()
        db.session.add_all([
            SatisKalemi(satis_id=sale.id, urun_id=product.id, urun_adi=product.urun_adi, miktar=1, birim_fiyat=100, toplam=100),
            CashTransaction(user_id=owner.id, account_id=account.id, cari_id=customer.id, islem_tipi='giris', tutar=100),
            CariHareket(user_id=owner.id, cari_id=customer.id, islem_tipi='satis', tutar=100),
            StokHareket(user_id=owner.id, urun_id=product.id, islem_tipi='cikis', miktar=1),
            SupportTicket(organization_id=organization.id, requester_id=owner.id, subject='Reset testi', category='technical'),
            ActionItem(organization_id=organization.id, source_type='manual', source_id=1, title='Reset aksiyonu'),
            SubscriptionPayment(organization_id=organization.id, plan='standart', amount=500, status='paid'),
            BackupLog(filename='reset-test.zip', file_size=10, user_id=owner.id),
        ])
        db.session.commit()

    response = client.post(
        f'/super-admin/organizations/{organization_id}/reset',
        data={'reset_confirm': 'SIFIRLA'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert '#companies' in response.headers['Location']
    with app.app_context():
        organization = db.session.get(Organization, organization_id)
        owner = User.query.filter_by(email=owner_email).first()
        assert organization is not None
        assert organization.name == organization_name
        assert owner is not None
        assert owner.organization_id == organization_id
        assert Urun.query.filter_by(user_id=owner.id).count() == 0
        assert Cari.query.filter_by(user_id=owner.id).count() == 0
        assert Satis.query.filter_by(user_id=owner.id).count() == 0
        assert CashTransaction.query.filter_by(user_id=owner.id).count() == 0
        assert SupportTicket.query.filter_by(organization_id=organization_id).count() == 0
        assert ActionItem.query.filter_by(organization_id=organization_id).count() == 0
        assert BackupLog.query.filter_by(user_id=owner.id).count() == 0
        assert SubscriptionPayment.query.filter_by(organization_id=organization_id).count() == 1
        assert Account.query.filter_by(user_id=owner.id).count() == 3
        assert AuditLog.query.filter_by(action='PLATFORM_ORGANIZATION_RESET', user_id=owner.id).first() is not None


def test_super_admin_embeds_company_users_inside_company_management(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        teammate = User(
            email='firma-user@example.com',
            password=generate_password_hash('password123'),
            firma_adi=organization.name,
            yetkili_adi='Firma Kullanici',
            organization_id=organization.id,
            role='staff',
            aktif=True,
        )
        db.session.add(teammate)
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert b'Firma kullanicilari' in response.data
    assert b'firma-user@example.com' in response.data
    assert b'id="platform-users-tab" class="settings-tab-btn hidden' in response.data


def test_super_admin_updates_company_user_and_returns_to_company_management(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        teammate = User(
            email='role-change@example.com',
            password=generate_password_hash('password123'),
            firma_adi=organization.name,
            organization_id=organization.id,
            role='staff',
            aktif=True,
        )
        db.session.add(teammate)
        db.session.commit()
        teammate_id = teammate.id

    response = client.post(f'/super-admin/users/{teammate_id}/update', data={
        'firma_adi': 'Test Firma',
        'paket_tipi': 'demo',
        'urun_limiti': '10',
        'role': 'admin',
        'aktif': 'on',
        'source_context': 'organization_users',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '#companies' in response.headers['Location']
    with app.app_context():
        teammate = db.session.get(User, teammate_id)
        assert teammate.role == 'admin'
        assert teammate.aktif is True


def test_super_admin_organization_360_and_payment_history(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.commit()
        organization_id = organization.id

    response = client.get(f'/super-admin/organizations/{organization_id}')

    assert response.status_code == 200
    assert b'Firma 360' in response.data
    assert b'Odeme / abonelik kaydi' in response.data

    response = client.post(f'/super-admin/organizations/{organization_id}/payments', data={
        'plan': 'standart',
        'amount': '1200',
        'currency': 'TRY',
        'period_start': '2026-05-14',
        'period_end': '2027-05-14',
        'status': 'paid',
        'note': 'Yillik destek odendi.',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        payment = SubscriptionPayment.query.filter_by(organization_id=organization_id).first()
        organization = db.session.get(Organization, organization_id)
        assert payment is not None
        assert payment.amount == 1200
        assert payment.status == 'paid'
        assert organization.subscription_end == date(2027, 5, 14)


def test_super_admin_maintenance_returns_to_system_tab(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.commit()

    response = client.post('/super-admin/maintenance', data={'maintenance_mode': 'on'}, follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-system' in response.headers['Location']


def test_super_admin_updates_system_management_controls(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.commit()

    response = client.post('/super-admin/system/update', data={
        'min_password_length': '11',
        'session_lifetime_minutes': '900',
        'failed_login_limit': '7',
        'auto_backup_frequency': 'monthly',
        'backup_retention_days': '120',
        'maintenance_mode': 'on',
        'registrations_enabled': 'on',
        'readonly_mode': 'on',
        'file_uploads_locked': 'on',
        'dangerous_operations_locked': 'on',
        'security_shield_enabled': 'on',
        'owner_account_protection': 'on',
        'financial_changes_locked': 'on',
        'support_impersonation_locked': 'on',
        'data_export_locked': 'on',
        'owner_approval_required': 'on',
        'global_notice_enabled': 'on',
        'maintenance_message': 'Planli bakim.',
        'maintenance_eta': '18:30',
        'global_notice_message': 'Sistem duyurusu.',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-system' in response.headers['Location']
    with app.app_context():
        settings = {
            setting.key: setting.value
            for setting in SystemSettings.query.filter(SystemSettings.key.in_([
                'platform.maintenance_mode',
                'platform.readonly_mode',
                'platform.file_uploads_locked',
                'platform.dangerous_operations_locked',
                'platform.security_shield_enabled',
                'platform.owner_account_protection',
                'platform.financial_changes_locked',
                'platform.support_impersonation_locked',
                'platform.data_export_locked',
                'platform.owner_approval_required',
                'platform.global_notice_enabled',
                'platform.maintenance_message',
                'platform.maintenance_eta',
                'platform.global_notice_message',
                'platform.min_password_length',
                'platform.session_lifetime_minutes',
                'platform.failed_login_limit',
                'platform.auto_backup_frequency',
                'platform.backup_retention_days',
            ])).all()
        }
        assert settings['platform.maintenance_mode'] == 'on'
        assert settings['platform.readonly_mode'] == 'on'
        assert settings['platform.file_uploads_locked'] == 'on'
        assert settings['platform.dangerous_operations_locked'] == 'on'
        assert settings['platform.security_shield_enabled'] == 'on'
        assert settings['platform.owner_account_protection'] == 'on'
        assert settings['platform.financial_changes_locked'] == 'on'
        assert settings['platform.support_impersonation_locked'] == 'on'
        assert settings['platform.data_export_locked'] == 'on'
        assert settings['platform.owner_approval_required'] == 'on'
        assert settings['platform.global_notice_enabled'] == 'on'
        assert settings['platform.maintenance_message'] == 'Planli bakim.'
        assert settings['platform.maintenance_eta'] == '18:30'
        assert settings['platform.global_notice_message'] == 'Sistem duyurusu.'
        assert settings['platform.min_password_length'] == '11'
        assert settings['platform.session_lifetime_minutes'] == '900'
        assert settings['platform.failed_login_limit'] == '7'
        assert settings['platform.auto_backup_frequency'] == 'monthly'
        assert settings['platform.backup_retention_days'] == '120'


def test_system_controls_do_not_clear_defaults_or_smtp_settings(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.add(SystemSettings(key='platform.site_url', value='https://esstok.com'))
        db.session.add(SystemSettings(key='platform.site_name', value='Esstok'))
        db.session.add(SystemSettings(key='platform.site_description', value='Bulut tabanli isletme yonetimi'))
        db.session.add(SystemSettings(key='platform.ga4_code', value='GA-TEST'))
        db.session.add(SystemSettings(key='platform.search_console_code', value='SC-TEST'))
        db.session.add(SystemSettings(key='platform.smtp_host', value='mail.esstok.com'))
        db.session.add(SystemSettings(key='platform.smtp_port', value='587'))
        db.session.add(SystemSettings(key='platform.smtp_username', value='destek@esstok.com'))
        db.session.add(SystemSettings(key='platform.smtp_password', value='secret'))
        db.session.add(SystemSettings(key='platform.smtp_from_email', value='destek@esstok.com'))
        db.session.add(SystemSettings(key='platform.smtp_from_name', value='Esstok'))
        db.session.commit()

    response = client.post('/super-admin/system/update', data={
        'maintenance_mode': 'on',
        'security_shield_enabled': 'on',
        'auto_backup_frequency': 'weekly',
        'min_password_length': '10',
        'session_lifetime_minutes': '600',
        'failed_login_limit': '6',
        'backup_retention_days': '90',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        preserved = {
            setting.key: setting.value
            for setting in SystemSettings.query.filter(SystemSettings.key.in_([
                'platform.site_url',
                'platform.site_name',
                'platform.site_description',
                'platform.ga4_code',
                'platform.search_console_code',
                'platform.smtp_host',
                'platform.smtp_port',
                'platform.smtp_username',
                'platform.smtp_password',
                'platform.smtp_from_email',
                'platform.smtp_from_name',
            ])).all()
        }
        assert preserved['platform.site_url'] == 'https://esstok.com'
        assert preserved['platform.site_name'] == 'Esstok'
        assert preserved['platform.site_description'] == 'Bulut tabanli isletme yonetimi'
        assert preserved['platform.ga4_code'] == 'GA-TEST'
        assert preserved['platform.search_console_code'] == 'SC-TEST'
        assert preserved['platform.smtp_host'] == 'mail.esstok.com'
        assert preserved['platform.smtp_port'] == '587'
        assert preserved['platform.smtp_username'] == 'destek@esstok.com'
        assert preserved['platform.smtp_password'] == 'secret'
        assert preserved['platform.smtp_from_email'] == 'destek@esstok.com'
        assert preserved['platform.smtp_from_name'] == 'Esstok'


def test_financial_lock_blocks_non_owner_organization_update(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        operator = User(
            email='ops-lock@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Operasyon',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='operations',
        )
        db.session.add(SystemSettings(key='platform.financial_changes_locked', value='on'))
        db.session.add(operator)
        db.session.commit()
        organization_id = organization.id
        operator_id = operator.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(operator_id)
        sess['_fresh'] = True

    response = client.post(f'/super-admin/organizations/{organization_id}/update', data={
        'name': 'Kilitli Degisiklik',
        'plan': 'profesyonel',
        'active': 'on',
        'user_limit': '9',
        'product_limit': '900',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '#companies' in response.headers['Location']
    with app.app_context():
        organization = db.session.get(Organization, organization_id)
        assert organization.name != 'Kilitli Degisiklik'
        log = AuditLog.query.filter_by(action='PLATFORM_LOCK_BLOCKED', user_id=operator_id).first()
        assert log is not None
        assert log.resource_type == 'PlatformLock'
        assert 'financial_changes_locked' in log.details


def test_support_impersonation_lock_blocks_non_owner_team_member(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        support_user = User(
            email='support-lock@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Destek',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='support',
        )
        db.session.add(SystemSettings(key='platform.support_impersonation_locked', value='on'))
        db.session.add(support_user)
        db.session.commit()
        organization_id = organization.id
        support_id = support_user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(support_id)
        sess['_fresh'] = True

    response = client.post(f'/super-admin/organizations/{organization_id}/impersonate', follow_redirects=False)

    assert response.status_code == 302
    assert '#companies' in response.headers['Location']
    with client.session_transaction() as sess:
        assert sess.get('_user_id') == str(support_id)
        assert 'platform_admin_id' not in sess
    with app.app_context():
        log = AuditLog.query.filter_by(action='PLATFORM_LOCK_BLOCKED', user_id=support_id).first()
        assert log is not None
        assert 'support_impersonation_locked' in log.details


def test_data_export_lock_blocks_non_owner_backup_view(client):
    with app.app_context():
        operator = User(
            email='backup-lock@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Operasyon',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='operations',
        )
        db.session.add(SystemSettings(key='platform.data_export_locked', value='on'))
        db.session.add(operator)
        db.session.commit()
        operator_id = operator.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(operator_id)
        sess['_fresh'] = True

    response = client.get('/super-admin/backups', follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-backup' in response.headers['Location']
    with app.app_context():
        log = AuditLog.query.filter_by(action='PLATFORM_LOCK_BLOCKED', user_id=operator_id).first()
        assert log is not None
        assert 'data_export_locked' in log.details


def test_owner_approval_mode_blocks_non_owner_critical_action(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        operator = User(
            email='approval-lock@example.com',
            password=generate_password_hash('TempPass123'),
            firma_adi='Platform Ekibi',
            yetkili_adi='Operasyon',
            aktif=True,
            role='platform_staff',
            is_platform_admin=True,
            platform_role='operations',
        )
        db.session.add(SystemSettings(key='platform.owner_approval_required', value='on'))
        db.session.add(operator)
        db.session.commit()
        organization_id = organization.id
        operator_id = operator.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(operator_id)
        sess['_fresh'] = True

    response = client.post(f'/super-admin/organizations/{organization_id}/update', data={
        'name': 'Onaysiz Degisiklik',
        'plan': 'profesyonel',
        'active': 'on',
        'user_limit': '9',
        'product_limit': '900',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        organization = db.session.get(Organization, organization_id)
        assert organization.name != 'Onaysiz Degisiklik'
        log = AuditLog.query.filter_by(action='PLATFORM_LOCK_BLOCKED', user_id=operator_id).first()
        assert log is not None
        assert 'owner_approval_required' in log.details


def test_super_admin_self_test_runs_and_stores_actionable_report(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        db.session.commit()

    response = client.post('/super-admin/system/self-test', follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-system' in response.headers['Location']
    with app.app_context():
        setting = SystemSettings.query.filter_by(key='platform.self_test_last_result').first()
        assert setting is not None
        result = json.loads(setting.value)
        assert result['summary']['total'] > 0
        assert result['summary']['routes'] > 0
        assert result['summary']['templates'] > 0
        assert result['summary']['buttons'] > 0
        assert result['status'] in {'passed', 'warning', 'failed'}
        assert all('expected' in check and 'actual' in check and 'suggestion' in check for check in result['checks'])
        log = AuditLog.query.filter_by(action='PLATFORM_SELF_TEST_RUN').first()
        assert log is not None


def test_super_admin_workflow_test_runs_and_cleans_sandbox_data(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        db.session.commit()

    response = client.post('/super-admin/system/workflow-test', follow_redirects=False)

    assert response.status_code == 302
    assert '#platform-system' in response.headers['Location']
    with app.app_context():
        setting = SystemSettings.query.filter_by(key='platform.workflow_test_last_result').first()
        assert setting is not None
        result = json.loads(setting.value)
        assert result['summary']['total'] >= 5
        assert result['status'] in {'passed', 'warning', 'failed'}
        assert any(check['check'] == 'Stok dusen satis akisi' for check in result['checks'])
        assert User.query.filter(User.email.like('test_robot_%')).count() == 0
        assert Organization.query.filter(Organization.name.like('TEST_ROBOT%')).count() == 0
        assert Urun.query.filter(Urun.urun_adi.like('TEST_ROBOT%')).count() == 0
        log = AuditLog.query.filter_by(action='PLATFORM_WORKFLOW_TEST_RUN').first()
        assert log is not None


def test_super_admin_single_test_run_executes_and_stores_result(client, monkeypatch):
    class FakeCompletedProcess:
        returncode = 0
        stdout = '.                                                                        [100%]\n1 passed in 0.12s\n'
        stderr = ''

    def fake_run(command, **kwargs):
        assert command[-2] == 'tests/test_app.py::test_pos_integration_settings_are_persisted_and_validated'
        assert command[-1] == '-q'
        return FakeCompletedProcess()

    monkeypatch.setattr('app.subprocess.run', fake_run)

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        db.session.commit()

    response = client.post(
        '/super-admin/system/test-center/run',
        data={'test_name': 'test_pos_integration_settings_are_persisted_and_validated'},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert '#platform-system-test-center' in response.headers['Location']
    with app.app_context():
        setting = SystemSettings.query.filter_by(key='platform.single_test_last_result').first()
        assert setting is not None
        result = json.loads(setting.value)
        assert result['status'] == 'passed'
        assert result['technical_name'] == 'test_pos_integration_settings_are_persisted_and_validated'
        assert '1 passed' in result['output']
        log = AuditLog.query.filter_by(action='PLATFORM_SINGLE_TEST_RUN').first()
        assert log is not None


def test_super_admin_dashboard_renders_self_test_report(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        set_platform_setting = SystemSettings(
            key='platform.self_test_last_result',
            value=json.dumps({
                'status': 'failed',
                'status_label': 'Kritik hata var, mudahale gerekli',
                'ran_at': '2026-05-15T09:00:00+00:00',
                'summary': {
                    'total': 2,
                    'passed': 1,
                    'warnings': 0,
                    'failed': 1,
                    'routes': 10,
                    'api_routes': 3,
                    'templates': 5,
                    'forms': 2,
                    'buttons': 8,
                },
                'checks': [
                    {
                        'status': 'failed',
                        'severity': 'critical',
                        'area': 'Ayarlar',
                        'check': 'Test kontrolu',
                        'expected': 'Beklenen sonuc',
                        'actual': 'Gerceklesen hata',
                        'probable_cause': 'Olasi neden',
                        'suggestion': 'Mudahale onerisi',
                        'technical_detail': 'endpoint=test',
                    }
                ],
            }, ensure_ascii=False)
        )
        db.session.add(set_platform_setting)
        db.session.add(SystemSettings(
            key='platform.workflow_test_last_result',
            value=json.dumps({
                'status': 'passed',
                'status_label': 'Derin is akisi kararli',
                'ran_at': '2026-05-15T09:05:00+00:00',
                'summary': {
                    'total': 5,
                    'passed': 5,
                    'warnings': 0,
                    'failed': 0,
                    'routes': 1,
                    'api_routes': 0,
                    'templates': 0,
                    'forms': 0,
                    'buttons': 0,
                },
                'checks': [],
            }, ensure_ascii=False)
        ))
        db.session.add(SystemSettings(
            key='platform.single_test_last_result',
            value=json.dumps({
                'status': 'passed',
                'status_label': 'Test gecti',
                'ran_at': '2026-05-15T09:10:00+00:00',
                'technical_name': 'test_pos_integration_settings_are_persisted_and_validated',
                'label': 'POS entegrasyon ayarlari kaydoluyor ve dogrulaniyor',
                'target': 'tests/test_app.py::test_pos_integration_settings_are_persisted_and_validated',
                'line': 256,
                'duration_seconds': 0.12,
                'returncode': 0,
                'output': '1 passed in 0.12s',
            }, ensure_ascii=False)
        ))
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert b'Test Robotu' in response.data
    assert b'Kritik hata var' in response.data
    assert b'Mudahale onerisi' in response.data
    assert b'Derin is akisi kararli' in response.data
    assert b'Test Envanteri' in response.data
    assert b'test_pos_integration_settings_are_persisted_and_validated' in response.data
    assert b'tests/test_app.py' in response.data


def test_platform_lock_blocked_label_renders_in_audit_logs(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.add(AuditLog(
            user_id=owner.id,
            action='PLATFORM_LOCK_BLOCKED',
            resource_type='PlatformLock',
            details='Kilit=financial_changes_locked; endpoint=test',
        ))
        db.session.commit()

    response = client.get('/super-admin/logs')

    assert response.status_code == 200
    assert b'Kilitli islem engellendi' in response.data
    assert b'Platform kilidi' in response.data
    assert b'PLATFORM_LOCK_BLOCKED' not in response.data


def test_company_can_create_and_reply_to_support_ticket(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        organization_id = organization.id
        owner_id = owner.id
        db.session.commit()

    response = client.post('/destek', data={
        'subject': 'POS satis hatasi',
        'category': 'technical',
        'priority': 'high',
        'message': 'POS ekraninda odeme tamamlanmiyor.',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        ticket = SupportTicket.query.filter_by(organization_id=organization_id).first()
        assert ticket is not None
        assert ticket.requester_id == owner_id
        assert ticket.status == 'waiting_admin'
        assert ticket.messages[0].message == 'POS ekraninda odeme tamamlanmiyor.'

    response = client.post(f'/destek/{ticket.id}', data={'message': 'Ekran goruntusu eklendi.'}, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        ticket = db.session.get(SupportTicket, ticket.id)
        assert ticket.status == 'waiting_admin'
        assert len(ticket.messages) == 2


def test_support_ticket_can_include_screenshot(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        organization_id = organization.id
        db.session.commit()

    response = client.post('/destek', data={
        'subject': 'Ekran goruntulu hata',
        'category': 'bug',
        'priority': 'normal',
        'message': 'Hata ekran goruntusunde gorunuyor.',
        'screenshot': (BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'), 'hata.png'),
    }, content_type='multipart/form-data', follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        ticket = SupportTicket.query.filter_by(organization_id=organization_id).first()
        message = ticket.messages[0]
        assert message.attachment_filename.endswith('.png')
        assert message.attachment_original_name == 'hata.png'
        message_id = message.id
        filename = message.attachment_filename

    response = client.get(f'/destek/ek/{message_id}/{filename}')

    assert response.status_code == 200
    assert response.data.startswith(b'\x89PNG')


def test_system_file_upload_lock_blocks_support_screenshots(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_user_organization(owner)
        db.session.add(SystemSettings(key='platform.file_uploads_locked', value='on'))
        db.session.commit()

    response = client.post('/destek', data={
        'subject': 'Yukleme kilidi',
        'category': 'bug',
        'priority': 'normal',
        'message': 'Ekran goruntusu yuklenememeli.',
        'screenshot': (BytesIO(b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'), 'hata.png'),
    }, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 200
    assert b'Dosya yuklemeleri sistem yonetimi tarafindan gecici olarak kapatildi.' in response.data


def test_super_admin_can_answer_support_ticket(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        ticket = SupportTicket(
            organization_id=organization.id,
            requester_id=owner.id,
            subject='Abonelik sorusu',
            category='billing',
            priority='normal',
            status='waiting_admin',
        )
        db.session.add(ticket)
        db.session.flush()
        db.session.add(SupportTicketMessage(
            ticket_id=ticket.id,
            user_id=owner.id,
            message='Paket yenileme hakkinda bilgi alabilir miyim',
        ))
        ticket_id = ticket.id
        db.session.commit()

    response = client.post(f'/super-admin/support/{ticket_id}', data={
        'status': 'waiting_admin',
        'priority': 'high',
        'message': 'Yenileme icin sizinle iletisime gececegiz.',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        ticket = db.session.get(SupportTicket, ticket_id)
        assert ticket.priority == 'high'
        assert ticket.status == 'waiting_customer'
        assert ticket.messages[-1].is_staff_reply is True


def test_super_admin_support_list_links_and_turkish_labels(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        ticket = SupportTicket(
            organization_id=organization.id,
            requester_id=owner.id,
            subject='Teknik destek',
            category='billing',
            priority='high',
            status='open',
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert f"/super-admin/support/{ticket_id}".encode() in response.data
    assert 'Açık'.encode() in response.data
    assert 'Yüksek'.encode() in response.data
    assert 'Ödeme / Abonelik'.encode() in response.data


def test_super_admin_support_filters_do_not_reload_dashboard(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.add(SupportTicket(
            organization_id=organization.id,
            requester_id=owner.id,
            subject='Filtre testi',
            category='technical',
            priority='normal',
            status='waiting_admin',
        ))
        db.session.commit()

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert b'data-support-filter="waiting_admin"' in response.data
    assert b'data-support-status="waiting_admin"' in response.data
    assert b'support_status=waiting_admin' not in response.data


def test_super_admin_notifications_include_pending_support_tickets(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        db.session.add(SupportTicket(
            organization_id=organization.id,
            requester_id=owner.id,
            subject='Acil destek',
            category='technical',
            priority='urgent',
            status='waiting_admin',
        ))
        db.session.commit()

    response = client.get('/api/notifications')
    data = response.get_json()

    assert response.status_code == 200
    assert data['success'] is True
    assert data['count'] >= 1
    assert data['notifications'][0]['title'] == 'Yeni destek talebi'
    assert '#platform-support' in data['notifications'][0]['url']


def test_action_center_generates_support_action(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        ticket = SupportTicket(
            organization_id=organization.id,
            requester_id=owner.id,
            subject='Destek bekleyen hata',
            category='technical',
            priority='high',
            status='waiting_admin',
        )
        db.session.add(ticket)
        db.session.commit()
        ticket_id = ticket.id

    response = client.get('/super-admin')

    assert response.status_code == 200
    assert b'Aksiyon Merkezi' in response.data
    assert b'Destek talebi yan' in response.data
    with app.app_context():
        action = ActionItem.query.filter_by(source_type='support', source_id=ticket_id).first()
        assert action is not None
        assert action.status == 'open'
        assert action.severity == 'high'


def test_super_admin_can_complete_and_snooze_action(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        action = ActionItem(
            organization_id=organization.id,
            source_type='manual',
            source_id=999,
            title='Manuel takip',
            description='Kontrol edilecek.',
            severity='medium',
            status='open',
        )
        db.session.add(action)
        db.session.commit()
        action_id = action.id

    response = client.post(f'/super-admin/actions/{action_id}/update', data={'operation': 'snooze', 'days': '3'})

    assert response.status_code == 302
    with app.app_context():
        action = db.session.get(ActionItem, action_id)
        assert action.status == 'snoozed'
        assert action.snoozed_until is not None

    response = client.post(f'/super-admin/actions/{action_id}/update', data={'operation': 'done'})

    assert response.status_code == 302
    with app.app_context():
        action = db.session.get(ActionItem, action_id)
        assert action.status == 'done'
        assert action.resolved_at is not None


def test_super_admin_can_assign_action_and_tracks_history(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        owner.platform_role = 'operations'
        action = ActionItem(
            organization_id=organization.id,
            source_type='manual',
            source_id=777,
            title='Atama testi',
            description='Sahip atanacak.',
            severity='medium',
            status='open',
        )
        db.session.add(action)
        db.session.commit()
        action_id = action.id
        owner_id = owner.id

    response = client.post(f'/super-admin/actions/{action_id}/update', data={
        'operation': 'assign',
        'assigned_user_id': str(owner_id),
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        action = db.session.get(ActionItem, action_id)
        event = ActionItemEvent.query.filter_by(action_item_id=action_id, event_type='assigned').first()
        assert action.assigned_user_id == owner_id
        assert event is not None


def test_super_admin_can_refresh_action_ai_with_fallback(client, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        action = ActionItem(
            organization_id=organization.id,
            source_type='support',
            source_id=123,
            title='Destek talebi yan?t bekliyor',
            description='Firma destek yan?t? bekliyor.',
            severity='high',
            status='open',
        )
        db.session.add(action)
        db.session.commit()
        action_id = action.id

    response = client.post(f'/super-admin/actions/{action_id}/ai')

    assert response.status_code == 302
    with app.app_context():
        action = db.session.get(ActionItem, action_id)
        assert action.ai_summary
        assert action.ai_recommendation
        assert 'Talebi inceleyin' in action.ai_recommendation


def test_action_center_generates_subscription_action(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        organization = ensure_user_organization(owner)
        owner.is_platform_admin = True
        organization.subscription_end = date(2026, 5, 20)
        organization.subscription_status = 'active'
        db.session.commit()
        organization_id = organization.id

    response = client.get('/super-admin?source=subscription')

    assert response.status_code == 200
    with app.app_context():
        action = ActionItem.query.filter_by(source_type='subscription', source_id=organization_id).first()
        assert action is not None
        assert action.status == 'open'
        assert action.severity in {'medium', 'high', 'critical'}


def test_super_admin_impersonation_and_exit_restores_owner(client):
    with app.app_context():
        admin = User.query.filter_by(email='test@example.com').first()
        tenant_owner = User.query.filter_by(email='other@example.com').first()
        organization = ensure_user_organization(tenant_owner)
        admin.is_platform_admin = True
        organization_id = organization.id
        admin_id = admin.id
        tenant_owner_id = tenant_owner.id
        db.session.commit()

    response = client.post(f'/super-admin/organizations/{organization_id}/impersonate', follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess['platform_admin_id'] == admin_id
        assert sess['_user_id'] == str(tenant_owner_id)

    get_response = client.get('/super-admin/impersonation/exit', follow_redirects=False)
    assert get_response.status_code == 405

    response = client.post('/super-admin/impersonation/exit', follow_redirects=False)

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert 'platform_admin_id' not in sess
        assert sess['_user_id'] == str(admin_id)


def test_platform_maintenance_blocks_normal_users_but_not_platform_admin(client):
    with app.app_context():
        admin = User.query.filter_by(email='test@example.com').first()
        normal = User.query.filter_by(email='other@example.com').first()
        ensure_user_organization(admin)
        ensure_user_organization(normal)
        admin.is_platform_admin = True
        admin_id = admin.id
        normal_id = normal.id
        db.session.commit()

    response = client.post('/super-admin/maintenance', data={'maintenance_mode': 'on'}, follow_redirects=False)
    assert response.status_code == 302

    response = client.get('/dashboard')
    assert response.status_code == 200

    with client.session_transaction() as sess:
        sess['_user_id'] = str(normal_id)
        sess['_fresh'] = True

    response = client.get('/dashboard')
    assert response.status_code == 503

    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_id)
        sess['_fresh'] = True
    client.post('/super-admin/maintenance', data={}, follow_redirects=False)


def test_system_readonly_blocks_normal_user_mutations_but_not_super_admin(client):
    with app.app_context():
        admin = User.query.filter_by(email='test@example.com').first()
        normal = User.query.filter_by(email='other@example.com').first()
        ensure_user_organization(admin)
        ensure_user_organization(normal)
        admin.is_platform_admin = True
        normal_id = normal.id
        db.session.add(SystemSettings(key='platform.readonly_mode', value='on'))
        db.session.commit()

    response = client.post('/super-admin/system/update', data={
        'readonly_mode': 'on',
        'security_shield_enabled': 'on',
    }, follow_redirects=False)
    assert response.status_code == 302

    with client.session_transaction() as sess:
        sess['_user_id'] = str(normal_id)
        sess['_fresh'] = True

    response = client.post('/cari-ekle', data={'unvan': 'Readonly Cari'}, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        assert Cari.query.filter_by(unvan='Readonly Cari').first() is None


def test_bootstrap_creates_platform_admin_when_database_is_empty(client, monkeypatch):
    monkeypatch.setenv('PLATFORM_ADMIN_EMAILS', 'owner@example.com')
    monkeypatch.setenv('PLATFORM_ADMIN_PASSWORD', 'StrongTemporaryPassword123!')
    with app.app_context():
        db.session.query(AuditLog).delete()
        db.session.query(Urun).delete()
        db.session.query(Cari).delete()
        db.session.query(Warehouse).delete()
        db.session.query(User).delete()
        db.session.query(Organization).delete()
        db.session.commit()

        bootstrap_platform_admins()

        user = User.query.filter_by(email='owner@example.com').first()
        assert user is not None
        assert user.is_platform_admin is True
        assert user.aktif is True
        assert user.organization_id is not None
        assert db.session.get(Organization, user.organization_id).plan == 'profesyonel'


def test_platform_admin_bootstrap_is_idempotent(client, monkeypatch):
    monkeypatch.setenv('PLATFORM_ADMIN_EMAILS', 'owner@example.com')
    monkeypatch.setenv('PLATFORM_ADMIN_PASSWORD', 'StrongTemporaryPassword123!')

    with app.app_context():
        bootstrap_platform_admins()
        bootstrap_platform_admins()

        users = User.query.filter(db.func.lower(User.email) == 'owner@example.com').all()
        assert len(users) == 1
        assert users[0].is_platform_admin is True


def test_platform_admin_login_creates_missing_owner_account(client, monkeypatch):
    monkeypatch.setenv('PLATFORM_ADMIN_EMAILS', 'owner@example.com')
    monkeypatch.setenv('PLATFORM_ADMIN_PASSWORD', 'StrongTemporaryPassword123!')
    with app.app_context():
        db.session.query(AuditLog).delete()
        db.session.query(Urun).delete()
        db.session.query(Cari).delete()
        db.session.query(Warehouse).delete()
        db.session.query(User).delete()
        db.session.query(Organization).delete()
        db.session.commit()

    with client.session_transaction() as sess:
        sess.clear()

    response = client.post('/giris', data={
        'email': 'owner@example.com',
        'password': 'StrongTemporaryPassword123!',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '/dashboard' in response.headers['Location']
    with app.app_context():
        user = User.query.filter_by(email='owner@example.com').first()
        assert user is not None
        assert user.is_platform_admin is True


def test_reserved_owner_email_registers_as_super_admin(client):
    with client.session_transaction() as sess:
        sess.clear()

    with app.app_context():
        existing = User.query.filter_by(email='mehmetdurna@msn.com').first()
        if existing:
            db.session.delete(existing)
            db.session.commit()

    response = client.post('/kayit', data={
        'email': 'mehmetdurna@msn.com',
        'password': 'StrongPassword123!',
        'firma_adi': 'Platform Ekibi',
        'yetkili_adi': 'Mehmet Durna',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '/giris' in response.headers['Location']
    with app.app_context():
        user = User.query.filter_by(email='mehmetdurna@msn.com').first()
        assert user is not None
        assert user.is_platform_admin is True
        assert user.platform_role == 'owner'
        assert user.role == 'owner'
        organization = db.session.get(Organization, user.organization_id)
        assert organization.plan == 'profesyonel'


def test_reserved_owner_email_is_promoted_on_login(client):
    with app.app_context():
        user = User(
            email='mehmetdurna@msn.com',
            password=generate_password_hash('StrongPassword123!'),
            firma_adi='Platform Ekibi',
            is_platform_admin=False,
            platform_role='viewer',
        )
        db.session.add(user)
        db.session.commit()

    with client.session_transaction() as sess:
        sess.clear()

    response = client.post('/giris', data={
        'email': 'mehmetdurna@msn.com',
        'password': 'StrongPassword123!',
    }, follow_redirects=False)

    assert response.status_code == 302
    assert '/dashboard' in response.headers['Location']
    with app.app_context():
        user = User.query.filter_by(email='mehmetdurna@msn.com').first()
        assert user.is_platform_admin is True
        assert user.platform_role == 'owner'
        organization = db.session.get(Organization, user.organization_id)
        assert organization.plan == 'profesyonel'


def test_standard_security_headers_are_added(client):
    response = client.get('/health')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'
    assert response.headers['X-Request-ID']
    assert 'no-store' in response.headers['Cache-Control']


def test_security_shield_blocks_suspicious_requests(client):
    with app.app_context():
        db.session.add(SystemSettings(key='platform.security_shield_enabled', value='on'))
        db.session.commit()

    response = client.get('/dashboardnext=../.env', follow_redirects=False)

    assert response.status_code == 403


def test_notifications_surface_actionable_business_signals(client):
    with app.app_context():
        product = Urun.query.first()
        product.stok_miktari = 2
        product.kritik_stok = 5
        db.session.commit()

    response = client.get('/api/notifications')
    data = response.get_json()

    assert response.status_code == 200
    assert data['success'] is True
    assert data['count'] >= 1
    assert any(item['title'] == 'Kritik stok uyarısı' for item in data['notifications'])


def test_notification_preferences_filter_stock_alerts(client):
    with app.app_context():
        product = Urun.query.first()
        product.stok_miktari = 2
        product.kritik_stok = 5
        db.session.commit()

    response = client.post('/api/settings/notifications', json={
        'notify_stock_alerts': False,
        'notify_customer_activity': True,
        'notify_quote_status': True,
        'notify_daily_reports': True,
        'notify_system_updates': True,
        'notify_realtime': True,
        'notify_sound': False,
        'notify_desktop': False,
        'notify_history': True,
        'notification_summary_frequency': 'realtime',
        'notification_report_frequency': 'weekly',
        'quiet_hours_start': '22:00',
        'quiet_hours_end': '08:00',
    })
    assert response.status_code == 200

    response = client.get('/api/notifications')
    data = response.get_json()

    assert response.status_code == 200
    assert data['success'] is True
    assert all(item['title'] != 'Kritik stok uyarısı' for item in data['notifications'])


def test_api_404_returns_json(client):
    response = client.get('/api/does-not-exist')
    data = response.get_json()

    assert response.status_code == 404
    assert data['success'] is False
    assert 'message' in data


def test_backup_download_rejects_unsafe_filename(client):
    response = client.get('/api/settings/backup/download/..%5Csettings.json')
    data = response.get_json()

    assert response.status_code == 400
    assert data['success'] is False


def test_professional_admin_audit_logs_are_tenant_scoped(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        other_user = User.query.filter_by(email='other@example.com').first()
        user.paket_tipi = 'profesyonel'
        db.session.add(AuditLog(user_id=other_user.id, action='FOREIGN_ADMIN_LEAK_CHECK', resource_type='User'))
        db.session.add(AuditLog(user_id=user.id, action='LOCAL_ADMIN_CHECK', resource_type='User'))
        db.session.commit()

    response = client.get('/admin/audit-logs')

    assert response.status_code == 200
    assert b'LOCAL_ADMIN_CHECK' in response.data
    assert b'FOREIGN_ADMIN_LEAK_CHECK' not in response.data


def test_dashboard_renders_without_name_errors(client):
    response = client.get('/dashboard')

    assert response.status_code == 200
    assert 'Başlangıç rehberi'.encode('utf-8') in response.data
    assert 'Kurulumunuzu birkaç adımda tamamlayın'.encode('utf-8') in response.data
    assert 'İlk ürün, ilk satış ve ilk tahsilat'.encode('utf-8') in response.data
    assert '1/3 adım tamamlandı'.encode('utf-8') in response.data


def test_product_filters_render_without_reload_errors(client):
    response = client.get('/urunler?search=Test&category=Elektronik&stock_status=available')

    assert response.status_code == 200
    assert b'Test Urun' in response.data


def test_demo_data_tools_are_hidden_for_regular_users(client):
    product_page = client.get('/urun-ekle')
    assert product_page.status_code == 200
    assert 'Demo \u00dcr\u00fcn Ekle'.encode('utf-8') not in product_page.data

    staff_page = client.get('/personel_ekle')
    assert staff_page.status_code == 200
    assert 'Demo Veri Doldur'.encode('utf-8') not in staff_page.data
    assert 'Demo Doldur'.encode('utf-8') not in staff_page.data

    response = client.post('/urunler/demo-veri', json={})
    assert response.status_code == 403
    assert response.get_json()['success'] is False


def test_product_add_page_can_create_demo_products(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        owner.is_platform_admin = True
        owner.platform_role = 'owner'
        db.session.commit()

    page = client.get('/urun-ekle')
    assert page.status_code == 200
    assert 'Demo Ürün Ekle'.encode('utf-8') in page.data

    response = client.post('/urunler/demo-veri', json={})
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['created_count'] == 11

    with app.app_context():
        products = Urun.query.filter(Urun.barkod.like('DEMO-%')).all()
        assert len(products) == 11
        assert len({product.kategori for product in products}) == 11
        assert 'Ba\u011flant\u0131 Elemanlar\u0131' in {product.kategori for product in products}
        assert '\u0130\u015f G\u00fcvenli\u011fi G\u00f6zl\u00fc\u011f\u00fc' in {product.urun_adi for product in products}
        assert {product.depo_adi for product in products} >= {'Ana Depo', 'Şube Deposu', 'Servis Aracı'}


def test_primary_navigation_pages_render_without_server_errors(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        owner.paket_tipi = 'profesyonel'
        db.session.add(Departman(ad='Operasyon', user_id=owner.id))
        db.session.commit()

    paths = [
        '/dashboard',
        '/urunler',
        '/urun-ekle',
        '/cariler',
        '/cari-ekle',
        '/pos',
        '/nakit',
        '/onmuhasebe/hesaplar',
        '/onmuhasebe/mutabakat',
        '/onmuhasebe/raporlar',
        '/teklifler',
        '/teklif/ekle',
        '/personel',
        '/departmanlar',
        '/izinler',
        '/avanslar',
        '/primler',
        '/iade',
        '/gunluk-satislar',
        '/raporlar',
        '/settings',
        '/admin',
        '/admin/audit-logs',
        '/admin/backup',
        '/admin/settings',
        '/stok/giris',
        '/stok/cikis',
        '/urunler/toplu-fiyat-guncelleme',
    ]

    failures = []
    for path in paths:
        response = client.get(path, follow_redirects=False)
        if response.status_code >= 400:
            failures.append((path, response.status_code))

    assert failures == []


def test_onmuhasebe_hesaplar_shows_default_accounts(client):
    response = client.get('/onmuhasebe/hesaplar')
    assert response.status_code == 200
    assert b'Nakit Kasa' in response.data
    assert b'Banka Hesabi' in response.data
    assert b'POS' in response.data
    assert 'Yeni Para Hesabı'.encode('utf-8') in response.data
    assert 'Giren Para'.encode('utf-8') in response.data
    assert 'Çıkan Para'.encode('utf-8') in response.data
    assert 'Kalan Para'.encode('utf-8') in response.data


def test_onmuhasebe_account_toggle_changes_active_state(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        account = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        assert account is not None
        account_id = account.id
        account.active = True
        db.session.commit()

    response = client.post('/onmuhasebe/hesaplar', data={
        'action': 'toggle',
        'account_id': str(account_id),
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        account = db.session.get(Account, account_id)
        assert account.active is False

    response = client.post('/onmuhasebe/hesaplar', data={
        'action': 'toggle',
        'account_id': str(account_id),
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        account = db.session.get(Account, account_id)
        assert account.active is True


def test_onmuhasebe_hesaplar_allows_quick_cash_movement(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        account = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        assert account is not None
        account_id = account.id
        account.active = True
        db.session.commit()

    response = client.post('/onmuhasebe/hesaplar', data={
        'action': 'quick_tx',
        'account_id': str(account_id),
        'islem_tipi': 'cikis',
        'tutar': '125,50',
        'aciklama': 'Kargo ödemesi',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        tx = CashTransaction.query.filter_by(
            account_id=account_id,
            referans_tip='manual',
            islem_tipi='cikis',
            aciklama='Kargo ödemesi',
        ).first()
        assert tx is not None
        assert tx.tutar == 125.50
        assert tx.odeme_turu == 'Nakit'


def test_onmuhasebe_hesaplar_allows_pos_valor_transfer(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        pos = Account.query.filter_by(user_id=owner.id, name='POS').first()
        bank = Account.query.filter_by(user_id=owner.id, name='Banka Hesabi').first()
        assert pos is not None
        assert bank is not None
        pos.active = True
        bank.active = True
        pos_id = pos.id
        bank_id = bank.id
        db.session.commit()

    response = client.post('/onmuhasebe/hesaplar', data={
        'action': 'quick_tx',
        'account_id': str(pos_id),
        'target_account_id': str(bank_id),
        'islem_tipi': 'transfer',
        'tutar': '575',
        'aciklama': 'POS valör tahsilatı',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        out_tx = CashTransaction.query.filter_by(
            user_id=owner.id,
            account_id=pos_id,
            referans_tip='transfer',
            islem_tipi='cikis',
        ).first()
        in_tx = CashTransaction.query.filter_by(
            user_id=owner.id,
            account_id=bank_id,
            referans_tip='transfer',
            islem_tipi='giris',
        ).first()
        assert out_tx is not None
        assert in_tx is not None
        assert out_tx.tutar == 575.0
        assert in_tx.tutar == 575.0
        assert out_tx.odeme_turu == 'Transfer'
        assert in_tx.odeme_turu == 'Transfer'


def test_onmuhasebe_hesaplar_rejects_manual_pos_movement(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        pos = Account.query.filter_by(user_id=owner.id, name='POS').first()
        assert pos is not None
        pos.active = True
        pos_id = pos.id
        db.session.commit()

    response = client.post('/onmuhasebe/hesaplar', data={
        'action': 'quick_tx',
        'account_id': str(pos_id),
        'islem_tipi': 'giris',
        'tutar': '575',
        'aciklama': 'Yanlis POS girisi',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert CashTransaction.query.filter_by(account_id=pos_id, aciklama='Yanlis POS girisi').first() is None


def test_onmuhasebe_hesaplar_rejects_pos_transfer_to_cash(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        pos = Account.query.filter_by(user_id=owner.id, name='POS').first()
        cash = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        assert pos is not None
        assert cash is not None
        pos.active = True
        cash.active = True
        pos_id = pos.id
        cash_id = cash.id
        db.session.commit()

    response = client.post('/onmuhasebe/hesaplar', data={
        'action': 'quick_tx',
        'account_id': str(pos_id),
        'target_account_id': str(cash_id),
        'islem_tipi': 'transfer',
        'tutar': '575',
        'aciklama': 'Yanlis POS kasa aktarimi',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        assert CashTransaction.query.filter_by(account_id=pos_id, aciklama='Yanlis POS kasa aktarimi').first() is None


def test_card_payment_defaults_to_pos_account(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        assert normalize_payment_method('kart') == 'Kredi Kartı'
        assert default_account_for_payment_method(owner.id, 'Kredi Kartı').type == 'pos'
        assert default_account_for_payment_method(owner.id, 'kart').type == 'pos'
        assert default_account_for_payment_method(owner.id, 'pos').type == 'pos'


def test_nakit_yonetimi_uses_plain_business_labels(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(owner.id)
        kasa = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        assert kasa is not None
        db.session.add_all([
            CashTransaction(
                user_id=owner.id,
                account_id=kasa.id,
                islem_tipi='giris',
                tutar=150,
                odeme_turu='Nakit',
                aciklama='Test gelir',
                referans_tip='manual',
            ),
            CashTransaction(
                user_id=owner.id,
                account_id=kasa.id,
                islem_tipi='cikis',
                tutar=40,
                odeme_turu='Nakit',
                aciklama='Test gider',
                referans_tip='manual',
            ),
        ])
        db.session.commit()

    response = client.get('/nakit')

    assert response.status_code == 200
    assert 'Kasaya Giren'.encode('utf-8') in response.data
    assert 'Kasadan Çıkan'.encode('utf-8') in response.data
    assert 'Kasa Neti'.encode('utf-8') in response.data
    assert 'Para Girişi'.encode('utf-8') in response.data
    assert 'Para Çıkışı'.encode('utf-8') in response.data
    assert '+₺150,00'.encode('utf-8') in response.data
    assert '-₺40,00'.encode('utf-8') in response.data


def test_onmuhasebe_hesap_detay_allows_manual_tx_and_transfer(client):
    # Ensure defaults exist
    resp = client.get('/onmuhasebe/hesaplar')
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        kasa = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        banka = Account.query.filter_by(user_id=owner.id, name='Banka Hesabi').first()
        assert kasa is not None
        assert banka is not None
        kasa_id = kasa.id
        banka_id = banka.id

    # Manual transaction (income)
    resp = client.post(f'/onmuhasebe/hesaplar/{kasa_id}', data={
        'action': 'tx',
        'islem_tipi': 'giris',
        'tutar': '125.50',
        'aciklama': 'Test tahsilat',
        'tarih': '2026-05-18',
    }, follow_redirects=True)
    assert resp.status_code == 200


    assert 'Para Hareketi Ekle'.encode('utf-8') not in resp.data
    assert 'Hareketi Kaydet'.encode('utf-8') not in resp.data

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        tx = CashTransaction.query.filter_by(user_id=owner.id, account_id=kasa_id, referans_tip='manual').first()
        assert tx is not None
        assert abs(tx.tutar - 125.50) < 0.001

    # Transfer to bank
    resp = client.post(f'/onmuhasebe/hesaplar/{kasa_id}', data={
        'action': 'transfer',
        'target_account_id': str(banka_id),
        'tutar': '25',
        'aciklama': 'Test transfer',
        'tarih': '2026-05-18',
    }, follow_redirects=True)
    assert resp.status_code == 200


    assert 'Hesaplar Aras\u0131 Para Aktar'.encode('utf-8') in resp.data
    assert 'Para Giri\u015fi'.encode('utf-8') in resp.data
    assert 'Para \u00c7\u0131k\u0131\u015f\u0131'.encode('utf-8') in resp.data

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        out_tx = CashTransaction.query.filter_by(user_id=owner.id, account_id=kasa_id, referans_tip='transfer', islem_tipi='cikis').first()
        in_tx = CashTransaction.query.filter_by(user_id=owner.id, account_id=banka_id, referans_tip='transfer', islem_tipi='giris').first()
        assert out_tx is not None
        assert in_tx is not None
        assert abs(out_tx.tutar - 25.0) < 0.001
        assert abs(in_tx.tutar - 25.0) < 0.001


def test_cari_tahsilat_can_target_specific_account(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        assert cari is not None
        cari_id = cari.id

    # Visit detail once so default accounts exist
    resp = client.get(f'/cari/{cari_id}')
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        bank = Account.query.filter_by(user_id=owner.id, name='Banka Hesabi').first()
        assert bank is not None
        bank_id = bank.id

    resp = client.post(f'/cari/{cari_id}/tahsilat', data={
        'tutar': '50',
        'tahsilat_turu': 'Havale/EFT',
        'account_id': str(bank_id),
        'aciklama': 'Test banka tahsilat',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        tx = CashTransaction.query.filter_by(user_id=owner.id, referans_tip='cari_tahsilat').order_by(CashTransaction.id.desc()).first()
        assert tx is not None
        assert tx.account_id == bank_id


def test_cari_odeme_creates_cash_out_and_reduces_debt(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        assert cari is not None
        cari.borc = 100.0
        cari.alacak = 0.0
        db.session.commit()
        cari_id = cari.id

    resp = client.get(f'/cari/{cari_id}')
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        kasa = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        assert kasa is not None
        kasa_id = kasa.id

    resp = client.post(f'/cari/{cari_id}/odeme', data={
        'tutar': '40',
        'odeme_turu': 'Nakit',
        'account_id': str(kasa_id),
        'aciklama': 'Test cari odeme',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = db.session.get(Cari, cari_id)
        tx = CashTransaction.query.filter_by(user_id=owner.id, referans_tip='cari_odeme').order_by(CashTransaction.id.desc()).first()
        movement = CariHareket.query.filter_by(user_id=owner.id, cari_id=cari_id, referans_tip='cari_odeme').first()
        assert float(cari.borc or 0) == 60.0
        assert float(cari.alacak or 0) == 0.0
        assert tx is not None
        assert tx.islem_tipi == 'cikis'
        assert tx.account_id == kasa_id
        assert movement is not None
        assert movement.tutar == 40.0


def test_onmuhasebe_mutabakat_creates_adjustment_tx(client):
    resp = client.get('/onmuhasebe/hesaplar')
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        kasa = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        assert kasa is not None
        kasa_id = kasa.id

    # Add a manual income to make expected balance 100
    resp = client.post(f'/onmuhasebe/hesaplar/{kasa_id}', data={
        'action': 'tx',
        'islem_tipi': 'giris',
        'tutar': '100',
        'aciklama': 'Test gelir',
        'tarih': '2026-05-18',
    }, follow_redirects=True)
    assert resp.status_code == 200

    # Counted balance is 90 -> should create 10 outgoing adjustment
    resp = client.post('/onmuhasebe/mutabakat', data={
        'account_id': str(kasa_id),
        'recon_date': '2026-05-18',
        'counted_balance': '90',
        'note': 'Sayim',
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert 'Kasa Sayımı'.encode('utf-8') in resp.data
    assert 'Saydığım Para'.encode('utf-8') in resp.data
    assert 'Sisteme Göre Para'.encode('utf-8') in resp.data
    assert 'Aradaki Fark'.encode('utf-8') in resp.data

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        rec = AccountReconciliation.query.filter_by(user_id=owner.id, account_id=kasa_id).order_by(AccountReconciliation.id.desc()).first()
        assert rec is not None
        assert abs((rec.expected_balance or 0) - 100.0) < 0.001
        assert abs((rec.counted_balance or 0) - 90.0) < 0.001
        assert abs((rec.difference or 0) - (-10.0)) < 0.001

        tx = CashTransaction.query.filter_by(user_id=owner.id, account_id=kasa_id, referans_tip='reconciliation', referans_id=rec.id).first()
        assert tx is not None
        assert tx.islem_tipi == 'cikis'
        assert tx.odeme_turu == 'Kasa Sayım Farkı'
        assert 'Sisteme göre: 100,00'.encode('utf-8').decode('utf-8') in tx.aciklama
        assert 'Saydığım: 90,00'.encode('utf-8').decode('utf-8') in tx.aciklama
        assert abs(tx.tutar - 10.0) < 0.001


def test_full_regression_hirdavat_core_workflow(client):
    # 1) Stock in (manual)
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        assert product is not None
        cari = Cari.query.filter_by(user_id=owner.id).first()
        assert cari is not None
        product_id = product.id
        cari_id = cari.id
        stock_before = float(product.stok_miktari or 0)

    resp = client.post('/stok/giris', data={
        'urun_id': str(product_id),
        'miktar': '5',
        'depo': 'Ana Depo',
        'aciklama': 'Test stok giris',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before + 5.0
        assert StokHareket.query.filter_by(user_id=owner.id, islem_tipi='giris').count() >= 1

    # 2) POS cash sale -> stock decreases, cash tx exists
    with app.app_context():
        product = db.session.get(Urun, product_id)
        stock_before_sale = float(product.stok_miktari or 0)

    resp = client.post('/pos/satis', json={
        'items': [{
            'id': product_id,
            'name': 'Test Urun',
            'price': 100.0,
            'quantity': 1,
        }],
        'kdvRate': 18,
        'discount': 0,
        'customerId': '',
        'paymentMethod': 'cash',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before_sale - 1.0
        assert Satis.query.filter_by(user_id=owner.id).count() >= 1
        assert CashTransaction.query.filter_by(user_id=owner.id, referans_tip='satis').count() >= 1

    # 3) POS credit (veresiye) -> cari alacak increases, no cash tx for that sale
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = db.session.get(Cari, cari_id)
        alacak_before = float(cari.alacak or 0)
        cash_tx_before = CashTransaction.query.filter_by(user_id=owner.id, referans_tip='satis').count()

    resp = client.post('/pos/satis', json={
        'items': [{
            'id': product_id,
            'name': 'Test Urun',
            'price': 100.0,
            'quantity': 1,
        }],
        'kdvRate': 18,
        'discount': 0,
        'customerId': cari_id,
        'paymentMethod': 'credit',
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = db.session.get(Cari, cari_id)
        assert float(cari.alacak or 0) > alacak_before
        cash_tx_after = CashTransaction.query.filter_by(user_id=owner.id, referans_tip='satis').count()
        assert cash_tx_after == cash_tx_before  # veresiye sat?? kasa hareketi yazmamal?

    # 4) Cari tahsilat to bank account -> cash tx account_id = bank
    resp = client.get(f'/cari/{cari_id}')
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        bank = Account.query.filter_by(user_id=owner.id, name='Banka Hesabi').first()
        assert bank is not None
        bank_id = bank.id

    resp = client.post(f'/cari/{cari_id}/tahsilat', data={
        'tutar': '50',
        'tahsilat_turu': 'Havale/EFT',
        'account_id': str(bank_id),
        'aciklama': 'Test banka tahsilat',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        tx = CashTransaction.query.filter_by(user_id=owner.id, referans_tip='cari_tahsilat').order_by(CashTransaction.id.desc()).first()
        assert tx is not None
        assert tx.account_id == bank_id

    # 5) Create offer with one line item
    resp = client.post('/teklif/ekle', data={
        'cari_id': str(cari_id),
        'teklif_no': 'TEST-001',
        'tarih': '2026-05-18',
        'kdv_orani': '18',
        'urunler[]': [str(product_id)],
        'miktarlar[]': ['2'],
        'birimler[]': ['Adet'],
        'fiyatlar[]': ['100'],
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        teklif = Teklif.query.filter_by(user_id=owner.id, teklif_no='TEST-001').first()
        assert teklif is not None
        assert TeklifKalemi.query.filter_by(teklif_id=teklif.id).count() == 1

    # 6) Key report pages render
    assert client.get('/onmuhasebe/raporlar').status_code == 200
    assert client.get('/raporlar').status_code == 200
    assert client.get('/gunluk-satislar').status_code == 200


def test_iade_urun_iadesi_cari_alacak_olustur_does_not_touch_cash(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        assert product is not None
        assert cari is not None
        product_id = product.id
        cari_id = cari.id

        # Simulate customer debt so credit can reduce it
        cari.alacak = 100.0
        cari.borc = 0.0
        stock_before = float(product.stok_miktari or 0)
        db.session.commit()

    resp = client.post('/iade', data={
        'cari_id': str(cari_id),
        'urun_idler[]': [str(product_id)],
        'urun_adlari[]': ['Test Urun'],
        'iade_miktarlari[]': ['1'],
        'iade_turu': 'urun_iadesi',
        'odeme_turu': 'Nakit',
        'iade_sebebi': 'Test iade',
        'alacak_olustur': 'on',
    }, follow_redirects=True)
    assert resp.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = db.session.get(Urun, product_id)
        cari = db.session.get(Cari, cari_id)
        assert float(product.stok_miktari or 0) == stock_before + 1.0
        assert float(cari.alacak or 0) == 0.0
        assert Iade.query.filter_by(user_id=owner.id).count() >= 1
        assert CariHareket.query.filter_by(user_id=owner.id, cari_id=cari_id, islem_tipi='iade').count() >= 1
        assert CashTransaction.query.filter_by(user_id=owner.id, referans_tip='iade').count() == 0


def test_iade_credit_return_updates_cari_statement_balance(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        product_id = product.id
        cari_id = cari.id
        cari.alacak = 100.0
        cari.borc = 0.0
        db.session.add(CariHareket(
            cari_id=cari.id,
            user_id=owner.id,
            islem_tipi='satis',
            tutar=100.0,
            aciklama='Veresiye satis test',
            odeme_turu='Alacak',
            referans_id=501,
            referans_tip='satis'
        ))
        db.session.commit()

    response = client.post('/iade', data={
        'cari_id': str(cari_id),
        'urun_idler[]': [str(product_id)],
        'urun_adlari[]': ['Test Urun'],
        'iade_miktarlari[]': ['1'],
        'iade_turu': 'urun_iadesi',
        'refund_mode': 'credit',
        'iade_sebebi': 'Ekstre iade testi',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = db.session.get(Cari, cari_id)
        iade = Iade.query.filter_by(user_id=owner.id).order_by(Iade.id.desc()).first()
        iade_hareket = CariHareket.query.filter_by(
            cari_id=cari_id,
            referans_tip='iade',
            referans_id=iade.id,
            islem_tipi='iade'
        ).first()
        context = build_cari_ekstre_context(cari, [owner.id])

        assert iade_hareket is not None
        assert float(cari.alacak or 0) == 0.0
        assert context['closing_balance'] == 0.0
        assert context['total_plus'] == 100.0
        assert context['total_minus'] == 100.0
        assert [row['hareket'].islem_tipi for row in context['rows']] == ['satis', 'iade']

    detail_response = client.get(f'/cari/{cari_id}')
    assert detail_response.status_code == 200
    assert 'İade'.encode('utf-8') in detail_response.data
    assert 'Ekstre iade testi'.encode('utf-8') in detail_response.data


def test_iade_urun_iadesi_without_credit_only_restocks(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        product_id = product.id
        cari_id = cari.id
        stock_before = float(product.stok_miktari or 0)
        cari.alacak = 25.0
        cari.borc = 0.0
        db.session.commit()

    response = client.post('/iade', data={
        'cari_id': str(cari_id),
        'urun_idler[]': [str(product_id)],
        'urun_adlari[]': ['Test Urun'],
        'iade_miktarlari[]': ['1'],
        'iade_turu': 'urun_iadesi',
        'odeme_turu': 'Nakit',
        'iade_sebebi': 'Sadece stok iadesi',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = db.session.get(Urun, product_id)
        cari = db.session.get(Cari, cari_id)
        iade = Iade.query.filter_by(user_id=owner.id).order_by(Iade.id.desc()).first()
        assert float(product.stok_miktari or 0) == stock_before + 1
        assert float(cari.alacak or 0) == 25.0
        assert iade is not None
        assert CariHareket.query.filter_by(referans_tip='iade', referans_id=iade.id).count() == 0
        assert CashTransaction.query.filter_by(referans_tip='iade', referans_id=iade.id).count() == 0


def test_iade_para_iadesi_creates_only_cash_out_on_selected_account(client):
    client.get('/iade')
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        bank = Account.query.filter_by(user_id=owner.id, name='Banka Hesabi').first()
        assert product is not None
        assert cari is not None
        assert bank is not None
        product_id = product.id
        cari_id = cari.id
        bank_id = bank.id
        cari.alacak = 100.0
        cari.borc = 0.0
        db.session.commit()

    response = client.post('/iade', data={
        'cari_id': str(cari_id),
        'urun_idler[]': [str(product_id)],
        'urun_adlari[]': ['Test Urun'],
        'iade_miktarlari[]': ['1'],
        'iade_turu': 'para_iadesi',
        'odeme_turu': 'Havale/EFT',
        'account_id': str(bank_id),
        'iade_sebebi': 'Para iadesi test',
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = db.session.get(Cari, cari_id)
        iade = Iade.query.filter_by(user_id=owner.id).order_by(Iade.id.desc()).first()
        cash_tx = CashTransaction.query.filter_by(
            user_id=owner.id,
            referans_tip='iade',
            referans_id=iade.id,
            islem_tipi='cikis',
        ).first()
        cari_move = CariHareket.query.filter_by(
            user_id=owner.id,
            cari_id=cari_id,
            referans_tip='iade',
            referans_id=iade.id,
        ).first()
        assert float(cari.alacak or 0) == 100.0
        assert cash_tx is not None
        assert cash_tx.account_id == bank_id
        assert cash_tx.tutar == 100.0
        assert cari_move is not None
        assert cari_move.islem_tipi == 'iade_bilgi'
        assert cari_move.tutar == 100.0

        context = build_cari_ekstre_context(cari, [owner.id])
        assert any(
            row['hareket'].id == cari_move.id and row['signed'] == 0.0
            for row in context['rows']
        )

    detail_response = client.get(f'/cari/{cari_id}')
    assert detail_response.status_code == 200
    assert 'Para İadesi'.encode('utf-8') in detail_response.data
    assert 'Para iadesi test'.encode('utf-8') in detail_response.data


def test_iade_rejects_invalid_return_type_without_stock_change(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        cari = Cari.query.filter_by(unvan='Test Cari').first()
        product_id = product.id
        cari_id = cari.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/iade', data={
        'cari_id': str(cari_id),
        'urun_idler[]': [str(product_id)],
        'urun_adlari[]': ['Test Urun'],
        'iade_miktarlari[]': ['1'],
        'iade_turu': 'gecersiz_tur',
        'odeme_turu': 'Nakit',
        'iade_sebebi': 'Gecersiz tur test',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before
        assert Iade.query.count() == 0
        assert StokHareket.query.filter_by(islem_tipi='giris').count() == 0


def test_iade_rejects_foreign_account(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        other = User.query.filter_by(email='other@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        foreign_account = Account(user_id=other.id, type='bank', name='Other Bank', currency='TRY', opening_balance=0)
        db.session.add(foreign_account)
        db.session.commit()
        product_id = product.id
        cari_id = cari.id
        foreign_account_id = foreign_account.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/iade', data={
        'cari_id': str(cari_id),
        'urun_idler[]': [str(product_id)],
        'urun_adlari[]': ['Test Urun'],
        'iade_miktarlari[]': ['1'],
        'iade_turu': 'para_iadesi',
        'odeme_turu': 'Havale/EFT',
        'account_id': str(foreign_account_id),
        'iade_sebebi': 'Foreign account test',
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before
        assert Iade.query.count() == 0


def test_credit_sale_cancel_does_not_create_cash_out(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        product_id = product.id
        cari_id = cari.id

    sale_response = client.post('/pos/satis', json={
        'items': [{'id': product_id, 'name': 'Test Urun', 'price': 100, 'quantity': 1}],
        'kdvRate': 18,
        'discount': 0,
        'customerId': cari_id,
        'paymentMethod': 'credit',
    })
    assert sale_response.status_code == 200
    assert sale_response.get_json()['success'] is True

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        sale = Satis.query.filter_by(user_id=owner.id).order_by(Satis.id.desc()).first()
        sale_id = sale.id
        cari = db.session.get(Cari, cari_id)
        assert float(cari.alacak or 0) == 118.0
        cash_before = CashTransaction.query.filter_by(user_id=owner.id).count()

    cancel_response = client.post('/gunluk-satislar', data={'satis_id': str(sale_id)}, follow_redirects=True)
    assert cancel_response.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cash_after = CashTransaction.query.filter_by(user_id=owner.id).count()
        cari = db.session.get(Cari, cari_id)
        sale = db.session.get(Satis, sale_id)
        assert sale.durum == 'iptal'
        assert float(cari.alacak or 0) == 0.0
        cancel_movement = CariHareket.query.filter_by(referans_tip='satis_iptal', referans_id=sale_id).first()
        assert cancel_movement is not None
        assert cancel_movement.aciklama == f'Satış iptali - {sale.fatura_no}'
        assert cancel_movement.odeme_turu == 'İptal'
        assert cash_after == cash_before


def test_sale_cancel_reverses_original_cash_account(client):
    client.get('/onmuhasebe/hesaplar')
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        bank = Account.query.filter_by(user_id=owner.id, name='Banka Hesabi').first()
        product_id = product.id
        bank_id = bank.id

    sale_response = client.post('/pos/satis', json={
        'items': [{'id': product_id, 'name': 'Test Urun', 'price': 100, 'quantity': 1}],
        'kdvRate': 18,
        'discount': 0,
        'customerId': '',
        'paymentMethod': 'Havale/EFT',
        'account_id': bank_id,
    })
    assert sale_response.status_code == 200
    assert sale_response.get_json()['success'] is True

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        sale = Satis.query.filter_by(user_id=owner.id).order_by(Satis.id.desc()).first()
        sale_id = sale.id

    cancel_response = client.post('/gunluk-satislar', data={'satis_id': str(sale_id)}, follow_redirects=True)
    assert cancel_response.status_code == 200

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        reverse_tx = CashTransaction.query.filter_by(
            user_id=owner.id,
            referans_id=sale_id,
            referans_tip='satis_iptal',
            islem_tipi='cikis',
        ).order_by(CashTransaction.id.desc()).first()
        assert reverse_tx is not None
        assert reverse_tx.account_id == bank_id
        assert reverse_tx.aciklama == f'Satış iptali - {sale.fatura_no}'


def test_paid_customer_sale_cancel_does_not_create_cari_reversal(client):
    client.get('/onmuhasebe/hesaplar')
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        kasa = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        product_id = product.id
        cari_id = cari.id
        kasa_id = kasa.id
        stock_before = float(product.stok_miktari or 0)

    sale_response = client.post('/pos/satis', json={
        'items': [{'id': product_id, 'name': 'Test Urun', 'price': 100, 'quantity': 1}],
        'kdvRate': 18,
        'discount': 0,
        'customerId': cari_id,
        'paymentMethod': 'cash',
        'account_id': kasa_id,
    })
    assert sale_response.status_code == 200
    assert sale_response.get_json()['success'] is True

    with app.app_context():
        sale = Satis.query.order_by(Satis.id.desc()).first()
        sale_id = sale.id
        assert CariHareket.query.filter_by(referans_tip='satis', referans_id=sale_id).count() == 0
        assert CashTransaction.query.filter_by(referans_tip='satis', referans_id=sale_id, islem_tipi='giris').count() == 1

    cancel_response = client.post('/gunluk-satislar', data={'satis_id': str(sale_id)}, follow_redirects=True)
    assert cancel_response.status_code == 200

    with app.app_context():
        product = db.session.get(Urun, product_id)
        cari = db.session.get(Cari, cari_id)
        reverse_tx = CashTransaction.query.filter_by(referans_tip='satis_iptal', referans_id=sale_id, islem_tipi='cikis').first()
        assert float(product.stok_miktari or 0) == stock_before
        assert float(cari.alacak or 0) == 0
        assert reverse_tx is not None
        assert reverse_tx.account_id == kasa_id
        assert CariHareket.query.filter_by(referans_tip='satis_iptal', referans_id=sale_id).count() == 0


def test_cari_ekstre_renders_and_csv_downloads(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        assert cari is not None
        cari_id = cari.id

    resp = client.get(f'/cari/{cari_id}/ekstre')
    assert resp.status_code == 200
    assert 'Cari Ekstresi'.encode('utf-8') in resp.data
    assert 'Dönem Başı Bakiye'.encode('utf-8') in resp.data
    assert 'Veresiye Satışlar'.encode('utf-8') in resp.data
    assert 'Tahsilatlar'.encode('utf-8') in resp.data
    assert 'Dönem Sonu Bakiye'.encode('utf-8') in resp.data
    assert 'Cari Hareketleri'.encode('utf-8') in resp.data
    assert 'Kalan Bakiye'.encode('utf-8') in resp.data
    assert b'Acilis Bakiye' not in resp.data
    assert 'A??l?? Bakiye'.encode('utf-8') not in resp.data
    assert b'@media print' in resp.data
    assert b'.ekstre-print-page' in resp.data
    assert b'.print-ekstre-header' in resp.data
    assert b'overflow: visible !important' in resp.data
    assert b'#mainContent' in resp.data
    assert b'.app-content' in resp.data

    print_resp = client.get(f'/cari/{cari_id}/ekstre/yazdir')
    assert print_resp.status_code == 200
    assert 'Cari Ekstresi'.encode('utf-8') in print_resp.data
    assert 'window.print()'.encode('utf-8') in print_resp.data
    assert b'<table>' in print_resp.data

    resp = client.get(f'/cari/{cari_id}/ekstre.csv')
    assert resp.status_code == 200
    assert 'text/csv' in resp.headers.get('Content-Type', '')


def test_cari_ekstre_without_date_filter_does_not_double_count_running_balance(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari(unvan='Ekstre Denge Cari', tipi='Müşteri', user_id=owner.id)
        db.session.add(cari)
        db.session.flush()

        db.session.add_all([
            CariHareket(
                cari_id=cari.id,
                user_id=owner.id,
                islem_tipi='satis',
                tutar=200,
                odeme_turu='Alacak',
                referans_id=9001,
                referans_tip='satis'
            ),
            CariHareket(
                cari_id=cari.id,
                user_id=owner.id,
                islem_tipi='tahsilat',
                tutar=50,
                odeme_turu='Nakit',
                referans_id=9002,
                referans_tip='cari_tahsilat'
            ),
        ])
        db.session.commit()

        context = build_cari_ekstre_context(cari, [owner.id])

        assert context['opening_balance'] == 0.0
        assert context['closing_balance'] == 150.0
        assert context['has_balance_mismatch'] is False
        assert len(context['rows']) == 2
        assert context['rows'][-1]['balance'] == 150.0


def test_dashboard_and_reports_ignore_cancelled_sales(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        product_name = product.urun_adi
        fast_product = Urun(
            barkod='RPT-FAST-001',
            urun_adi='Rapor Cok Satan',
            kategori='Rapor Test',
            birim='Adet',
            alis_fiyati=5,
            satis_fiyati=10,
            stok_miktari=20,
            kritik_stok=2,
            depo_adi='Ana Depo',
            user_id=owner.id,
        )
        db.session.add(fast_product)
        db.session.flush()
        active_sale = Satis(
            fatura_no='RPT-ACTIVE-001',
            cari_id=None,
            user_id=owner.id,
            ara_toplam=100,
            kdv_orani=18,
            kdv_tutar=18,
            genel_toplam=118,
            durum='tamamlandi',
        )
        fast_sale = Satis(
            fatura_no='RPT-FAST-001',
            cari_id=None,
            user_id=owner.id,
            ara_toplam=50,
            kdv_orani=0,
            kdv_tutar=0,
            genel_toplam=50,
            durum='tamamlandi',
        )
        cancelled_sale = Satis(
            fatura_no='RPT-CANCEL-001',
            cari_id=None,
            user_id=owner.id,
            ara_toplam=500,
            kdv_orani=18,
            kdv_tutar=90,
            genel_toplam=590,
            durum='iptal',
        )
        db.session.add_all([active_sale, fast_sale, cancelled_sale])
        db.session.flush()
        db.session.add(SatisKalemi(
            satis_id=active_sale.id,
            urun_id=product.id,
            urun_adi=product.urun_adi,
            miktar=1,
            birim='Adet',
            birim_fiyat=100,
            toplam=100,
        ))
        db.session.add(SatisKalemi(
            satis_id=fast_sale.id,
            urun_id=fast_product.id,
            urun_adi=fast_product.urun_adi,
            miktar=5,
            birim='Adet',
            birim_fiyat=10,
            toplam=50,
        ))
        db.session.add(SatisKalemi(
            satis_id=cancelled_sale.id,
            urun_id=product.id,
            urun_adi='Iptal Urun',
            miktar=1,
            birim='Adet',
            birim_fiyat=500,
            toplam=500,
        ))
        db.session.commit()

    dashboard_response = client.get('/dashboard')
    reports_response = client.get('/raporlar')

    assert dashboard_response.status_code == 200
    assert reports_response.status_code == 200
    assert b'RPT-CANCEL-001' not in dashboard_response.data
    assert b'Iptal Urun' not in reports_response.data
    assert 'İşletme Raporları'.encode('utf-8') in reports_response.data
    assert 'Bu Ayki Satış'.encode('utf-8') in reports_response.data
    assert 'Carilerden Alacak'.encode('utf-8') in reports_response.data
    assert 'En Çok Satılan Ürünler'.encode('utf-8') in reports_response.data
    reports_text = reports_response.data.decode('utf-8')
    assert reports_text.index('Rapor Cok Satan') < reports_text.index(product_name)
    assert '168,00'.encode('utf-8') in dashboard_response.data
    assert '590,00'.encode('utf-8') not in reports_response.data


def test_business_reports_print_layout_prints_full_report(client):
    response = client.get('/raporlar')

    assert response.status_code == 200
    assert b'@media print' in response.data
    assert b'@page' in response.data
    assert b'.report-print-page' in response.data
    assert b'.print-report-header' in response.data
    assert b'overflow: visible !important' in response.data
    assert b'#mainContent' in response.data
    assert b'.app-content' in response.data
    assert b'no-print flex flex-col' in response.data


def test_daily_sales_renders_payment_method_labels(client):
    client.get('/onmuhasebe/hesaplar')
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        pos_account = Account.query.filter_by(user_id=owner.id, name='POS').first()

        card_sale = Satis(
            fatura_no='DAY-CARD-001',
            user_id=owner.id,
            tarih=datetime.now(timezone.utc),
            ara_toplam=100,
            kdv_orani=0,
            kdv_tutar=0,
            genel_toplam=100,
            durum='tamamlandi',
        )
        credit_sale = Satis(
            fatura_no='DAY-CREDIT-001',
            user_id=owner.id,
            cari_id=cari.id,
            tarih=datetime.now(timezone.utc),
            ara_toplam=200,
            kdv_orani=0,
            kdv_tutar=0,
            genel_toplam=200,
            durum='tamamlandi',
        )
        db.session.add_all([card_sale, credit_sale])
        db.session.flush()
        db.session.add_all([
            SatisKalemi(satis_id=card_sale.id, urun_id=product.id, urun_adi='Kartli Urun', miktar=1, birim='Adet', birim_fiyat=100, toplam=100),
            SatisKalemi(satis_id=credit_sale.id, urun_id=product.id, urun_adi='Veresiye Urun', miktar=1, birim='Adet', birim_fiyat=200, toplam=200),
            CashTransaction(user_id=owner.id, account_id=pos_account.id, islem_tipi='giris', tutar=100, odeme_turu='Kredi Kartı', referans_id=card_sale.id, referans_tip='satis'),
            CariHareket(cari_id=cari.id, user_id=owner.id, islem_tipi='satis', tutar=200, odeme_turu='Alacak', referans_id=credit_sale.id, referans_tip='satis'),
        ])
        db.session.commit()

    response = client.get('/gunluk-satislar')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'DAY-CARD-001' in text
    assert 'Kredi Kartı' in text
    assert 'DAY-CREDIT-001' in text
    assert 'Veresiye' in text


def test_daily_sales_renders_sale_time_in_istanbul_timezone(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        sale = Satis(
            fatura_no='TZ-SALE-001',
            user_id=owner.id,
            tarih=datetime(2026, 6, 18, 7, 6, tzinfo=timezone.utc),
            ara_toplam=100,
            kdv_orani=0,
            kdv_tutar=0,
            genel_toplam=100,
            durum='tamamlandi',
        )
        db.session.add(sale)
        db.session.flush()
        db.session.add(SatisKalemi(
            satis_id=sale.id,
            urun_id=product.id,
            urun_adi='Saat Test Urunu',
            miktar=1,
            birim='Adet',
            birim_fiyat=100,
            toplam=100,
        ))
        db.session.commit()

    response = client.get('/gunluk-satislar?tarih=2026-06-18')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'TZ-SALE-001' in text
    assert '10:06' in text
    assert '07:06' not in text


def test_sale_receipt_page_renders_sale_time_in_istanbul_timezone(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        sale = Satis(
            fatura_no='TZ-RECEIPT-001',
            user_id=owner.id,
            tarih=datetime(2026, 6, 18, 7, 6, tzinfo=timezone.utc),
            ara_toplam=100,
            kdv_orani=0,
            kdv_tutar=0,
            genel_toplam=100,
            durum='tamamlandi',
        )
        db.session.add(sale)
        db.session.flush()
        db.session.add(SatisKalemi(
            satis_id=sale.id,
            urun_id=product.id,
            urun_adi='Fis Saat Test Urunu',
            miktar=1,
            birim='Adet',
            birim_fiyat=100,
            toplam=100,
        ))
        db.session.commit()
        sale_id = sale.id

    response = client.get(f'/satis/{sale_id}/fis')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'TZ-RECEIPT-001' in text
    assert '18.06.2026 10:06' in text
    assert '18.06.2026 07:06' not in text


def test_pos_receipt_route_renders_shared_print_template(client):
    response = client.post('/pos/fis', data={
        'receipt_payload': json.dumps({
            'fatura_no': 'POS-PRINT-001',
            'date_iso': '2026-06-18T07:06:00+00:00',
            'payment_method': 'Nakit',
            'subtotal': 100,
            'vat_total': 0,
            'discount': 0,
            'total': 100,
            'items': [{'name': 'Ortak Fiş Ürünü', 'qty': 1, 'unit': 'Adet', 'unit_price': 100, 'line_total': 100}],
        }),
        'sale_payload': json.dumps({
            'receivedAmount': 120,
            'customer_name': '',
        }),
    })
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'POS-PRINT-001' in text
    assert 'Satış Fişi' in text
    assert 'Ortak Fiş Ürünü' in text
    assert 'Alınan' in text
    assert 'Para üstü' in text


def test_onmuhasebe_reports_net_cash_after_sale_and_cancel(client):
    client.get('/onmuhasebe/hesaplar')
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        account = Account.query.filter_by(user_id=owner.id, name='Nakit Kasa').first()
        sale_id = 9991
        db.session.add(CashTransaction(
            user_id=owner.id,
            account_id=account.id,
            islem_tipi='giris',
            tutar=118,
            odeme_turu='Nakit',
            referans_id=sale_id,
            referans_tip='satis',
        ))
        db.session.add(CashTransaction(
            user_id=owner.id,
            account_id=account.id,
            islem_tipi='cikis',
            tutar=118,
            odeme_turu='Nakit',
            referans_id=sale_id,
            referans_tip='satis_iptal',
        ))
        db.session.commit()

    response = client.get('/onmuhasebe/raporlar')

    assert response.status_code == 200
    assert 'Para Raporları'.encode('utf-8') in response.data
    assert 'Giren Para'.encode('utf-8') in response.data
    assert 'Çıkan Para'.encode('utf-8') in response.data
    assert 'Kalan Para'.encode('utf-8') in response.data
    assert 'Kasa Sayım Farkı'.encode('utf-8') in response.data
    assert '118,00'.encode('utf-8') in response.data
    assert '0,00'.encode('utf-8') in response.data


def test_templates_do_not_hardcode_internal_app_host():
    offenders = []
    for template in Path('templates').rglob('*.html'):
        text = template.read_text(encoding='utf-8', errors='replace')
        if 'http://10.250.1.55:5000' in text or 'http://127.0.0.1:5000' in text:
            offenders.append(str(template))

    assert offenders == []


def test_confirmed_forms_do_not_trigger_loading_before_confirmation():
    text = Path('templates/_base.html').read_text(encoding='utf-8')

    assert 'if (event.defaultPrevented) return;' in text
    assert 'form.dataset.confirmed = \'true\';' in text


def test_personel_department_filter_uses_department_id(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        departman = Departman(ad='Operasyon', user_id=user.id)
        db.session.add(departman)
        db.session.flush()
        db.session.add(Personel(
            sicil_no='P-001',
            ad='Ayse',
            soyad='Yilmaz',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            departman_id=departman.id,
            pozisyon='Uzman',
            telefon='5551234567',
            user_id=user.id
        ))
        db.session.commit()
        departman_id = departman.id

    response = client.get('/personel')

    assert response.status_code == 200
    assert f'data-departman="{departman_id}"'.encode() in response.data
    assert b'data-search=' in response.data


def test_personel_table_uses_items_per_page_preference(client):
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/preferences', json={'items_per_page': '10'})
        assert response.status_code == 200
        assert response.get_json()['success'] is True

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            for index in range(12):
                db.session.add(Personel(
                    sicil_no=f'PG-{index:02d}',
                    ad=f'AyarPersonel{index:02d}',
                    soyad='Sayfalama',
                    ise_giris_tarihi=date(2026, 1, 1),
                    calisma_durumu='Aktif',
                    pozisyon='Test',
                    user_id=user.id,
                ))
            db.session.commit()

        first_page = client.get('/personel')
        assert first_page.status_code == 200
        assert 'Sayfa başına 10'.encode('utf-8') in first_page.data
        assert b'AyarPersonel00' in first_page.data
        assert b'AyarPersonel09' in first_page.data
        assert b'AyarPersonel10' not in first_page.data

        second_page = client.get('/personel?page=2')
        assert second_page.status_code == 200
        assert b'AyarPersonel10' in second_page.data
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_personel_search_finds_records_beyond_current_page(client):
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        response = client.post('/api/settings/preferences', json={'items_per_page': '10'})
        assert response.status_code == 200
        assert response.get_json()['success'] is True

        with app.app_context():
            user = User.query.filter_by(email='test@example.com').first()
            for index in range(12):
                db.session.add(Personel(
                    sicil_no=f'PS-{index:02d}',
                    ad=f'PersonelArama{index:02d}',
                    soyad='Sayfalama',
                    ise_giris_tarihi=date(2026, 1, 1),
                    calisma_durumu='Aktif',
                    pozisyon='Test',
                    user_id=user.id,
                ))
            db.session.commit()

        first_page = client.get('/personel')
        assert first_page.status_code == 200
        assert b'PersonelArama10' not in first_page.data

        search_response = client.get('/personel?search=PersonelArama10')
        assert search_response.status_code == 200
        assert b'PersonelArama10' in search_response.data
        assert 'Toplam 1 kayıt'.encode('utf-8') in search_response.data
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_personel_detail_renders_work_duration(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-DETAIL',
            ad='Detay',
            soyad='Kontrol',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Uzman',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.commit()
        personel_id = personel.id

    response = client.get(f'/personel_detay/{personel_id}')

    assert response.status_code == 200
    assert b'Detay' in response.data


def test_personel_list_shows_approved_active_leave_as_on_leave(client):
    today = date.today()
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-LEAVE',
            ad='Izinli',
            soyad='Personel',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        db.session.add(Izin(
            personel_id=personel.id,
            izin_tipi='Yıllık İzin',
            baslangic_tarihi=today,
            bitis_tarihi=today,
            gun_sayisi=1,
            onay_durumu='Onaylandı',
            user_id=user.id
        ))
        db.session.commit()
        personel_id = personel.id

    response = client.get('/personel')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'data-durum="İzinli"' in text
    assert 'İzinli' in text
    assert today.strftime('%d.%m.%Y') in text

    api_response = client.get(f'/api/personel/{personel_id}')
    data = api_response.get_json()
    assert data['calisma_durumu'] == 'İzinli'
    assert data['kayitli_calisma_durumu'] == 'Aktif'
    assert data['aktif_izin']['izin_tipi'] == 'Yıllık İzin'


def test_leave_create_rejects_overlapping_leave(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-OVERLAP',
            ad='Cakisan',
            soyad='Izin',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        db.session.add(Izin(
            personel_id=personel.id,
                izin_tipi='Yıllık İzin',
            baslangic_tarihi=date(2026, 6, 10),
            bitis_tarihi=date(2026, 6, 12),
            gun_sayisi=3,
            onay_durumu='Beklemede',
            user_id=user.id
        ))
        db.session.commit()
        personel_id = personel.id

    response = client.post('/izin_ekle', data={
        'personel_id': str(personel_id),
        'izin_tipi': 'Mazeret İzni',
        'baslangic_tarihi': '2026-06-11',
        'bitis_tarihi': '2026-06-13',
        'aciklama': 'Çakışma kontrolü'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert 'aynı tarih aralığında'.encode('utf-8') in response.data
    with app.app_context():
        assert Izin.query.filter_by(personel_id=personel_id).count() == 1


def test_leave_reject_records_decision_note(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-REJECT',
            ad='Red',
            soyad='Kontrol',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        izin = Izin(
            personel_id=personel.id,
            izin_tipi='Mazeret ?zni',
            baslangic_tarihi=date(2026, 7, 1),
            bitis_tarihi=date(2026, 7, 1),
            gun_sayisi=1,
            onay_durumu='Beklemede',
            user_id=user.id
        )
        db.session.add(izin)
        db.session.commit()
        izin_id = izin.id

    response = client.post(f'/izin_reddet/{izin_id}', data={'karar_notu': 'Eksik evrak'}, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        izin = db.session.get(Izin, izin_id)
        assert izin.onay_durumu == 'Reddedildi'
        assert 'Red: Eksik evrak' in izin.aciklama


def test_leave_cancel_removes_active_leave_from_personel_status(client):
    today = date.today()
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-CANCEL',
            ad='Iptal',
            soyad='Kontrol',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        izin = Izin(
            personel_id=personel.id,
                izin_tipi='Yıllık İzin',
            baslangic_tarihi=today,
            bitis_tarihi=today,
            gun_sayisi=1,
                onay_durumu='Onaylandı',
            user_id=user.id
        )
        db.session.add(izin)
        db.session.commit()
        izin_id = izin.id
        personel_id = personel.id

    response = client.post(f'/izin_iptal/{izin_id}', data={'karar_notu': 'Plan değişti'}, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        izin = db.session.get(Izin, izin_id)
        assert izin.onay_durumu == 'İptal Edildi'
        assert 'İptal: Plan değişti' in izin.aciklama

    api_response = client.get(f'/api/personel/{personel_id}')
    assert api_response.get_json()['calisma_durumu'] == 'Aktif'

    detail_response = client.get(f'/personel_detay/{personel_id}')
    detail_text = detail_response.get_data(as_text=True)
    assert detail_response.status_code == 200
    assert 'İzin Geçmişi' in detail_text
    assert 'İptal Edildi' in detail_text


def test_personel_detail_renders_payroll_summary_with_primes_and_advances(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-PAYROLL',
            ad='Bordro',
            soyad='Kontrol',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=20000,
            iban='TR000000000000000000000001',
            banka_adi='Test Bank',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        db.session.add(Prim(
            personel_id=personel.id,
            prim_tipi='Satış Primi',
            tutar=1500,
            donem='2026-06',
            user_id=user.id
        ))
        db.session.add(Avans(
            personel_id=personel.id,
            tutar=500,
            kesinti_turu='Maaştan',
            taksit_sayisi=1,
            durum='Beklemede',
            user_id=user.id,
            talep_tarihi=datetime(2026, 6, 10, tzinfo=timezone.utc)
        ))
        db.session.commit()
        personel_id = personel.id

    response = client.get(f'/personel_detay/{personel_id}?period=2026-06')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Bordro Ön İzleme' in text
    assert '2026-06 dönemi net ödeme özeti' in text
    assert 'Avans Geçmişi' in text
    assert 'Prim Geçmişi' in text
    assert f'/personel_detay/{personel_id}/bordro?period=2026-06' in text
    assert '₺20.000,00' in text
    assert '₺1.500,00' in text
    assert '₺500,00' in text
    assert '₺21.000,00' in text
    assert 'IBAN bilgisi eksik' not in text


def test_personel_payroll_print_page_renders_payslip(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-SLIP',
            ad='Bordro',
            soyad='Cikti',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Usta',
            maas=18000,
            iban='TR000000000000000000000002',
            banka_adi='Test Bank',
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        db.session.add(Prim(
            personel_id=personel.id,
            prim_tipi='Performans',
            tutar=2000,
            donem='2026-06',
            user_id=user.id
        ))
        db.session.add(Avans(
            personel_id=personel.id,
            tutar=750,
            kesinti_turu='Maaştan',
            taksit_sayisi=1,
            durum='Ödendi',
            user_id=user.id,
            talep_tarihi=datetime(2026, 6, 5, tzinfo=timezone.utc)
        ))
        db.session.commit()
        personel_id = personel.id

    response = client.get(f'/personel_detay/{personel_id}/bordro?period=2026-06')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Maaş Bordrosu' in text
    assert 'Bordro Cikti' in text
    assert '2026-06 maaş ödemesi' in text
    assert 'Performans' in text
    assert 'Avans Kesintisi' in text
    assert '₺19.250,00' in text
    assert 'window.print()' in text
    assert '@media print' in text


def test_bulk_payroll_page_renders_totals_and_bank_csv(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel_one = Personel(
            sicil_no='P-BULK-1',
            ad='Toplu',
            soyad='Bir',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=10000,
            iban='TR000000000000000000000101',
            banka_adi='Test Bank',
            user_id=user.id
        )
        personel_two = Personel(
            sicil_no='P-BULK-2',
            ad='Toplu',
            soyad='Iki',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Usta',
            maas=15000,
            iban='',
            banka_adi='',
            user_id=user.id
        )
        db.session.add_all([personel_one, personel_two])
        db.session.flush()
        db.session.add(Prim(
            personel_id=personel_one.id,
            prim_tipi='Satış',
            tutar=1000,
            donem='2026-06',
            user_id=user.id
        ))
        db.session.add(Avans(
            personel_id=personel_two.id,
            tutar=500,
            kesinti_turu='Maaştan',
            taksit_sayisi=1,
            durum='Beklemede',
            user_id=user.id,
            talep_tarihi=datetime(2026, 6, 15, tzinfo=timezone.utc)
        ))
        db.session.commit()

    response = client.get('/personel/bordro/toplu?period=2026-06')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Toplu Maaş Bordrosu' in text
    assert '2026-06 dönemi toplu ödeme listesi' in text
    assert 'Toplu Bir' in text
    assert 'Toplu Iki' in text
    assert '₺25.500,00' in text
    assert '1 personelin IBAN bilgisi eksik' in text
    assert '/personel/bordro/banka-listesi.csv?period=2026-06' in text

    csv_response = client.get('/personel/bordro/banka-listesi.csv?period=2026-06')
    csv_text = csv_response.get_data(as_text=True)

    assert csv_response.status_code == 200
    assert 'text/csv' in csv_response.headers.get('Content-Type', '')
    assert 'maas-banka-listesi-2026-06.csv' in csv_response.headers.get('Content-Disposition', '')
    assert 'Dönem;Ad Soyad;Sicil No;Banka;IBAN;Açıklama;Net Tutar' in csv_text
    assert '2026-06;Toplu Bir;P-BULK-1;Test Bank;TR000000000000000000000101;2026-06 maaş Ödemesi;11000,00' in csv_text
    assert '2026-06;Toplu Iki;P-BULK-2;;;2026-06 maaş Ödemesi;14500,00' in csv_text


def test_bulk_payroll_payment_creates_payslips_and_cash_out_once(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(user.id)
        bank = Account.query.filter_by(user_id=user.id, type='bank').first()
        personel_one = Personel(
            sicil_no='P-PAY-1',
            ad='Odeme',
            soyad='Bir',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=12000,
            iban='TR000000000000000000000201',
            banka_adi='Test Bank',
            user_id=user.id
        )
        personel_two = Personel(
            sicil_no='P-PAY-2',
            ad='Odeme',
            soyad='Iki',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Usta',
            maas=8000,
            iban='TR000000000000000000000202',
            banka_adi='Test Bank',
            user_id=user.id
        )
        db.session.add_all([personel_one, personel_two])
        db.session.flush()
        db.session.add(Prim(
            personel_id=personel_one.id,
            prim_tipi='Satış',
            tutar=1000,
            donem='2026-06',
            user_id=user.id
        ))
        db.session.add(Avans(
            personel_id=personel_two.id,
            tutar=500,
            kesinti_turu='Maaştan',
            taksit_sayisi=1,
            durum='Ödendi',
            user_id=user.id,
            talep_tarihi=datetime(2026, 6, 7, tzinfo=timezone.utc)
        ))
        db.session.commit()
        bank_id = bank.id

    response = client.post('/personel/bordro/toplu/ode', data={
        'period': '2026-06',
        'account_id': str(bank_id),
    }, follow_redirects=True)

    assert response.status_code == 200
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        payslips = MaasKaydi.query.filter_by(user_id=user.id, ay='2026-06', odeme_durumu='Ödendi').all()
        assert len(payslips) == 2
        assert sorted(round(p.net_ucret, 2) for p in payslips) == [7500.0, 13000.0]
        tx = CashTransaction.query.filter_by(user_id=user.id, referans_tip='maas_odeme').first()
        assert tx is not None
        assert tx.account_id == bank_id
        assert tx.islem_tipi == 'cikis'
        assert round(tx.tutar, 2) == 20500.0
        first_tx_id = tx.id

    second_response = client.post('/personel/bordro/toplu/ode', data={
        'period': '2026-06',
        'account_id': str(bank_id),
    }, follow_redirects=True)

    assert second_response.status_code == 200
    assert 'ödenecek yeni maaş kaydı bulunmuyor'.encode('utf-8') in second_response.data
    second_text = second_response.get_data(as_text=True)
    assert 'Bu dönem için kayıtlı maaş ödeme hareketleri' in second_text
    assert '-₺20.500,00' in second_text
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        assert CashTransaction.query.filter_by(user_id=user.id, referans_tip='maas_odeme').count() == 1
        assert db.session.get(CashTransaction, first_tx_id) is not None


def test_payroll_records_page_lists_paid_payslips_by_period(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        personel = Personel(
            sicil_no='P-RECORD',
            ad='Kayit',
            soyad='Bordro',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=9000,
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        db.session.add(MaasKaydi(
            personel_id=personel.id,
            ay='2026-06',
            yil=2026,
            brut_ucret=9500,
            net_ucret=9000,
            diger_kesintiler=500,
            odeme_durumu='Ödendi',
            odeme_tarihi=datetime(2026, 6, 30, tzinfo=timezone.utc),
            user_id=user.id
        ))
        db.session.add(MaasKaydi(
            personel_id=personel.id,
            ay='2026-05',
            yil=2026,
            brut_ucret=9000,
            net_ucret=9000,
            diger_kesintiler=0,
            odeme_durumu='Ödendi',
            odeme_tarihi=datetime(2026, 5, 31, tzinfo=timezone.utc),
            user_id=user.id
        ))
        db.session.commit()
        personel_id = personel.id

    response = client.get('/personel/bordro/kayitlar?period=2026-06')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Bordro Kayıtları' in text
    assert 'Kayit Bordro' in text
    assert '2026-06' in text
    assert '₺9.500,00' in text
    assert '₺9.000,00' in text
    assert f'/personel_detay/{personel_id}/bordro?period=2026-06' in text
    assert f'/personel_detay/{personel_id}/bordroperiod=2026-05' not in text


def test_payroll_records_page_shows_finance_trace_for_period(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(user.id)
        bank = Account.query.filter_by(user_id=user.id, type='bank').first()
        personel = Personel(
            sicil_no='P-TRACE',
            ad='Finans',
            soyad='Iz',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=7000,
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        db.session.add(MaasKaydi(
            personel_id=personel.id,
            ay='2026-06',
            yil=2026,
            brut_ucret=7000,
            net_ucret=7000,
            diger_kesintiler=0,
            odeme_durumu='Ödendi',
            odeme_tarihi=datetime(2026, 6, 30, tzinfo=timezone.utc),
            user_id=user.id
        ))
        db.session.add(CashTransaction(
            user_id=user.id,
            account_id=bank.id,
            tarih=datetime(2026, 6, 30, tzinfo=timezone.utc),
            islem_tipi='cikis',
            tutar=7000,
            odeme_turu='Havale/EFT',
            aciklama='2026-06 toplu maaş ödemesi (1 personel)',
            referans_tip='maas_odeme',
        ))
        db.session.commit()

    response = client.get('/personel/bordro/kayitlar?period=2026-06')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Finans İzi' in text
    assert '2026-06 dönemi ödeme hareketleri' in text
    assert 'Banka Hesabi' in text
    assert '2026-06 toplu maaş ödemesi (1 personel)' in text
    assert '-₺7.000,00' in text


def test_advance_payment_creates_cash_out_and_payroll_deduction(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(user.id)
        cash_account = Account.query.filter_by(user_id=user.id, type='cash').first()
        personel = Personel(
            sicil_no='P-ADVANCE',
            ad='Avans',
            soyad='Odeme',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=10000,
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        avans = Avans(
            personel_id=personel.id,
            tutar=1200,
            kesinti_turu='Maaştan',
            taksit_sayisi=1,
            durum='Beklemede',
            aciklama='Talep notu',
            user_id=user.id,
            talep_tarihi=datetime(2026, 6, 8, tzinfo=timezone.utc)
        )
        db.session.add(avans)
        db.session.commit()
        avans_id = avans.id
        account_id = cash_account.id
        personel_id = personel.id

    response = client.post(f'/avans_ode/{avans_id}', data={
        'account_id': str(account_id),
        'odeme_notu': 'Nakit verildi'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert 'Avans Ödemesi kaydedildi ve finans çıkışı oluşturuldu.'.encode('utf-8') in response.data
    with app.app_context():
        avans = db.session.get(Avans, avans_id)
        assert avans.durum == 'Ödendi'
        assert 'Ödeme notu: Nakit verildi' in avans.aciklama
        tx = CashTransaction.query.filter_by(referans_tip='personel_avans', referans_id=avans_id).first()
        assert tx is not None
        assert tx.account_id == account_id
        assert tx.islem_tipi == 'cikis'
        assert tx.tutar == 1200

    detail_response = client.get(f'/personel_detay/{personel_id}?period={date.today().strftime("%Y-%m")}')
    text = detail_response.get_data(as_text=True)
    assert detail_response.status_code == 200
    assert 'Avans Kesintisi' in text
    assert '₺1.200,00' in text
    assert '₺8.800,00' in text


def test_cash_paid_prime_creates_cash_out_and_is_excluded_from_payroll(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(user.id)
        bank = Account.query.filter_by(user_id=user.id, type='bank').first()
        personel = Personel(
            sicil_no='P-PRIME',
            ad='Prim',
            soyad='Odeme',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Satış',
            maas=10000,
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        prim = Prim(
            personel_id=personel.id,
            prim_tipi='Satış Primi',
            tutar=1500,
            donem=date.today().strftime('%Y-%m'),
            user_id=user.id
        )
        db.session.add(prim)
        db.session.commit()
        prim_id = prim.id
        personel_id = personel.id
        bank_id = bank.id

    response = client.post(f'/prim_ode/{prim_id}', data={
        'account_id': str(bank_id),
        'odeme_notu': 'Peşin ödendi'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert 'Prim peşin Ödendi ve finans çıkışı oluşturuldu.'.encode('utf-8') in response.data
    with app.app_context():
        prim = db.session.get(Prim, prim_id)
        assert 'Peşin Ödeme notu: Peşin ödendi' in prim.aciklama
        tx = CashTransaction.query.filter_by(referans_tip='personel_prim', referans_id=prim_id).first()
        assert tx is not None
        assert tx.account_id == bank_id
        assert tx.islem_tipi == 'cikis'
        assert tx.tutar == 1500

    detail_response = client.get(f'/personel_detay/{personel_id}?period={date.today().strftime("%Y-%m")}')
    text = detail_response.get_data(as_text=True)
    assert detail_response.status_code == 200
    assert 'Bu Ay Prim' in text
    assert '₺0,00' in text
    assert '₺10.000,00' in text

    primler_response = client.get('/primler')
    primler_text = primler_response.get_data(as_text=True)
    assert 'Peşin ödendi' in primler_text


def test_personel_detail_shows_finance_history_timeline(client):
    with app.app_context():
        user = User.query.filter_by(email='test@example.com').first()
        ensure_default_accounts_for_user(user.id)
        bank = Account.query.filter_by(user_id=user.id, type='bank').first()
        personel = Personel(
            sicil_no='P-FINANCE',
            ad='Finans',
            soyad='Personel',
            ise_giris_tarihi=date(2026, 1, 1),
            calisma_durumu='Aktif',
            pozisyon='Kasiyer',
            maas=10000,
            user_id=user.id
        )
        db.session.add(personel)
        db.session.flush()
        avans = Avans(
            personel_id=personel.id,
            tutar=500,
            kesinti_turu='Maa?tan',
            taksit_sayisi=1,
            durum='Ödendi',
            user_id=user.id,
            talep_tarihi=datetime(2026, 6, 5, tzinfo=timezone.utc)
        )
        prim = Prim(
            personel_id=personel.id,
            prim_tipi='Satış',
            tutar=750,
            donem='2026-06',
            user_id=user.id
        )
        db.session.add_all([avans, prim])
        db.session.flush()
        db.session.add(MaasKaydi(
            personel_id=personel.id,
            ay='2026-06',
            yil=2026,
            brut_ucret=10000,
            net_ucret=9500,
            diger_kesintiler=500,
            odeme_durumu='Ödendi',
            odeme_tarihi=datetime(2026, 6, 30, tzinfo=timezone.utc),
            user_id=user.id
        ))
        db.session.add_all([
            CashTransaction(
                user_id=user.id,
                account_id=bank.id,
                tarih=datetime(2026, 6, 30, tzinfo=timezone.utc),
                islem_tipi='cikis',
                tutar=9500,
                odeme_turu='Havale/EFT',
                aciklama='2026-06 toplu maaş ödemesi (1 personel)',
                referans_tip='maas_odeme',
            ),
            CashTransaction(
                user_id=user.id,
                account_id=bank.id,
                tarih=datetime(2026, 6, 5, tzinfo=timezone.utc),
                islem_tipi='cikis',
                tutar=500,
                odeme_turu='Havale/EFT',
                aciklama='Finans Personel avans ödemesi',
                referans_id=avans.id,
                referans_tip='personel_avans',
            ),
            CashTransaction(
                user_id=user.id,
                account_id=bank.id,
                tarih=datetime(2026, 6, 10, tzinfo=timezone.utc),
                islem_tipi='cikis',
                tutar=750,
                odeme_turu='Havale/EFT',
                aciklama='Finans Personel peşin prim ödemesi',
                referans_id=prim.id,
                referans_tip='personel_prim',
            ),
        ])
        db.session.commit()
        personel_id = personel.id

    response = client.get(f'/personel_detay/{personel_id}?period=2026-06')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Finans Geçmişi' in text
    assert 'Maaş' in text
    assert 'Avans' in text
    assert 'Peşin Prim' in text
    assert '₺9.500,00' in text
    assert '₺500,00' in text
    assert '₺750,00' in text
    assert 'Banka Hesabi' in text


def test_personel_create_rejects_foreign_department(client):
    with app.app_context():
        other_user = User.query.filter_by(email='other@example.com').first()
        foreign_departman = Departman(ad='Baska Firma Departmani', user_id=other_user.id)
        db.session.add(foreign_departman)
        db.session.commit()
        foreign_departman_id = foreign_departman.id

    response = client.post('/personel_ekle', data={
        'sicil_no': 'P-FOREIGN',
        'ad': 'Yetkisiz',
        'soyad': 'Departman',
        'tc_kimlik': '12345678901',
        'dogum_tarihi': '1990-01-01',
        'ise_giris_tarihi': '2026-01-01',
        'calisma_durumu': 'Aktif',
        'departman_id': str(foreign_departman_id),
        'pozisyon': 'Test',
        'maas': '1000'
    })

    assert response.status_code == 200
    with app.app_context():
        assert Personel.query.filter_by(sicil_no='P-FOREIGN').first() is None


def test_cari_filters_render_without_reload_errors(client):
    response = client.get('/cariler?search=Test&type=all')

    assert response.status_code == 200
    assert b'Test Cari' in response.data


def test_new_cari_page_opens_create_modal(client):
    response = client.get('/cari-ekle')

    assert response.status_code == 200
    assert b'id="newCariButton"' in response.data
    assert b'id="cariModal"' in response.data
    assert b'action="/cari-ekle"' in response.data
    assert 'Müşteri ve Tedarikçiler'.encode('utf-8') in response.data
    assert 'Yeni Müşteri/Tedarikçi'.encode('utf-8') in response.data
    assert 'Toplam Hesap'.encode('utf-8') in response.data
    assert 'Hesap türü'.encode('utf-8') in response.data
    assert 'Firma / Kişi adı *'.encode('utf-8') in response.data
    assert 'Cari tipi'.encode('utf-8') not in response.data


def test_new_cari_submission_creates_current_user_record(client):
    response = client.post('/cari-ekle', data={
        'unvan': 'Yeni Profesyonel Cari',
        'tipi': 'Müşteri',
        'yetkili': 'Ayse Test',
        'telefon': '5551234567',
        'email': 'ayse@example.com'
    }, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/cariler')
    with app.app_context():
        created = Cari.query.filter_by(unvan='Yeni Profesyonel Cari').first()
        owner = User.query.filter_by(email='test@example.com').first()
        assert created is not None
        assert created.user_id == owner.id


def test_cari_detail_does_not_render_other_users_child_records(client):
    with app.app_context():
        cari = Cari.query.filter_by(unvan='Test Cari').first()
        other_user = User.query.filter_by(email='other@example.com').first()
        foreign_sale = Satis(
            fatura_no='FOREIGN-LEAK-CHECK',
            cari_id=cari.id,
            user_id=other_user.id,
            genel_toplam=999
        )
        db.session.add(foreign_sale)
        db.session.commit()
        cari_id = cari.id

    response = client.get(f'/cari/{cari_id}')

    assert response.status_code == 200
    assert b'FOREIGN-LEAK-CHECK' not in response.data


def test_cari_screens_prefer_movement_based_balance_over_legacy_fields(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari(
            unvan='Hareket Bazli Cari',
            tipi='Müşteri',
            alacak=999.0,
            borc=0.0,
            user_id=owner.id
        )
        db.session.add(cari)
        db.session.flush()
        db.session.add_all([
            CariHareket(
                cari_id=cari.id,
                user_id=owner.id,
                islem_tipi='satis',
                tutar=200.0,
                odeme_turu='Alacak',
                referans_id=8101,
                referans_tip='satis'
            ),
            CariHareket(
                cari_id=cari.id,
                user_id=owner.id,
                islem_tipi='tahsilat',
                tutar=50.0,
                odeme_turu='Nakit',
                referans_id=8102,
                referans_tip='cari_tahsilat'
            ),
        ])
        db.session.commit()
        cari_id = cari.id

    list_response = client.get('/cariler?search=Hareket%20Bazli%20Cari')
    list_text = list_response.get_data(as_text=True)
    assert list_response.status_code == 200
    assert 'Hareket Bazli Cari' in list_text
    assert '₺150,00' in list_text or '₺150.00' in list_text
    assert '₺999,00' not in list_text and '₺999.00' not in list_text

    detail_response = client.get(f'/cari/{cari_id}')
    detail_text = detail_response.get_data(as_text=True)
    assert detail_response.status_code == 200
    assert '₺150,00' in detail_text or '₺150.00' in detail_text


def test_customer_cari_detail_prioritizes_collection_action(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        cari.tipi = 'Müşteri'
        cari.alacak = 100.0
        cari.borc = 0.0
        db.session.commit()
        cari_id = cari.id

    response = client.get(f'/cari/{cari_id}')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert b'@media print' in response.data
    assert b'.cari-print-page' in response.data
    assert b'.print-cari-header' in response.data
    assert b'overflow: visible !important' in response.data
    assert 'Cari Detayı'.encode('utf-8') in response.data
    assert 'Kalan Bakiye'.encode('utf-8') in response.data
    assert 'Sık Kullanılan İşlemler'.encode('utf-8') in response.data
    assert 'Cari Hareketleri'.encode('utf-8') in response.data
    assert 'Ödeme Şekli'.encode('utf-8') in response.data
    assert 'Sistem uygun hesabı seçsin'.encode('utf-8') in response.data
    assert 'Tahsilatı Kaydet'.encode('utf-8') in response.data
    assert 'Tahsil edilecek bakiye' in text
    assert 'Tahsil Edilecek' in text
    assert 'Müşteriden Tahsilat Al' in text
    assert 'Tedarikçiye Ödeme Yap' not in text
    assert 'Cari Kartı' not in text
    assert 'Finans Hareketleri' not in text
    assert 'İşlem Tipi' not in text
    assert 'Ödeme Türü' not in text


def test_supplier_cari_detail_prioritizes_payment_action(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        supplier = Cari(unvan='Test Tedarikci', tipi='Tedarikçi', borc=200.0, alacak=0.0, user_id=owner.id)
        db.session.add(supplier)
        db.session.commit()
        supplier_id = supplier.id

    response = client.get(f'/cari/{supplier_id}')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert b'.cari-print-page' in response.data
    assert b'.print-cari-header' in response.data
    assert 'Ödemeyi Kaydet'.encode('utf-8') in response.data
    assert 'Ödeme Şekli'.encode('utf-8') in response.data
    assert 'Ödenecek bakiye' in text
    assert 'Ödenecek' in text
    assert 'Tedarikçiye Ödeme Yap' in text
    assert 'Müşteriden Tahsilat Al' not in text


def test_pos_screen_renders_direct_payment_actions(client):
    response = client.get('/pos')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert b'data-payment-button' in response.data
    assert b'processPayment' in response.data
    assert 'Peşin Satış (müşteri seçmeden)'.encode('utf-8') in response.data
    assert 'Veresiye'.encode('utf-8') in response.data
    assert "processPayment('credit')" in text
    assert '<option value="0" selected>%0</option>' in text
    assert "readNumberInput('kdvRate', 0)" in text
    assert 'Barkodu okut + Enter'.encode('utf-8') not in response.data
    assert 'F2: Barkod alan?'.encode('utf-8') not in response.data
    assert "event.key === 'F10'" in text
    assert "event.key === 'F11'" in text
    assert 'Sepeti Temizle' in text
    assert '(F11)' in text
    assert 'window.appConfirm' in text
    assert "confirm('Sepeti" not in text
    assert 'function playScanFeedback' in text
    assert "playScanFeedback('success')" in text
    assert "playScanFeedback('error')" in text
    assert 'id="categoryFilter"' not in text
    assert 'id="categoryFilters"' not in text
    assert 'id="product-helper-panel"' not in text
    assert 'id="pos-payment-panel"' in text
    assert 'id="searchResultsDropdown"' in text
    assert 'id="searchResultsList"' in text
    assert 'function renderSearchResults' in text
    assert 'function addProductToCartById' in text
    assert 'function moveSearchSelection' in text
    assert 'function getSelectedSearchProduct' in text
    assert "event.key === 'ArrowDown'" in text
    assert "event.key === 'ArrowUp'" in text
    assert 'onkeyup="filterProducts()"' not in text
    assert 'id="receivedAmountInput"' in text
    assert 'id="changeAmount"' in text
    assert 'id="printReceiptAfterSale"' in text
    assert 'id="quickProductModal"' in text
    assert 'function openQuickProductModal' in text
    assert 'async function submitQuickProduct' in text
    assert "fetch('/api/pos/products'" in text
    assert 'Ürünü Kaydet ve Sepete Ekle' in text
    assert "fetch('/pos/satis'" in text
    assert "window.location.href = '/pos-odeme'" not in text
    assert 'pos_odeme' not in text
    assert '?deme ekran?na y?nlendiriliyor'.encode('utf-8') not in response.data
    pos_template = Path('templates', 'pos_urun_secimi_ve_sepet.html').read_text(encoding='utf-8')
    payment_block = pos_template[pos_template.index('async function processPayment'):pos_template.index('function setPaymentBusy')]
    assert payment_block.index('printReceiptDocument(receipt, saleData)') < payment_block.index('cart = [];')
    assert 'function printReceiptDocument(receipt, saleData)' in pos_template
    assert "fetch('{{ url_for(\"pos_fis_yazdir\") }}'" in pos_template
    assert "formData.set('receipt_payload'" in pos_template
    assert "formData.set('sale_payload'" in pos_template
    assert "document.createElement('iframe')" in pos_template
    assert "receipt-print-finished" in pos_template


def test_pos_quick_product_create_adds_product_for_current_user(client):
    response = client.post('/api/pos/products', json={
        'barkod': 'POS-NEW-001',
        'urun_adi': 'H?zl? POS ?r?n?',
        'satis_fiyati': 75.5,
        'stok_miktari': 3,
        'kategori': 'POS Test',
        'birim': 'Adet'
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['product']['barkod'] == 'POS-NEW-001'
    assert data['product']['urun_adi'] == 'H?zl? POS ?r?n?'
    assert data['product']['satis_fiyati'] == 75.5
    assert data['product']['stok_miktari'] == 3.0

    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(barkod='POS-NEW-001').first()
        assert product is not None
        assert product.user_id == owner.id
        assert product.kategori == 'POS Test'


def test_pos_quick_product_rejects_duplicate_barcode(client):
    response = client.post('/api/pos/products', json={
        'barkod': '1234567890123',
        'urun_adi': 'Tekrarl? Barkod',
        'satis_fiyati': 10,
        'stok_miktari': 1
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False
    assert data['message'] == 'Bu barkod zaten kayıtlı.'
    assert data['product']['barkod'] == '1234567890123'


def test_pos_payment_screen_has_single_complete_sale_handler(client):
    response = client.get('/pos-odeme')
    text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert text.count('async function completeSale()') == 1
    assert text.count('function selectPaymentMethod(method)') == 1
    assert 'POS Ödeme' in text
    assert "showMessage('Sepet bo?!'" not in text
    assert "showMessage('Al?nan tutar yetersiz!'" not in text
    assert 'showNotification(' in text


def test_quote_form_uses_main_application_layout(client):
    response = client.get('/teklif/ekle')

    assert response.status_code == 200
    assert b'id="teklifForm"' in response.data
    assert b'id="mainContent"' in response.data
    assert b'Teklif kalemleri' in response.data or 'Teklif kalemleri'.encode('utf-8') in response.data
    assert b'name="durum"' in response.data


def test_quote_create_defaults_to_sent_and_allows_draft(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        product_id = product.id
        cari_id = cari.id

    response = client.post('/teklif/ekle', data={
        'cari_id': str(cari_id),
        'teklif_no': 'STATUS-SENT-001',
        'tarih': '2026-06-03',
        'kdv_orani': '18',
        'urunler[]': [str(product_id)],
        'miktarlar[]': ['1'],
        'birimler[]': ['Adet'],
        'fiyatlar[]': ['100'],
    }, follow_redirects=True)
    assert response.status_code == 200

    response = client.post('/teklif/ekle', data={
        'cari_id': str(cari_id),
        'teklif_no': 'STATUS-DRAFT-001',
        'tarih': '2026-06-03',
        'durum': 'taslak',
        'kdv_orani': '18',
        'urunler[]': [str(product_id)],
        'miktarlar[]': ['1'],
        'birimler[]': ['Adet'],
        'fiyatlar[]': ['100'],
    }, follow_redirects=True)
    assert response.status_code == 200

    with app.app_context():
        sent = Teklif.query.filter_by(teklif_no='STATUS-SENT-001').first()
        draft = Teklif.query.filter_by(teklif_no='STATUS-DRAFT-001').first()
        assert sent is not None
        assert sent.durum == 'gonderildi'
        assert draft is not None
        assert draft.durum == 'taslak'


def test_quote_create_rejects_empty_or_invalid_lines(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        cari_id = cari.id
        quote_count = Teklif.query.count()

    response = client.post('/teklif/ekle', data={
        'cari_id': str(cari_id),
        'teklif_no': 'EMPTY-LINE-001',
        'tarih': '2026-06-03',
        'kdv_orani': '18',
        'urunler[]': [''],
        'miktarlar[]': [''],
        'birimler[]': ['Adet'],
        'fiyatlar[]': [''],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        assert Teklif.query.count() == quote_count
        assert Teklif.query.filter_by(teklif_no='EMPTY-LINE-001').first() is None


def test_quote_rejects_invalid_kdv(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        product_id = product.id
        cari_id = cari.id

    response = client.post('/teklif/ekle', data={
        'cari_id': str(cari_id),
        'teklif_no': 'BAD-KDV-001',
        'tarih': '2026-06-03',
        'kdv_orani': '-1',
        'urunler[]': [str(product_id)],
        'miktarlar[]': ['1'],
        'birimler[]': ['Adet'],
        'fiyatlar[]': ['100'],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        assert Teklif.query.filter_by(teklif_no='BAD-KDV-001').first() is None


def test_quote_edit_updates_kdv_and_preserves_lines_on_invalid_edit(client):
    with app.app_context():
        owner = User.query.filter_by(email='test@example.com').first()
        product = Urun.query.filter_by(user_id=owner.id).first()
        cari = Cari.query.filter_by(user_id=owner.id).first()
        quote = Teklif(
            teklif_no='EDIT-KDV-001',
            cari_id=cari.id,
            user_id=owner.id,
            durum='gonderildi',
            kdv_orani=18,
            toplam_tutar=100,
            genel_toplam=118,
        )
        db.session.add(quote)
        db.session.flush()
        db.session.add(TeklifKalemi(
            teklif_id=quote.id,
            urun_id=product.id,
            urun_adi=product.urun_adi,
            miktar=1,
            birim='Adet',
            birim_fiyat=100,
            toplam=100,
        ))
        db.session.commit()
        quote_id = quote.id
        product_id = product.id
        cari_id = cari.id

    response = client.post(f'/teklif/{quote_id}/duzenle', data={
        'cari_id': str(cari_id),
        'gecerlilik_tarihi': '',
        'durum': 'gonderildi',
        'kdv_orani': '8',
        'urunler[]': [str(product_id)],
        'miktarlar[]': ['1'],
        'birimler[]': ['Adet'],
        'fiyatlar[]': ['100'],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        quote = db.session.get(Teklif, quote_id)
        assert quote.kdv_orani == 8
        assert quote.genel_toplam == 108
        assert TeklifKalemi.query.filter_by(teklif_id=quote_id).count() == 1

    response = client.post(f'/teklif/{quote_id}/duzenle', data={
        'cari_id': str(cari_id),
        'gecerlilik_tarihi': '',
        'durum': 'gonderildi',
        'kdv_orani': '18',
        'urunler[]': [''],
        'miktarlar[]': [''],
        'birimler[]': ['Adet'],
        'fiyatlar[]': [''],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        quote = db.session.get(Teklif, quote_id)
        assert quote.kdv_orani == 8
        assert quote.genel_toplam == 108
        assert TeklifKalemi.query.filter_by(teklif_id=quote_id).count() == 1


def test_stock_add(client):
    with app.app_context():
        product = Urun.query.first()
    response = client.post('/api/stock/add', json={
        'product_id': product.id,
        'quantity': 5,
        'depot': 'Ana Depo'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['new_stock'] == 25.0
    with app.app_context():
        assert StokHareket.query.filter_by(islem_tipi='giris', depo='Ana Depo').count() == 1


def test_stock_batch_add(client):
    with app.app_context():
        product = Urun.query.first()
    response = client.post('/api/stock/batch-add', json={
        'product_ids': [product.id],
        'quantity': 3,
        'depot': 'Ana Depo'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert len(data['results']) == 1
    assert data['results'][0]['new_stock'] == 23.0


def test_stock_batch_add_is_atomic_when_one_product_invalid(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        product_id = product.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/api/stock/batch-add', json={
        'product_ids': [product_id, 999999],
        'quantity': 3,
        'depot': 'Ana Depo'
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False

    with app.app_context():
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before
        assert StokHareket.query.count() == 0


def test_stok_giris_template_downloads_csv(client):
    response = client.get('/stok/giris/sablon.csv')

    assert response.status_code == 200
    assert 'text/csv' in response.headers.get('Content-Type', '')
    assert 'stok-giris-sablonu.csv' in response.headers.get('Content-Disposition', '')

    csv_text = response.get_data(as_text=True)
    assert 'Barkod;Ürün Adı;Kategori;Birim;Miktar;Alış Fiyatı;Satış Fiyatı;Kritik Stok;Depo;Açıklama' in csv_text
    assert 'Örnek Matkap Ucu 5mm' in csv_text


def test_stock_import_preview_does_not_apply_changes_immediately(client):
    csv_content = (
        'Barkod;Ürün Adı;Kategori;Birim;Miktar;Alış Fiyatı;Satış Fiyatı;Kritik Stok;Depo;Açıklama\n'
        '1234567890123;Test Urun Guncel;Hırdavat;Koli;4;75;125;8;Ana Depo;Mevcut ürüne ek\n'
        '8690000000002;Yeni Keski;Hırdavat;Adet;7;25,50;39,90;3;Merkez Depo;Yeni ürün oluştur\n'
    )

    response = client.post(
        '/api/stock/import/preview',
        data={'file': (BytesIO(csv_content.encode('utf-8')), 'stok.csv')},
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['preview_count'] == 2
    assert data['valid_count'] == 2

    with app.app_context():
        existing = Urun.query.filter_by(barkod='1234567890123', depo_adi='Ana Depo').first()
        new_product = Urun.query.filter_by(barkod='8690000000002', depo_adi='Merkez Depo').first()

        assert existing is not None
        assert float(existing.stok_miktari or 0) == 20.0
        assert new_product is None
        assert StokHareket.query.filter_by(islem_tipi='giris').count() == 0


def test_stock_import_commit_applies_selected_preview_rows(client):
    csv_content = (
        'Barkod;Ürün Adı;Kategori;Birim;Miktar;Alış Fiyatı;Satış Fiyatı;Kritik Stok;Depo;Açıklama\n'
        '1234567890123;Test Urun Guncel;Hırdavat;Koli;4;75;125;8;Ana Depo;Mevcut ürüne ek\n'
        '8690000000002;Yeni Keski;Hırdavat;Adet;7;25,50;39,90;3;Merkez Depo;Yeni ürün oluştur\n'
    )

    preview_response = client.post(
        '/api/stock/import/preview',
        data={'file': (BytesIO(csv_content.encode('utf-8')), 'stok.csv')},
        content_type='multipart/form-data',
    )
    preview_data = preview_response.get_json()
    row_ids = [row['row_id'] for row in preview_data['rows']]

    response = client.post('/api/stock/import/commit', json={'row_ids': row_ids})

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['created_count'] == 1
    assert data['updated_count'] == 1
    assert data['remaining_count'] == 0

    with app.app_context():
        existing = Urun.query.filter_by(barkod='1234567890123', depo_adi='Ana Depo').first()
        new_product = Urun.query.filter_by(barkod='8690000000002', depo_adi='Merkez Depo').first()

        assert existing is not None
        assert float(existing.stok_miktari or 0) == 24.0
        assert new_product is not None
        assert new_product.urun_adi == 'Yeni Keski'
        assert float(new_product.stok_miktari or 0) == 7.0
        assert StokHareket.query.filter_by(islem_tipi='giris').count() == 2


def test_stock_add_to_different_warehouse_creates_depot_product(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
    response = client.post('/api/stock/add', json={
        'product_id': product.id,
        'quantity': 4,
        'depot': 'Merkez Depo'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['new_stock'] == 4.0
    assert data['product_id'] != product.id

    with app.app_context():
        source = db.session.get(Urun, product.id)
        target = Urun.query.filter_by(barkod='1234567890123', depo_adi='Merkez Depo').first()
        assert source.stok_miktari == 20.0
        assert target is not None
        assert target.stok_miktari == 4.0


def test_transfer_products_records_both_ledger_entries(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
    response = client.post('/api/settings/transfer-products', json={
        'from_warehouse': 'Ana Depo',
        'to_warehouse': 'Merkez Depo',
        'product_ids': [product.id],
        'quantity': 6
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True

    with app.app_context():
        source = db.session.get(Urun, product.id)
        target = Urun.query.filter_by(barkod='1234567890123', depo_adi='Merkez Depo').first()
        assert source.stok_miktari == 14.0
        assert target.stok_miktari == 6.0
        assert StokHareket.query.filter_by(islem_tipi='cikis', depo='Ana Depo').count() == 1
        assert StokHareket.query.filter_by(islem_tipi='giris', depo='Merkez Depo').count() == 1


def test_transfer_products_is_atomic_when_one_item_invalid(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        product_id = product.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/api/settings/transfer-products', json={
        'from_warehouse': 'Ana Depo',
        'to_warehouse': 'Merkez Depo',
        'product_ids': [product_id, 999999],
        'quantity': 3
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False

    with app.app_context():
        product = db.session.get(Urun, product_id)
        target = Urun.query.filter_by(barkod='1234567890123', depo_adi='Merkez Depo').first()
        assert float(product.stok_miktari or 0) == stock_before
        assert target is None
        assert StokHareket.query.count() == 0


def test_transfer_products_does_not_create_missing_source_warehouse(client):
    with app.app_context():
        missing_before = Warehouse.query.filter_by(name='Hayali Depo').count()
        target_before = Warehouse.query.filter_by(name='Merkez Depo').count()

    response = client.post('/api/settings/transfer-products', json={
        'from_warehouse': 'Hayali Depo',
        'to_warehouse': 'Merkez Depo',
        'product_ids': [1],
        'quantity': 1
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False

    with app.app_context():
        assert Warehouse.query.filter_by(name='Hayali Depo').count() == missing_before
        assert Warehouse.query.filter_by(name='Merkez Depo').count() == target_before
        assert StokHareket.query.count() == 0


def test_pos_sale_rejects_foreign_customer(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        foreign_cari = Cari.query.filter_by(unvan='Other Cari').first()

    response = client.post('/pos/satis', json={
        'customerId': foreign_cari.id,
        'items': [{'id': product.id, 'price': 100, 'quantity': 1}],
        'paymentMethod': 'cash'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False
    assert 'Geçersiz müşteri' in data['message']

    with app.app_context():
        assert Satis.query.count() == 0


def test_pos_sale_successfully_records_sale(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        cari = Cari.query.filter_by(unvan='Test Cari').first()

    response = client.post('/pos/satis', json={
        'customerId': cari.id,
        'items': [{'id': product.id, 'price': 100, 'quantity': 2}],
        'paymentMethod': 'cash'
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['total'] == 236.0

    with app.app_context():
        assert Satis.query.count() == 1
        new_satis = Satis.query.first()
        assert new_satis.genel_toplam == 236.0
        assert db.session.get(Cari, cari.id).alacak == 0
        assert CashTransaction.query.filter_by(referans_tip='satis', referans_id=new_satis.id, islem_tipi='giris').count() == 1
        assert CariHareket.query.filter_by(referans_tip='satis', referans_id=new_satis.id).count() == 0


def test_pos_sale_normalizes_card_payment_method(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        product_id = product.id

    response = client.post('/pos/satis', json={
        'items': [{'id': product_id, 'price': 100, 'quantity': 1}],
        'paymentMethod': 'card'
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['receipt']['payment_method'] == 'Kredi Kartı'

    with app.app_context():
        sale = Satis.query.order_by(Satis.id.desc()).first()
        tx = CashTransaction.query.filter_by(referans_tip='satis', referans_id=sale.id, islem_tipi='giris').first()
        assert tx is not None
        assert tx.odeme_turu == 'Kredi Kartı'


def test_pos_card_sale_requires_active_adapter_when_integration_enabled(client):
    enable_platform_pos_integration_for_users()
    settings_path = primary_test_user_backup_dir() / 'settings.json'
    original = settings_path.read_text(encoding='utf-8') if settings_path.exists() else None
    try:
        with app.app_context():
            owner = User.query.filter_by(email='test@example.com').first()
            product = Urun.query.filter_by(user_id=owner.id, depo_adi='Ana Depo').first()
            product_id = product.id
            stock_before = float(product.stok_miktari or 0)

        client.post('/api/settings/pos-integration', json={
            'mode': 'integrated',
            'provider': 'pavo',
            'environment': 'live',
            'connection_type': 'ip',
            'bank_name': 'Test Bankas?',
            'terminal_id': 'TERM-001',
            'merchant_id': 'MERCHANT-001',
            'device_ip': '192.168.1.50',
            'device_port': '8080',
            'device_serial': 'SN-001',
            'timeout_seconds': 30,
            'test_amount': 1,
            'auto_send_amount': True,
            'require_success': True,
        })

        response = client.post('/pos/satis', json={
            'items': [{'id': product_id, 'price': 100, 'quantity': 1}],
            'paymentMethod': 'card'
        })

        assert response.status_code == 409
        data = response.get_json()
        assert data['success'] is False
        assert data['payment_integration']['status'] == 'adapter_required'

        with app.app_context():
            product = db.session.get(Urun, product_id)
            assert float(product.stok_miktari or 0) == stock_before
            assert Satis.query.count() == 0
    finally:
        if original is None:
            if settings_path.exists():
                settings_path.unlink()
            if settings_path.parent.exists() and not any(settings_path.parent.iterdir()):
                settings_path.parent.rmdir()
        else:
            settings_path.write_text(original, encoding='utf-8')


def test_pos_sale_rejects_negative_discount(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()

    response = client.post('/pos/satis', json={
        'items': [{'id': product.id, 'price': 100, 'quantity': 1}],
        'paymentMethod': 'cash',
        'discount': -1
    })
    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False

    with app.app_context():
        assert Satis.query.count() == 0


def test_pos_sale_allows_zero_kdv_and_applies_discount(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        product_id = product.id

    response = client.post('/pos/satis', json={
        'items': [{'id': product_id, 'price': 100, 'quantity': 2}],
        'paymentMethod': 'cash',
        'kdvRate': 0,
        'discount': 15
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['total'] == 185.0
    assert data['receipt']['subtotal'] == 200.0
    assert data['receipt']['vat_rate'] == 0
    assert data['receipt']['vat_total'] == 0
    assert data['receipt']['discount'] == 15

    with app.app_context():
        sale = Satis.query.order_by(Satis.id.desc()).first()
        assert sale.ara_toplam == 200.0
        assert sale.kdv_orani == 0
        assert sale.kdv_tutar == 0
        assert sale.iskonto == 15
        assert sale.genel_toplam == 185.0


def test_pos_sale_rejects_discount_greater_than_total_without_stock_change(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        product_id = product.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/pos/satis', json={
        'items': [{'id': product_id, 'price': 100, 'quantity': 1}],
        'paymentMethod': 'cash',
        'kdvRate': 18,
        'discount': 118
    })

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is False

    with app.app_context():
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before
        assert Satis.query.count() == 0
        assert CashTransaction.query.count() == 0


def test_stock_out_rejects_empty_sale(client):
    with app.app_context():
        cari = Cari.query.filter_by(unvan='Test Cari').first()

    response = client.post('/stok/cikis', data={
        'cari_id': str(cari.id),
        'depo': 'Ana Depo',
        'urun_id[]': [''],
        'miktar[]': [''],
        'birim_fiyat[]': ['']
    }, follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        assert Satis.query.count() == 0


def test_stock_out_calculates_kdv_discount_and_creates_cari_movement(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        cari = Cari.query.filter_by(unvan='Test Cari').first()
        product_id = product.id
        cari_id = cari.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/stok/cikis', data={
        'cari_id': str(cari_id),
        'depo': 'Ana Depo',
        'tarih': '2026-06-03',
        'kdv_orani': '8',
        'iskonto': '10',
        'urun_id[]': [str(product_id)],
        'miktar[]': ['2'],
        'birim_fiyat[]': ['100'],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        product = db.session.get(Urun, product_id)
        sale = Satis.query.order_by(Satis.id.desc()).first()
        cari = db.session.get(Cari, cari_id)
        movement = CariHareket.query.filter_by(referans_tip='satis', referans_id=sale.id).first()
        assert float(product.stok_miktari or 0) == stock_before - 2
        assert sale.ara_toplam == 200
        assert sale.kdv_orani == 8
        assert sale.kdv_tutar == 16
        assert sale.iskonto == 10
        assert sale.genel_toplam == 206
        assert float(cari.alacak or 0) == 206
        assert movement is not None
        assert movement.tutar == 206


def test_stock_out_rejects_invalid_kdv_or_excessive_discount(client):
    with app.app_context():
        product = Urun.query.filter_by(depo_adi='Ana Depo').first()
        cari = Cari.query.filter_by(unvan='Test Cari').first()
        product_id = product.id
        cari_id = cari.id
        stock_before = float(product.stok_miktari or 0)

    response = client.post('/stok/cikis', data={
        'cari_id': str(cari_id),
        'depo': 'Ana Depo',
        'tarih': '2026-06-03',
        'kdv_orani': '101',
        'iskonto': '0',
        'urun_id[]': [str(product_id)],
        'miktar[]': ['1'],
        'birim_fiyat[]': ['100'],
    }, follow_redirects=False)

    assert response.status_code == 302
    with app.app_context():
        product = db.session.get(Urun, product_id)
        assert float(product.stok_miktari or 0) == stock_before
        assert Satis.query.count() == 0

