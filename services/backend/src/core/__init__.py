"""Аналитическое ядро digital-echo-core.

Содержит:
- edges.py        — SQL-запросы к MySQL и утилиты подключения.
- voltdb_client.py — низкоуровневый клиент VoltDB.
- volt_resolver.py — пакетный lookup БИН → резидентность.
- kz_index.py      — расчёт индекса КС и аналитические виды.
- explore.py       — EDA по графу.
- check_company.py — точечная проверка одного БИН.
"""
