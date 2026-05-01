"""digital-echo-core: пакетный lookup БИН → резидентность через VoltDB.taxpayer.

Подключает справочник из VoltDB к графу из MySQL.

Особенности:
  - БИН/ИИН в MySQL хранятся как BIGINT UNSIGNED (без ведущих нулей).
  - БИН/ИИН в VoltDB.taxpayer хранятся как VARCHAR(12) (с ведущими нулями).
  - Это нормализуется автоматически в `_pad`.

Использование:
    from voltdb_client import VoltDBClient
    from volt_resolver import TaxpayerResolver

    with VoltDBClient.from_env() as volt:
        r = TaxpayerResolver(volt)
        info = r.lookup_batch(['20240000555', '130240013649'])
        # {
        #   '20240000555':  {'resident': 1, 'name': 'Company 436838', 'state': 1},
        #   '130240013649': {'resident': 0, 'name': 'Company 2515046', 'state': 1},
        # }
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from .voltdb_client import VoltDBClient


# Безопасный размер чанка для IN-клаузы в VoltDB @AdHoc.
# VoltDB ограничивает длину сериализованного запроса ~2 МБ, а число параметров —
# несколькими тысячами. 1000 — консервативное значение, отлично работает.
DEFAULT_CHUNK_SIZE = 1000

# 12-символьный формат БИН/ИИН, как в VoltDB.taxpayer (колонка TIN)
BIN_LENGTH = 12


def _pad(tin: str | int) -> str:
    """Нормализация БИН/ИИН к 12-символьному виду с ведущими нулями."""
    s = str(tin).strip()
    return s.zfill(BIN_LENGTH) if s else s


class TaxpayerResolver:
    """Кэширующий резолвер справочника TAXPAYER в VoltDB."""

    def __init__(self, volt: VoltDBClient, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        self._volt = volt
        self._chunk_size = chunk_size
        self._cache: dict[str, dict] = {}
        # Узлы, которых в TAXPAYER не оказалось (None-ответ кэшируется отдельно)
        self._missing: set[str] = set()

    # ------------------------------------------------------------------
    def lookup_batch(self, tins: Iterable[str | int]) -> dict[str, dict]:
        """Возвращает {tin_padded: {'resident', 'name', 'state', 'type'}}.

        Ключи в результате — 12-символьные БИН/ИИН с ведущими нулями.
        Если ключа нет в результате — идентификатор не найден в TAXPAYER.
        """
        unique = sorted({_pad(t) for t in tins if str(t).strip()})

        # Что уже есть в кэше — не запрашиваем
        to_fetch = [t for t in unique
                    if t not in self._cache and t not in self._missing]

        if to_fetch:
            self._fetch_chunks(to_fetch)

        # Собираем ответ по запрошенным
        return {t: self._cache[t] for t in unique if t in self._cache}

    def is_resident(self, tin: str | int) -> bool | None:
        """Удобная обёртка: True/False/None (если узел не найден в справочнике)."""
        padded = _pad(tin)
        if padded in self._cache:
            return bool(self._cache[padded].get("resident"))
        if padded in self._missing:
            return None
        # Один запрос
        self._fetch_chunks([padded])
        if padded in self._cache:
            return bool(self._cache[padded].get("resident"))
        return None

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        return {
            "cached": len(self._cache),
            "missing": len(self._missing),
        }

    # ------------------------------------------------------------------ внутренности

    def _fetch_chunks(self, tins: list[str]) -> None:
        for i in range(0, len(tins), self._chunk_size):
            chunk = tins[i : i + self._chunk_size]
            self._fetch_chunk(chunk)

    def _fetch_chunk(self, tins: list[str]) -> None:
        if not tins:
            return
        # Защита от SQL-инъекции: только цифры. Проверяем явно.
        sanitized = [t for t in tins if t.isdigit() and len(t) == BIN_LENGTH]
        if not sanitized:
            return

        in_clause = "','".join(sanitized)
        sql = (
            "SELECT TIN, NAME_RU, RESIDENT, STATE, TYPE "
            "FROM TAXPAYER "
            f"WHERE TIN IN ('{in_clause}')"
        )
        df: pd.DataFrame = self._volt.query(sql)

        found: set[str] = set()
        if not df.empty:
            for _, row in df.iterrows():
                tin = str(row["TIN"])
                self._cache[tin] = {
                    "resident": (None if pd.isna(row["RESIDENT"]) else int(row["RESIDENT"])),
                    "name": (None if pd.isna(row["NAME_RU"]) else str(row["NAME_RU"])),
                    "state": (None if pd.isna(row["STATE"]) else int(row["STATE"])),
                    "type": (None if pd.isna(row["TYPE"]) else int(row["TYPE"])),
                }
                found.add(tin)

        for t in sanitized:
            if t not in found:
                self._missing.add(t)
