# VK Post Downloader

Небольшая командная утилита для загрузки текста, изображений из постов ВКонтакте.

Особенности
- Получение текста через VK API (при наличии токена).
- HTML-парсинг страницы при отсутствии API-данных.
- Скачивание изображений и видео в папку `output/` (или указанную через `--out-dir`).
- Интерактивное меню для последовательной обработки постов.

Требования
- Python 3.8+
- Зависимости: `requests`, `beautifulsoup4` (см. `requirements.txt`).

Установка
```powershell
python pip install -r requirements.txt
```

Запуск
- Интерактивно (меню):
```powershell
python main.py
```

- Без меню, через VK API (печатает только текст и скачивает медиа):
```powershell
python main.py --api --token YOUR_TOKEN https://vk.com/wall-OWNER_POSTID --out-dir media
```

Примеры
- `python main.py --api https://vk.com/wall-58074160_21758` — использует переменную окружения `VK_TOKEN` или запросит токен.

Файлы
- `main.py` — основной скрипт.
- `requirements.txt` — зависимости.
- `output/` — по умолчанию папка для сохранённых медиа (игнорируется в git).

