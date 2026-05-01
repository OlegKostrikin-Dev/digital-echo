"""digital-echo-core: тонкий клиент VoltDB для справочников компаний (PROFILE, TAX_ORGANIZATION и др.).

Зачем:
  В MySQL лежат ЭСФ-транзакции, в VoltDB — справочники налогоплательщиков.
  Чтобы понять, кто из узлов графа резидент/нерезидент, нужно делать lookup по БИН.

Использование:
    from voltdb_client import VoltDBClient

    with VoltDBClient.from_env() as volt:
        df = volt.query("SELECT * FROM PROFILE LIMIT 5")
        tables = volt.list_tables()
"""

from __future__ import annotations

import os
from contextlib import AbstractContextManager
from typing import Any, Iterable

import pandas as pd
from dotenv import load_dotenv

try:
    from voltdbclient import FastSerializer, VoltProcedure  # type: ignore
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "voltdbclient не установлен. Добавьте 'voltdbclient' в requirements.txt "
        "и пересоберите образ: docker compose build"
    ) from exc


# Стандартный клиентский порт VoltDB
DEFAULT_PORT = 21212


class VoltDBConfigError(RuntimeError):
    """Не заданы обязательные переменные окружения для VoltDB."""


class VoltDBClient(AbstractContextManager["VoltDBClient"]):
    """Контекстный клиент VoltDB.

    Поддерживает несколько хостов кластера через connect() — клиент сам выберет живой.
    """

    def __init__(
        self,
        hosts: Iterable[str],
        port: int = DEFAULT_PORT,
        user: str | None = None,
        password: str | None = None,
    ) -> None:
        self._hosts = [h.strip() for h in hosts if h and h.strip()]
        if not self._hosts:
            raise VoltDBConfigError("Список VoltDB-хостов пуст.")
        self._port = port
        self._user = user or ""
        self._password = password or ""
        self._fs: FastSerializer | None = None

    # ------------------------------------------------------------------ env
    @classmethod
    def from_env(cls, dotenv: bool = True) -> "VoltDBClient":
        if dotenv:
            load_dotenv()

        hosts_raw = os.getenv("VOLTDB_HOSTS", "")
        port_raw = os.getenv("VOLTDB_PORT", str(DEFAULT_PORT))
        user = os.getenv("VOLTDB_USER", "") or None
        password = os.getenv("VOLTDB_PASSWORD", "") or None

        if not hosts_raw.strip():
            raise VoltDBConfigError(
                "Переменная VOLTDB_HOSTS не задана. "
                "Заполните её в .env (можно несколько хостов через запятую)."
            )
        hosts = [h.strip() for h in hosts_raw.split(",") if h.strip()]
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise VoltDBConfigError(f"Неверный VOLTDB_PORT={port_raw!r}") from exc

        return cls(hosts=hosts, port=port, user=user, password=password)

    # ---------------------------------------------------------- connection
    def connect(self) -> None:
        """Подключиться к первому доступному хосту из списка."""
        last_exc: Exception | None = None
        for host in self._hosts:
            try:
                self._fs = FastSerializer(
                    host=host,
                    port=self._port,
                    username=self._user,
                    password=self._password,
                )
                return
            except Exception as exc:  # voltdbclient бросает разные типы
                last_exc = exc
                continue
        raise ConnectionError(
            f"Не удалось подключиться ни к одному из VoltDB-хостов: {self._hosts}"
        ) from last_exc

    def close(self) -> None:
        if self._fs is not None:
            try:
                self._fs.close()
            except Exception:
                pass
            self._fs = None

    def __enter__(self) -> "VoltDBClient":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------- queries
    def _ensure_connected(self) -> FastSerializer:
        if self._fs is None:
            raise RuntimeError("VoltDBClient не подключён. Используйте `with` или вызовите connect().")
        return self._fs

    def call_procedure(self, name: str, params: list[Any] | None = None) -> list[pd.DataFrame]:
        """Вызывает хранимую процедуру. Возвращает список таблиц-результатов как DataFrame."""
        fs = self._ensure_connected()
        proc = VoltProcedure(fs, name, [self._infer_type(p) for p in (params or [])])
        response = proc.call(params or [])

        if response is None:
            return []
        if getattr(response, "status", 1) != 1:
            status_str = getattr(response, "statusString", "?")
            raise RuntimeError(f"VoltDB procedure {name!r} failed: status={response.status}, msg={status_str}")

        result: list[pd.DataFrame] = []
        for table in getattr(response, "tables", []):
            cols = [c.name for c in table.columns]
            rows = list(table.tuples)
            df = pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)
            result.append(df)
        return result

    def query(self, sql: str) -> pd.DataFrame:
        """Выполняет произвольный SQL через @AdHoc. Возвращает первую таблицу-результат."""
        tables = self.call_procedure("@AdHoc", [sql])
        return tables[0] if tables else pd.DataFrame()

    # ----------------------------------------------------- system catalog
    def list_tables(self) -> pd.DataFrame:
        """Список всех таблиц через @SystemCatalog('TABLES')."""
        tables = self.call_procedure("@SystemCatalog", ["TABLES"])
        return tables[0] if tables else pd.DataFrame()

    def list_columns(self, table_name: str | None = None) -> pd.DataFrame:
        """Колонки всех таблиц (или одной, если задано имя)."""
        tables = self.call_procedure("@SystemCatalog", ["COLUMNS"])
        df = tables[0] if tables else pd.DataFrame()
        if table_name and "TABLE_NAME" in df.columns:
            df = df[df["TABLE_NAME"].str.upper() == table_name.upper()].reset_index(drop=True)
        return df

    def list_procedures(self) -> pd.DataFrame:
        tables = self.call_procedure("@SystemCatalog", ["PROCEDURES"])
        return tables[0] if tables else pd.DataFrame()

    # ----------------------------------------------------------- helpers
    @staticmethod
    def _infer_type(value: Any) -> int:
        """Грубое сопоставление Python-типа с VoltDB-типом для VoltProcedure."""
        if isinstance(value, bool):
            return FastSerializer.VOLTTYPE_TINYINT
        if isinstance(value, int):
            return FastSerializer.VOLTTYPE_BIGINT
        if isinstance(value, float):
            return FastSerializer.VOLTTYPE_FLOAT
        return FastSerializer.VOLTTYPE_STRING
