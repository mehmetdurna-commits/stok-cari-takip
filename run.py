#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

# Proje dizinini Python path'ine ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, User, Urun

# Demo ürünler listesi
DEMO_URUNLER = [
    {
        'barkod': '8680000000001',
        'urun_adi': 'Laptop Dell Inspiron 15',
        'kategori': 'Elektronik',
        'birim': 'Adet',
        'alis_fiyati': 8500.00,
        'satis_fiyati': 11299.99,
        'stok_miktari': 15,
        'kritik_stok': 5
    },
    {
        'barkod': '8680000000002',
        'urun_adi': 'Logitech M185 Kablosuz Mouse',
        'kategori': 'Bilgisayar Aksesuar',
        'birim': 'Adet',
        'alis_fiyati': 89.00,
        'satis_fiyati': 159.99,
        'stok_miktari': 45,
        'kritik_stok': 10
    },
    {
        'barkod': '8680000000003',
        'urun_adi': 'Samsung 24" LED Monitör',
        'kategori': 'Elektronik',
        'birim': 'Adet',
        'alis_fiyati': 1200.00,
        'satis_fiyati': 1899.00,
        'stok_miktari': 12,
        'kritik_stok': 3
    },
    {
        'barkod': '8680000000004',
        'urun_adi': 'HP LaserJet Pro Yazıcı',
        'kategori': 'Ofis Ekipman',
        'birim': 'Adet',
        'alis_fiyati': 1450.00,
        'satis_fiyati': 2199.00,
        'stok_miktari': 8,
        'kritik_stok': 2
    },
    {
        'barkod': '8680000000005',
        'urun_adi': 'Canon Pixma Mürekkep Püskürtmeli Yazıcı',
        'kategori': 'Ofis Ekipman',
        'birim': 'Adet',
        'alis_fiyati': 650.00,
        'satis_fiyati': 999.99,
        'stok_miktari': 18,
        'kritik_stok': 5
    },
    {
        'barkod': '8680000000006',
        'urun_adi': 'A4 Fotokopi Kağıdı (500 sayfa)',
        'kategori': 'Ofis Malzemeleri',
        'birim': 'Paket',
        'alis_fiyati': 18.50,
        'satis_fiyati': 32.99,
        'stok_miktari': 120,
        'kritik_stok': 25
    },
    {
        'barkod': '8680000000007',
        'urun_adi': 'Kablosuz Klavye Mouse Set',
        'kategori': 'Bilgisayar Aksesuar',
        'birim': 'Set',
        'alis_fiyati': 145.00,
        'satis_fiyati': 249.99,
        'stok_miktari': 25,
        'kritik_stok': 5
    },
    {
        'barkod': '8680000000008',
        'urun_adi': 'HDMI Kablo 3 Metre',
        'kategori': 'Kablo ve Bağlantı',
        'birim': 'Adet',
        'alis_fiyati': 12.00,
        'satis_fiyati': 29.99,
        'stok_miktari': 50,
        'kritik_stok': 10
    },
    {
        'barkod': '8680000000009',
        'urun_adi': 'USB Type-C Şarj Adaptörü 65W',
        'kategori': 'Elektronik',
        'birim': 'Adet',
        'alis_fiyati': 89.00,
        'satis_fiyati': 159.00,
        'stok_miktari': 35,
        'kritik_stok': 8
    },
    {
        'barkod': '8680000000010',
        'urun_adi': 'TP-Link WiFi 6 Router',
        'kategori': 'Ağ Ekipmanları',
        'birim': 'Adet',
        'alis_fiyati': 450.00,
        'satis_fiyati': 749.99,
        'stok_miktari': 10,
        'kritik_stok': 3
    }
]

def demo_urunleri_ekle(user_id):
    """Demo ürünleri veritabanına ekle"""
    eklenen = 0
    for urun_data in DEMO_URUNLER:
        # Barkod kontrolü - varsa ekleme
        mevcut = Urun.query.filter_by(barkod=urun_data['barkod'], user_id=user_id).first()
        if not mevcut:
            yeni_urun = Urun(
                barkod=urun_data['barkod'],
                urun_adi=urun_data['urun_adi'],
                kategori=urun_data['kategori'],
                birim=urun_data['birim'],
                alis_fiyati=urun_data['alis_fiyati'],
                satis_fiyati=urun_data['satis_fiyati'],
                stok_miktari=urun_data['stok_miktari'],
                kritik_stok=urun_data['kritik_stok'],
                user_id=user_id
            )
            db.session.add(yeni_urun)
            eklenen += 1
    
    if eklenen > 0:
        db.session.commit()
        print(f"✓ {eklenen} adet demo ürün eklendi!")
    else:
        print("ℹ Demo ürünler zaten mevcut.")

if __name__ == '__main__':
    # Veritabanını oluştur
    with app.app_context():
        if not app.config.get('IS_PRODUCTION'):
            db.create_all()
            print("Veritabanı tabloları oluşturuldu!")
        
        # Demo ürünleri ekle (devre dışı bırakıldı)
        # user = User.query.filter_by(email='mehmetdurna@msn.com').first()
        # if user:
        #     demo_urunleri_ekle(user.id)
        # else:
        #     print("⚠ mehmetdurna@msn.com kullanıcısı bulunamadı.")
        #     print("  Önce kayıt olun, sonra tekrar çalıştırın.")
    
    # Uygulamayı başlat
    print("\nStokCari Web Uygulaması başlatılıyor...")
    print("http://localhost:5000 adresinden erişebilirsiniz")
    app.run(
        debug=app.config.get('DEBUG', False),
        host=app.config.get('RUN_HOST', '0.0.0.0'),
        port=app.config.get('RUN_PORT', 5000)
    )
