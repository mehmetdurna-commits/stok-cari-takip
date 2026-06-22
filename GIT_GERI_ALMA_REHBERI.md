# Git Geri Alma Rehberi

Bu rehber, projede bir şey bozulduğunda panik yapmadan güvenli şekilde geri dönmek için hazırlanmıştır.

Bu projede Git geçmişi `.repo-git2/` klasöründe tutulur.

## 1) Her terminal açılışında önce bunu çalıştır

```powershell
$env:GIT_DIR='.repo-git2'
$env:GIT_WORK_TREE='.'
```

## 2) Önce durumu gör

```powershell
git status
git log --oneline
```

Bu iki komut şunu gösterir:

- hangi dosyalar değişmiş
- en son commitler hangileri

## 3) Henüz commit etmediğin değişiklikleri iptal et

Tek dosyayı geri al:

```powershell
git restore app.py
```

Tüm commitlenmemiş değişiklikleri geri al:

```powershell
git restore .
```

## 4) `git add` yaptın ama commit atmadın

Hazırlanan dosyaları sıradan çıkar:

```powershell
git restore --staged .
```

Sonra istersen dosyaların içeriğini de geri al:

```powershell
git restore .
```

## 5) Son commit'e geri dönmek istersen

Önce geçmişi gör:

```powershell
git log --oneline
```

Örnek çıktı:

```powershell
abc1234 POS fiş yazdırma hatasını düzelt
def5678 Personel bordro görünümünü iyileştir
ghi9012 Cari ekstre net durum hesabını düzelt
```

## 6) Sadece geçici olarak eski commit'e bakmak

```powershell
git checkout abc1234
```

Bu modda sadece eski hali incelersin.

Geri dönmek için:

```powershell
git checkout main
```

## 7) Projeyi tamamen eski commit'e döndürmek

Bu güçlü bir işlemdir. Dikkatli kullan.

```powershell
git reset --hard abc1234
```

Bu komut:

- projeyi o commit'e geri döndürür
- commitlenmemiş değişiklikleri siler

Bu yüzden önce mutlaka:

```powershell
git status
```

## 8) GitHub'a da geri dönüşü yansıtmak

Eğer `reset --hard` yaptıysan ve GitHub'daki `main` branch'i de aynı hale getirmek istiyorsan:

```powershell
git push --force
```

Bu komut tehlikelidir. Sadece bilinçli kullan.

## 9) Daha güvenli geri alma yöntemi

Geçmişi silmeden geri almak istersen:

```powershell
git revert COMMIT_ID
```

Örnek:

```powershell
git revert abc1234
```

Bu yöntem:

- eski commit'i silmez
- onu etkisiz hale getiren yeni bir commit oluşturur

Genelde en güvenli yöntem budur.

## 10) En güvenli kurtarma akışı

Bir şey bozulduysa şu sırayı uygula:

```powershell
git status
git log --oneline
```

Sonra bana şunu söyle:

- `geri dönmek istiyorum`
- veya
- `şu commit'e bakmak istiyorum`

Ben sana en güvenli komutu söylerim.

## 11) Altın kurallar

- Panikle `reset --hard` yapma
- Önce `git status` ve `git log --oneline` bak
- Emin değilsen önce `git revert` düşün
- Büyük bozulmalarda önce bana sor

## 12) Hızlı özet

### Commit edilmemiş değişiklikleri sil

```powershell
git restore .
```

### Hazırlanmış dosyaları geri çıkar

```powershell
git restore --staged .
```

### Eski commit'e bak

```powershell
git checkout COMMIT_ID
```

### Main'e dön

```powershell
git checkout main
```

### Tam geri sar

```powershell
git reset --hard COMMIT_ID
```

### Güvenli geri alma

```powershell
git revert COMMIT_ID
```
