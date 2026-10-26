# data_inbox

Tarayıcıdan elle kaydedilen TJK sayfalarını (ör. `2025-06-25_Istanbul.html`) buraya koyun.
Bu klasördeki .html/.json dosyaları git'e eklenmez (TJK içeriği depoda yeniden yayımlanmaz).

```bash
cd backend
.venv/Scripts/python -m horseiq.cli import-tjk-html ../data_inbox/2025-06-25_Istanbul.html --date 2025-06-25 --track İstanbul
```
