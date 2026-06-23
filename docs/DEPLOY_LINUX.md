# Linux (Nginx + Gunicorn) Deploy

Bu doküman, uygulamayı en yaygın ve genel kabul görmüş senaryo ile (Linux + Nginx + Gunicorn) canlıya almak için kısa bir rehberdir.

## 1) Sunucu gereksinimleri

- Ubuntu/Debian türevi bir Linux
- Python 3.11+ (tercihen 3.12+)
- PostgreSQL (önerilir)
- Nginx

## 2) Uygulamayı çalıştırma mantığı

- Nginx internetten gelen isteği karşılar (HTTPS/SSL burada biter).
- Nginx isteği iç ağdaki Gunicorn'a yönlendirir.
- Gunicorn `wsgi:application` objesini çalıştırır.

## 3) Ortam değişkenleri

`.env.example` dosyasını temel alın ve aşağıdakileri mutlaka ayarlayın:

- `APP_ENV=production`
- `SITE_URL=https://www.esstok.com` (canonical/OG/sitemap için)
- `SECRET_KEY` (zorunlu, uzun ve rastgele)
- `SECURITY_PASSWORD_SALT` (zorunlu, uzun ve rastgele)
- `DATABASE_URL` (prod'da SQLite önerilmez)
- `SESSION_COOKIE_SECURE=1`
- `USE_PROXY_FIX=1`

Not: `config.py` prod ortamda `SECRET_KEY`, `SECURITY_PASSWORD_SALT` ve `DATABASE_URL` için kontrol yapar.

## 4) Bağımlılıklar

Üretim bağımlılıkları `requirements.txt` içindedir. Ortak sanal ortamı oluşturun:

```bash
python3 -m venv /opt/stokcari/shared/.venv
/opt/stokcari/shared/.venv/bin/pip install -r requirements.txt
```

## 5) Gunicorn çalıştırma

Projede `gunicorn.conf.py` var. Örnek:

```bash
export APP_ENV=production
export USE_PROXY_FIX=1
gunicorn -c gunicorn.conf.py wsgi:application
```

## 6) Nginx reverse proxy (örnek)

Hazır şablon: `deploy/nginx/www.esstok.com.conf`

`/etc/nginx/sites-available/stokcari` gibi:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

SSL için genelde Let's Encrypt (certbot) kullanılır.

## 6.1) Systemd service (örnek)

Hazır şablon: `deploy/systemd/stokcari.service`

Örnek kurulum:

```bash
sudo cp deploy/systemd/stokcari.service /etc/systemd/system/stokcari.service
sudo systemctl daemon-reload
sudo systemctl enable --now stokcari
sudo systemctl status stokcari
```

## 6.2) Updater (Super Admin ile güncelleme)

Super Admin → Sistem Yönetimi ekranındaki “Güncelleme” kartı, bir `release.zip` yüklemenizi sağlar. Uygulama dosyayı `instance/updates/` altına bırakır ve updater servisi bunu güvenli şekilde uygular.

Hazır şablonlar:

- `deploy/systemd/stokcari-updater.service`
- `deploy/systemd/stokcari-updater.timer`

Kurulum:

```bash
sudo cp deploy/systemd/stokcari-updater.service /etc/systemd/system/stokcari-updater.service
sudo cp deploy/systemd/stokcari-updater.timer /etc/systemd/system/stokcari-updater.timer
sudo systemctl daemon-reload
sudo systemctl enable --now stokcari-updater.timer
sudo systemctl list-timers | grep stokcari-updater
```

Notlar:

- Uygulama `release.zip` dosyasını `instance/updates/incoming/` altına kaydeder ve `instance/updates/requests/` altına bir istek bırakır.
- Updater bu isteği alır, `releases/` altına açar, `current` symlink'ini yeni sürüme çevirir, servisi restart eder ve `/health` ile doğrular.
- Sağlık kontrolü geçmezse otomatik rollback yapar.

## Release zip üretimi (geliştirici bilgisayarı)

Projede release paketi üretmek için script var:

```bash
python scripts/build_release.py --version 2026.05.22-001 --out dist/stokcari-2026.05.22-001.zip
```

Bu zip Super Admin → Sistem Yönetimi → Güncelleme alanından yüklenebilir.

## 7) Veritabanı / migration

Projede `migrations/` klasörü var. Canlıya çıkarken:

 - DB'yi oluşturun (PostgreSQL)
 - `DATABASE_URL` ayarlayın
- Migration'larÄ± uygulayÄ±n

## 8) Sağlık kontrolü

Uygulama `GET /health` endpoint'i sunar; Nginx veya load balancer bunu kullanabilir.

## POS fiş yazdırma

POS ödeme ekranı, satış tamamlanınca `window.print()` ile tarayıcı yazdırmayı açar. Bu ekranda sadece fiş çıktısı basılsın diye `@media print` ile sayfanın geri kalanı gizlenir.

- Şablon: `templates/pos_odeme_ekrani_turkce_.html`
- Not: Termal fiş yazıcı (80mm) için tarayıcı yazdırma ayarlarında kenar boşluklarını düşük tutun.
