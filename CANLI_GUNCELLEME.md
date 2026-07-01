# Canlı Güncelleme Rehberi

Bu dosya, `esstok.com` canlı sunucusuna yeni kod gönderirken hızlıca bakmak için hazırlandı.

## 1) Kendi bilgisayarında kodu GitHub'a gönder

PowerShell aç:

```powershell
$env:GIT_DIR='.repo-git2'
$env:GIT_WORK_TREE='.'
git status
git add .
git commit -m "Yaptığın değişikliğin kısa açıklaması"
git push
```

Not:
- `nothing to commit, working tree clean` çıkarsa yeni değişiklik yok demektir.
- Her yeni PowerShell penceresinde `GIT_DIR` ve `GIT_WORK_TREE` satırlarını tekrar girmen gerekir.

## 2) Canlı sunucuda yeni kodu çek

Sunucu terminalinde:

```bash
cd /opt/esstok
git pull
source .venv/bin/activate
flask db upgrade
systemctl restart esstok
systemctl restart nginx
```

## 3) Ne zaman `pip install -r requirements.txt` çalıştırılır?

Sadece yeni Python paketi eklediysen çalıştır:

```bash
cd /opt/esstok
source .venv/bin/activate
pip install -r requirements.txt
```

Ardından:

```bash
flask db upgrade
systemctl restart esstok
systemctl restart nginx
```

## 4) Hızlı kontrol

Güncellemeden sonra şunları kontrol et:

- `https://www.esstok.com`
- giriş sayfası açılıyor mu
- kritik ekranlar açılıyor mu
- hata varsa servis durumu:

```bash
systemctl status esstok
systemctl status nginx
```

## 5) En pratik kısa akış

Bilgisayarda:

```powershell
$env:GIT_DIR='.repo-git2'
$env:GIT_WORK_TREE='.'
git add .
git commit -m "Canlı güncelleme"
git push
```

Sunucuda:

```bash
cd /opt/esstok
git pull
source .venv/bin/activate
flask db upgrade
systemctl restart esstok
```

## 6) Önemli not

Eğer repo `private` olursa sunucuda `git pull` için erişim yetkisi gerekir. En sağlıklı yöntem:

- ya deploy anahtarı / SSH key kurmak
- ya da GitHub erişimini sunucuda kalıcı yapılandırmak

Bu ayar yapılmadan repo'yu `private` yaparsan canlı sunucu `git pull` sırasında yetki hatası verebilir.
