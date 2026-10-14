## 1. Окружение разработчика

Нужны Python 3.11+ и PyYAML из `requirements.txt`; для тестов JavaScript нужен Node.js 18+.

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import sys, yaml; print(sys.version); print(yaml.__version__)'
```

## 2. Что редактировать и как собрать

1. Проверьте исходное состояние: `git status --short` и:

   ```sh
   .venv/bin/python scripts/build.py --check
   ```

   Ожидается `PASS: dist matches source (214 UUIDs)`.

   `STALE/MISSING` означает, что XML отсутствует или отличается от сборки;
   перед перезаписью посмотрите `git diff`.

2. Правьте соответствующий файл `src/templates/*.yaml`. Объекты, ключи и точки
   добавления перечислены в архитектуре. Вручную менять `dist` не нужно.
3. Запишите YAML и соберите:

   ```sh
   .venv/bin/python scripts/build.py --profile zabbix-6.0
   .venv/bin/python scripts/build.py --check
   ```

Результат всегда один: **`dist/zabbix-6.0/CSP_all_templates.xml`**.
Список и порядок исходников берутся из `profiles/zabbix-6.0.yaml`.
Сборщик записывает XML атомарно; повторная сборка даёт те же байты,
не меняет дату экспорта и не генерирует новые UUID. `--check` файлов не записывает.
Другие профили, в том числе Glaber, завершаются ошибкой как неподдерживаемые.

## 3. Проверки перед сохранением изменения

```sh
.venv/bin/python scripts/validate.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/inventory.py --format markdown
git diff --check
```
Ожидаемые результаты:

- `validate.py`: `errors: []`;
- unittest: структура шаблонов и JavaScript RAVPN проходят автономные проверки;
- inventory: внутренние ссылки нашего XML без ошибок; 10 известных предупреждений LLD scope описаны в архитектуре.

`validate.py` проверяет поддерживаемую структуру и ссылки нашего XML.
Он не исполняет Prometheus/JavaScript на живом CSP.

Покрытие и ограничения тестов: [TESTING.md](TESTING.md).
Что делают скрипты: [TOOLING.md](TOOLING.md).

## 4. Установка на Zabbix-docker

1) Склонируйте репозиторий
```sh
git clone --branch 6.0 --depth 1 https://github.com/zabbix/zabbix-docker.git

cd zabbix-docker
```

2) запуск
```sh
ZBX_WEB_NGINX_HTTP_PORT=8888 docker compose -f docker-compose_v3_alpine_mysql_latest.yaml up -d
```
доступен на localhost:8888

3) Нужно иметь portal2.p12 и разложить его на сертификат и ключ:
```sh
sudo openssl pkcs12 -in portal2.p12 -clcerts -nokeys -out portal-cert.pem

sudo openssl pkcs12 -in portal2.p12 -legacy -nocerts -nodes -out portal-key.pem
```
Может потребоваться добавить -legacy

4) После чего положить файлы и выдать права:
```sh
sudo cp portal-cert.pem zbx_env/var/lib/zabbix/ssl/certs/portal-cert.pem
sudo cp portal-key.pem zbx_env/var/lib/zabbix/ssl/keys/portal-key.pem

sudo chmod 644 zbx_env/var/lib/zabbix/ssl/certs/portal-cert.pem
sudo chmod 640 zbx_env/var/lib/zabbix/ssl/keys/portal-key.pem
```

5) положить файл со скриптом:
```sh
sudo cp ../externalscripts/csp_ui_cert.sh zbx_env/usr/lib/zabbix/externalscripts/csp_ui_cert.sh

sudo chmod 755 zbx_env/usr/lib/zabbix/externalscripts/csp_ui_cert.sh
```

- - -

1) Для установки возьмите [готовый XML](../dist/zabbix-6.0/CSP_all_templates.xml)
и импортируйте через **Configuration -> Templates -> Import**.

2) Создайте новый хост, например **CSP.**
3) В Groups: **BI.ZONE Secure SD-WAN**
4) Создайте Агента **Interfaces -> Agents -> add** оставляем значения по умолчанию
5) В Templates: **BI.ZONE Secure SD-WAN. Discovery template**
6) Переходим на вкладку Macros и прописываем:

**{$DOMAIN}** : csp.local (указываем без приписки ui)

**{$SSL_CERT}** : portal-cert.pem (указываем название файла из пунктов выше)

**{$SSL_KEY}** : portal-key.pem (указываем название файла из пунктов выше)
