# Карта метрик

Индекс ключей и LLD по трём шаблонам. Точные выражения, единицы, интервалы,
история и пороги — в YAML рядом с `key`. Потоки данных и HTTP-ручки:
[ARCHITECTURE.md](ARCHITECTURE.md).

`*` в таблицах — семейство ключей для поиска.

## Discovery — хосты, сертификат и cluster-wide RAVPN

| Ключ / LLD | За что отвечает |
| --- | --- |
| `csp.get.list.csp.discov` | CSP host prototype, подключение CSP-controller, передача CSP_INSTANCE |
| `csp.get.list.cpe.discov` | CPE host prototype, подключение CyberEdge, передача CPE_ID/CPE_NAME |
| `csp_ui_cert.sh[{$SSL_CERT},{$UI.CERT.CERT_DIR}]` | External master, локальный PEM, опрос раз в час |
| `get.ravpn.metrics` | Единственный cluster-wide ответ `{job="ravpn"}` на seed host |
| `csp.ravpn.connections/peers/users/devices[status]` | Общие суммы по статусам |
| `csp.ravpn.users.window` | Пик online users за `{$RAVPN.USERS.WINDOW}` |
| `csp.ravpn.vpc.discov` | Те же семейства в разрезе `{#VPC_ID}` |

## CSP-controller — контроллер и сервисы

| Семейство / ключ | За что отвечает |
| --- | --- |
| `csp.cpu.guest`, `guest_nice`, `idle`, `interrupt`, `iowait`, `nice`, `softirq`, `steal`, `system`, `user` | Режимы CPU из node exporter; обработка в `preprocessing` |
| `csp.cpu.util` | Загрузка из `csp.cpu.idle` |
| `csp.cpu.num`, `csp.cpu.load.avg1/5/15` | Число CPU и load average |
| `csp.cpu.intr`, `csp.cpu.switches` | Прерывания и переключения контекста |
| `csp.mem.avail/total/util`, `csp.swap.free/total/pfree/pused` | RAM, swap и расчётные проценты |
| `csp.fd.open`, `csp.krnl.maxfiles` | Открытые файловые дескрипторы и лимит |
| `csp.network.current_established` | Текущее число установленных TCP-соединений |
| `csp.node.role`, `csp.node.master` | Роль узла и флаг master для service alerts |
| `csp.system.*`, `csp.agent.version` | Имя, ОС, архитектура, часы, boot time, uptime, версия exporter |

| LLD key | Создаваемые метрики / где менять |
| --- | --- |
| `csp.get.list.cpe.discov` | `cpe.status.list[{#CPE_NAME}, {#CPE_ID}]` и дополнительный CPE host prototype |
| `csp.net.if.discov` | `net.if.in/out*` — трафик, пакеты, drops/errors; `net.if.speed*` — скорость/загрузка; `net.if.status` — состояние |
| `csp.services.discov` | `csp.stat.service[...]` — состояние контейнера, `csp.rst.auto.count.service[...]` — рестарты; filters/overrides и SERVICE_LIST_01–06 определяют набор сервисов |
| `csp.vfs.dev.discov` | `vfs.dev.*` — очередь, чтение/запись, время ожидания и загрузка блочного устройства |
| `csp.vfs.fs.discov` | `vfs.fs.*` — total/free/used, процент заполнения, свободные inode |

Фильтры интерфейсов: `{$NET.IF.IFNAME.*}`.

Фильтры дисков: `{$VFS.DEV.DEVNAME.*}`;

Пороги задержки: `{$VFS.DEV.READ.AWAIT.WARN}` и `{$VFS.DEV.WRITE.AWAIT.WARN}`.

Фильтры ФС: `{$VFS.FS.FSDEVICE.*}`, `{$VFS.FS.FSNAME.*}`, `{$VFS.FS.FSTYPE.*}`.

`csp.services.discov` питается от **get.csp.metrics**, хотя роль берётся из
**get.svc.metrics**. `HostServiceIsDown` сейчас проверяет `state - master < 0`:
при значениях 0/1 это отказ только на master. Группы 01/02 содержат одноразовые jobs;
для изменения алертов сначала задайте ожидаемые состояния каждой группы на master/slave.

## CyberEdge — CPE

| Семейство / ключ | За что отвечает |
| --- | --- |
| `cpe.avail.status`, `cpe.uptime` | Доступность по `up` и время работы |
| `cpe.conntr.ses.max`, `cpe.contr.ses.percent` | Лимит и заполнение conntrack; написание keys сохранено из исходника |
| `cpe.cpu.idle/intr/nice/softirq/steal/sys/usr/wait` | Режимы CPU из collectd |
| `cpe.mem.buff/cach/free/slre/slun/used/total/used.perc` | Компоненты RAM, сумма и доля занятой памяти |

Удалены пять отключённых unusual-traffic trigger prototypes, четыре старых
traffic prototypes с множителем ×8 и два legacy-графика (11 UUID).
Состав и эффект — в [REMOVAL_LEGACY_TRAFFIC.md](REMOVAL_LEGACY_TRAFFIC.md).
Raw/rate-метрики, графики скорости и обе сетевые LLD сохранены.
Два graph prototype качества с `discover: NO_DISCOVER` удалены:
[REMOVAL_NO_DISCOVER.md](REMOVAL_NO_DISCOVER.md).

## Известные ограничения

| Место | Ограничение / что проверить перед правкой |
| --- | --- |
| CPU, network, disk rates | Ряд накопительных counters используется без преобразования по времени. CSP CPU требует проверки преобразования counters в проценты; названия и units не гарантируют правильный расчёт |
| `last(...,#5)` | Это пятое последнее значение, а не условие за пять минут. Окно каждого алерта нужно определить отдельно |
| CyberEdge `*.rate` | Зависит от raw и истории `#4`; Проверить reset и реальные интервалы |
| `net.if.speed.util` CSP | Отношение показателей скорости не измеряет фактический трафик |
| CPE discovery в CSP-controller | Помимо создания хостов содержит уникальный status prototype; целиком удалять как дубль нельзя без решения о статусе и владельцах хостов |
| CyberEdge DOMAIN | Default содержит `mon.`, хотя URL добавляет его сам.|
| LLD-макросы | 10 предупреждений: отсутствует `{#IFALIAS}` для CSP-графика и 9 употреблений `{#CPE_ID}` вне объявленного контекста |
| CSP swap | `pfree/pused` сохраняются; при total=0 показывают 100% free / 0% used. `HostSwapIsFillingUp` проверяет used >80% за окно 5 минут |
| CSP filesystem filter | Одно условие использует FSNAME вместо FSDEVICE. Нужен тест пользовательского device filter |
| CyberEdge bzmon | Замены labels в LLD могут расходиться с исходными item selectors |
| CyberEdge filesystem/process/memory | Проверить намеренное включение tmp/overlay, направление `HostIncreaseOfProcesses`, состав суммы RAM и slab |
| PEM | Ошибка чтения/разбора файла не превращается в JSON для `UiCertInvalid`; контролировать также unsupported items |
