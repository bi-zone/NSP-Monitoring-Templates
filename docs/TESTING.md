# Тесты шаблонов

Тесты автономны: снимки Prometheus, данные стенда и сетевой доступ не нужны.
Нужны Python 3.11+, PyYAML из `requirements.txt` и Node.js 18+ для исполнения
JavaScript preprocessing RAVPN. Отсутствие Node.js считается ошибкой проверки.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/build.py --check
.venv/bin/python scripts/validate.py
.venv/bin/python -m unittest discover -s tests -v
```

`test_metrics.py` проверяет сборку и внутренние ссылки, формулы swap и отсутствие
удалённых неподдерживаемых discovery/prototypes.
`test_ravpn.py` исполняет JavaScript из YAML на небольших искусственных рядах,
заданных непосредственно в тесте: суммы по статусам и VPC, несколько устройств,
явные нули, отсутствие серий и уникальность VPC discovery.

### Исходные captures и их manifest удалены из публичной версии.