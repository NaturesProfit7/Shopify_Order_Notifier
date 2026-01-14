# Server Maintenance Guide

## Server Information
- **IP Address**: `146.103.108.73`
- **User**: `root`
- **Project Path**: `/home/deploy/Shopify_Order_Notifier`
- **Docker Compose Version**: Docker Compose V2 (встроенный в Docker)

## Quick Start - Подключение и проверка бота

### 1. Подключение к серверу
```bash
ssh root@146.103.108.73
```

### 2. Проверка статуса контейнеров
```bash
# Показать запущенные контейнеры
docker ps

# Показать все контейнеры (включая остановленные)
docker ps -a
```

### 3. Перезапуск бота

#### Вариант А: Быстрый перезапуск
```bash
cd /home/deploy/Shopify_Order_Notifier
docker compose restart
docker compose ps
```

#### Вариант Б: Полный перезапуск
```bash
cd /home/deploy/Shopify_Order_Notifier
docker compose down
docker compose up -d
docker compose ps
```

#### Вариант В: Перезапуск с пересборкой (после изменений в коде)
```bash
cd /home/deploy/Shopify_Order_Notifier
docker compose down
docker compose up -d --build
docker compose ps
```

### 4. Просмотр логов
```bash
cd /home/deploy/Shopify_Order_Notifier

# Последние 50 строк логов
docker compose logs --tail=50

# Логи в реальном времени
docker compose logs -f

# Логи только приложения
docker compose logs app -f

# Логи только БД
docker compose logs db -f
```

### 5. Проверка здоровья системы
```bash
# Использование диска
df -h

# Использование памяти
free -h

# Запущенные процессы
docker stats

# Подробная информация о контейнере
docker inspect shopify_order_notifier-app-1
```

## Типичные проблемы

### Бот медленно генерирует PDF (лаги 20-30 секунд)

**Симптомы**: PDF генерируется иногда за 0.3s, иногда за 20-30 секунд. Бот "зависает".

**Причина**: Нехватка памяти на сервере. Система использует swap (диск вместо RAM), что в 100 раз медленнее.

**Диагностика**:
```bash
# Проверить память и swap
free -h

# Если Swap used > 100MB - проблема в памяти
# Пример плохого состояния:
# Mem:  961Mi used: 838Mi free: 75Mi
# Swap: 1.0Gi used: 415Mi  <-- ПРОБЛЕМА!

# Проверить что потребляет память
ps aux --sort=-%mem | head -20

# Проверить активность swap (si/so должны быть 0)
vmstat 1 5
```

**Решение 1: Найти и убить зомби-процессы**
```bash
# Посмотреть процессы containerd-shim от старых контейнеров
ps aux | grep containerd-shim

# Если есть процессы с датой запуска давно в прошлом - это зомби
# Убить их (заменить PID на реальные):
sudo kill <PID1> <PID2>

# Перезапустить Docker полностью
sudo systemctl restart containerd
sleep 3
sudo systemctl start docker

# Запустить контейнеры
cd /home/deploy/Shopify_Order_Notifier
docker compose up -d
```

**Решение 2: Очистить неиспользуемые контейнеры и образы**
```bash
# Остановить ненужные контейнеры
docker stop <container_name>
docker rm <container_name>

# Очистить Docker кэш
docker system prune -a -f

# Проверить освободившуюся память
free -h
```

**Решение 3: Увеличить RAM на сервере**
Если после очистки памяти всё равно мало (< 200MB свободно) - нужно увеличить RAM до 2GB минимум.

**Нормальное состояние после исправления**:
```
Mem:  961Mi used: 537Mi free: 221Mi
Swap: 1.0Gi used: 41Mi   <-- OK!
PDF generation: 0.2-0.7s  <-- OK!
```

### Бот не запускается (Exit code 137)
Exit code 137 = процесс был убит (обычно из-за нехватки памяти)

**Решение**:
1. Проверить память: `free -h`
2. Проверить логи: `docker compose logs app --tail=100`
3. Перезапустить: `docker compose restart`

### База данных не отвечает
```bash
# Проверить статус БД
docker compose ps db

# Посмотреть логи БД
docker compose logs db --tail=50

# Перезапустить БД
docker compose restart db
```

### Контейнеры постоянно падают
```bash
# Посмотреть использование ресурсов
docker stats

# Проверить логи на ошибки
docker compose logs --tail=200

# Проверить конфигурацию
cd /home/deploy/Shopify_Order_Notifier
cat docker-compose.yml
cat .env
```

## Полезные команды

### Обновление кода на сервере
```bash
cd /home/deploy/Shopify_Order_Notifier
git pull origin master
docker compose down
docker compose up -d --build
```

### Очистка Docker ресурсов
```bash
# Удалить неиспользуемые образы
docker image prune -a

# Удалить неиспользуемые volumes
docker volume prune

# Полная очистка (осторожно!)
docker system prune -a
```

### Бэкап базы данных
```bash
# Создать бэкап
docker compose exec db pg_dump -U shopify_user shopify_orders > backup_$(date +%Y%m%d).sql

# Восстановить из бэкапа
cat backup_20231122.sql | docker compose exec -T db psql -U shopify_user shopify_orders
```

## Мониторинг

### Проверка что бот работает
```bash
# Telegram бот должен отвечать на команды
# Webhook должен быть доступен по адресу
curl http://localhost:8000/health  # если есть health endpoint
```

### Автоматический мониторинг
Рекомендуется настроить:
- **Uptime monitoring** (UptimeRobot, Pingdom)
- **Alerts** на падение контейнеров
- **Log monitoring** для ошибок

## Важные замечания

- **НЕ используйте** `docker-compose` (с дефисом) - используйте `docker compose` (с пробелом)
- Всегда проверяйте логи после перезапуска
- При изменении `.env` файла требуется перезапуск контейнеров
- Бэкапы БД делайте регулярно

## История оптимизаций

### 14.01.2026 - Оптимизация генерации PDF/VCF

**Проблема**: Бот лагал при генерации PDF (иногда до 27 секунд).

**Причины**:
1. PDF генерация блокировала event loop (синхронный код в async функции)
2. Зомби-процессы от старых контейнеров съедали ~100MB RAM
3. Система активно использовала swap из-за нехватки памяти

**Что было сделано**:

1. **Оптимизация кода** (`app/bot/routers/orders.py`):
   - Добавлен `run_in_executor` для `build_order_pdf()` - теперь PDF генерируется в отдельном потоке
   - Добавлен `run_in_executor` для `build_contact_vcf()` - аналогично для VCF
   - Бот остаётся отзывчивым во время генерации файлов

2. **Очистка сервера**:
   - Удалены неиспользуемые контейнеры warehouse-*
   - Убиты зомби-процессы containerd-shim
   - Очищен Docker кэш (`docker system prune -a`)
   - Перезапущены containerd и Docker

**Результат**:
- RAM свободно: 75MB → 221MB
- Swap: 415MB → 41MB
- PDF генерация: 0.3-27s → 0.2-0.7s (стабильно)

**Коммит**: `f9fb663` - "Оптимизация: PDF и VCF генерация теперь не блокирует event loop"

## Контакты для экстренной связи

- **Shopify Admin**: [ваш магазин].myshopify.com/admin
- **Telegram Bot**: @[ваш_бот]
