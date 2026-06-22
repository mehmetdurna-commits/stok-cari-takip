# Git Kullanımı

Bu projede Git geçmişi klasik `.git/` yerine `.repo-git2/` klasöründe tutulur.

## 1) Terminal açınca önce bunu çalıştır

```powershell
$env:GIT_DIR='.repo-git2'
$env:GIT_WORK_TREE='.'
```

Bu iki satırdan sonra bulunduğun terminal oturumunda `git` komutları normal çalışır.

## 2) En sık kullanacağın komutlar

### Durumu kontrol et

```powershell
git status
```

### Değişiklikleri hazırla

```powershell
git add .
```

Belirli bir dosyayı eklemek istersen:

```powershell
git add app.py
```

### Commit oluştur

```powershell
git commit -m "Kısa ve net açıklama"
```

Örnek:

```powershell
git commit -m "POS fiş yazdırma hatasını düzelt"
```

### GitHub'a gönder

```powershell
git push
```

## 3) Günlük güvenli çalışma akışı

Her değişiklikten sonra şu sırayı kullan:

```powershell
git status
git add .
git commit -m "Yaptığın değişiklik"
git push
```

## 4) Geçmişi görmek

```powershell
git log --oneline
```

Detaylı görmek istersen:

```powershell
git log
```

## 5) Hangi dosyalar değişti görmek

```powershell
git diff
```

Hazırlanmış dosyaları görmek:

```powershell
git diff --cached
```

## 6) Commit mesajı nasıl olmalı

Kısa, net ve tek işi anlatan mesaj yaz:

- `Cari ekstre net durum hesabını düzelt`
- `Personel bordro görünümünü iyileştir`
- `POS peşin satış fiş hatasını düzelt`

## 7) Dikkat

- Yeni terminal açınca `GIT_DIR` ve `GIT_WORK_TREE` satırlarını tekrar çalıştır.
- `.repo-git2/` klasörünü silme.
- Commit atmadan önce mümkünse `git status` kontrol et.
- Büyük değişikliklerde tek dev commit yerine küçük commitler at.

## 8) Hızlı başlangıç

Sadece hızlıca kaydetmek istersen:

```powershell
$env:GIT_DIR='.repo-git2'
$env:GIT_WORK_TREE='.'
git status
git add .
git commit -m "Güncelleme"
git push
```
