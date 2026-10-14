# Архитектура

Проект содержит три шаблона Zabbix 6.0. Канонические исходники — YAML;
XML в `dist` генерируется для импорта.
Ключи, LLD и как их менять: [METRICS.md](METRICS.md).
Команды сборки и установки: [BUILD_AND_INSTALL.md](BUILD_AND_INSTALL.md).
Зачем скрипты: [TOOLING.md](TOOLING.md).
Что проверяют тесты: [TESTING.md](TESTING.md).

## Навигация по репозиторию

| Файл / каталог | Что здесь менять или искать |
| --- | --- |
| [src/templates/00-group.yaml](../src/templates/00-group.yaml) | Группа шаблонов и `version: '6.0'`. Поле `date` служебное, не трогать — [зачем оно](TOOLING.md#дата-и-версия-экспорта) |
| [src/templates/discovery.yaml](../src/templates/discovery.yaml) | Создание CSP/CPE-хостов, portal PEM и единственный cluster-wide RAVPN collector |
| [src/templates/csp-controller.yaml](../src/templates/csp-controller.yaml) | Метрики CSP, сервисы, роль узла, диски и сеть |
| [src/templates/cyberedge.yaml](../src/templates/cyberedge.yaml) | Метрики CPE, bzmon/физические интерфейсы и процессы |
| [profiles/zabbix-6.0.yaml](../profiles/zabbix-6.0.yaml) | Порядок исходников и путь к XML |
| [externalscripts/csp_ui_cert.sh](../externalscripts/csp_ui_cert.sh) | Чтение локального PEM и выдача JSON для Discovery |
| [scripts/build.py](../scripts/build.py) | Сборка YAML -> XML |
| [scripts/template_io.py](../scripts/template_io.py), [inventory.py](../scripts/inventory.py), [validate.py](../scripts/validate.py) | Внутренности сборщика и справка по ссылкам — [TOOLING.md](TOOLING.md) |
| [tests/test_metrics.py](../tests/test_metrics.py) | Автономные проверки структуры и регрессий — [TESTING.md](TESTING.md) |
| [dist/zabbix-6.0/CSP_all_templates.xml](../dist/zabbix-6.0/CSP_all_templates.xml) | Готовый артефакт, вручную не редактировать |

## Как идут данные

```text
Seed-хост + Discovery
  get.csp.list -> CSP discovery -> CSP-хост + CSP-controller
  get.cpe.list -> CPE discovery -> CPE-хост + CyberEdge
  csp_ui_cert.sh -> JSON -> csp.ui.cert.* -> certificate triggers
  get.ravpn.metrics -> общие RAVPN items + VPC discovery

CSP-хост
  get.csp.metrics -> CPU / память / система / сеть / диски / контейнеры
  get.svc.metrics -> csp.node.role -> csp.node.master -> service triggers
  get.cpe.list -> CPE discovery -> CPE host prototype + cpe.status.list[...]

CPE-хост
  get.cpe.metrics -> CPU / память / conntrack / uptime / availability
                  -> bzmon / physical / filesystem / process discovery
```

HTTP master получает полный ответ Prometheus. `DEPENDENT` item извлекает из него
серии через `preprocessing`; `CALCULATED` item использует другие keys в `params`.
LLD находит сущности и создаёт items, triggers, graphs
или хосты из prototypes. Пользовательские макросы `{$...}` задают конфигурацию;
`{#...}` доступны в контексте соответствующего LLD.

### Источники HTTP

Все URL начинаются с `{$PROTO}://mon.{$DOMAIN}`; HTTP items используют
`{$SSL_CERT}` и `{$SSL_KEY}`

| Шаблон / master key | Путь и `match[]` | Назначение |
| --- | --- | --- |
| Discovery / `get.csp.list` | `/mon/csp`, без query | `node_uname_info` -> имя и instance CSP |
| Discovery и CSP-controller / `get.cpe.list` | `/mon/cpe-list`, без query | `up` -> CPE ID, имя и статус |
| CSP-controller / `get.csp.metrics` | `/mon/cpe-metrics`; `{job="exporters",instance=~"{$CSP_INSTANCE}.*"}` | Системные и контейнерные exporters |
| CSP-controller / `get.svc.metrics` | `/mon/cpe-metrics`; `{job="services",instance=~"{$CSP_INSTANCE}"}` | Роль CSP-узла |
| Discovery / `get.ravpn.metrics` | `/mon/cpe-metrics`; `{job="ravpn"}` | Прикладные Gauge RAVPN (одна cluster-wide копия на seed host) |
| CyberEdge / `get.cpe.metrics` | `/mon/cpe-metrics`; `{job="node",kind="cpe",cpe_id="{$CPE_ID}"}` | Метрики конкретного CPE |

Discovery передаёт CSP-хосту `{$CSP_INSTANCE}` (IPv4 без порта через `regsub`),
CPE-хосту — `{$CPE_ID}` и `{$CPE_NAME}`.
