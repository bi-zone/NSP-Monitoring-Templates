# NSP-Monitoring-Templates

Мониторинг девайсов и CSP-контроллеров.
Три шаблона собираются из YAML в один XML формата Zabbix 6.0.

- **[Архитектура](docs/ARCHITECTURE.md)** — потоки данных, HTTP-ручки, RAVPN.
- **[Карта метрик](docs/METRICS.md)** — ключи, LLD, ограничения, как добавлять item.
- **[Сборка, установка и проверка](docs/BUILD_AND_INSTALL.md)** — команды для Linux/macOS размещение файлов, макросы, импорт шаблонов.
- **[Инструменты репозитория](docs/TOOLING.md)** — дата экспорта, сборщик, внутренние скрипты.
- **[Тесты](docs/TESTING.md)** — автономные проверки структуры и логики RAVPN.

## Быстрый старт

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

1) Для установки возьмите [готовый XML](dist/zabbix-6.0/CSP_all_templates.xml)
и импортируйте через **Configuration -> Templates -> Import**.

2) Создайте новый хост, например **CSP.**
3) В Groups: **BI.ZONE Secure SD-WAN**
4) Создайте Агента **Interfaces -> Agents -> add** оставляем значения по умолчанию
5) В Templates: **BI.ZONE Secure SD-WAN. Discovery template**
6) Переходим на вкладку Macros и прописываем:

**{$DOMAIN}** : csp.local (указываем без приписки ui)

**{$SSL_CERT}** : portal-cert.pem (указываем название файла из пунктов выше)

**{$SSL_KEY}** : portal-key.pem (указываем название файла из пунктов выше)

## Разработка

Python нужен только для изменения и сборки шаблонов; для тестов нужен также Node.js 18+.
Для разработки из корня репозитория (Python 3.11):

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build.py
.venv/bin/python scripts/build.py --check
.venv/bin/python scripts/validate.py
.venv/bin/python -m unittest discover -s tests -v
```

Правки записывайте в `src/templates/*.yaml`, затем пересобирайте
`dist/zabbix-6.0/CSP_all_templates.xml`. Исходники и собранный XML сохраняйте
одним изменением в Git. YAML-фрагменты по отдельности не импортируются.

## Состояние проекта

Сейчас имеется **214 UUID** объектов шаблонов (метрики, discovery, триггеры, графики и другие сущности).
