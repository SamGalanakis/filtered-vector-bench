"""PostgreSQL + pgvector HNSW adapter."""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np
import psycopg
from numpy.typing import NDArray

from fvb.config import EngineConfig, TextConfig
from fvb.engines.base import Engine, PhaseStats, Row, directory_size, row_parts


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _vector(value: NDArray[np.float32]) -> str:
    return "[" + ",".join(format(float(item), ".9g") for item in value) + "]"


class PostgresEngine(Engine):
    """One isolated PostgreSQL cluster or pgvector container."""

    name = "postgres"

    def __init__(self, workdir: Path, dimensions: int, timeout: int, memory_cap_bytes: int,
                 settings: EngineConfig, text: TextConfig) -> None:
        super().__init__(workdir, dimensions, timeout, memory_cap_bytes)
        self.settings = settings
        self.text = text
        self.port = _free_port()
        self.container = f"fvb-postgres-{self.port}"
        self.process: subprocess.Popen[bytes] | None = None
        self._query_connection: psycopg.Connection[Any] | None = None
        self.pgdata = workdir / "data"
        self.dsn = f"host=127.0.0.1 port={self.port} dbname=postgres user=postgres"

    def prepare(self) -> None:
        """Initialize a durable cluster and apply parity settings."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.pgdata.mkdir(exist_ok=True)
        if self.settings.mode == "docker":
            self.pgdata.chmod(0o777)
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
            subprocess.run([
                "docker", "create", "--name", self.container, "--memory", str(self.memory_cap_bytes),
                "-p", f"127.0.0.1:{self.port}:5432", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                "-e", "POSTGRES_USER=postgres", "-v", f"{self.pgdata.resolve()}:/var/lib/postgresql/data",
                self.settings.image or "pgvector/pgvector:pg17", "postgres", "-c",
                "synchronous_commit=on", "-c", "listen_addresses=*",
            ], check=True, capture_output=True)
        else:
            for binary in ("initdb", "postgres"):
                if not shutil.which(binary):
                    raise FileNotFoundError(f"{binary} is required on PATH for local PostgreSQL mode")
            subprocess.run(["initdb", "-D", str(self.pgdata), "--auth=trust", "--username=postgres",
                            "--no-instructions"], check=True, capture_output=True)
            with (self.pgdata / "postgresql.conf").open("a", encoding="utf-8") as handle:
                handle.write(f"\nlisten_addresses='127.0.0.1'\nport={self.port}\n")
                handle.write("unix_socket_directories=''\nsynchronous_commit=on\n")

    def start(self) -> float:
        """Start PostgreSQL and wait for a successful connection."""
        started = time.perf_counter()
        if self.settings.mode == "docker":
            subprocess.run(["docker", "start", self.container], check=True, capture_output=True)
        else:
            command, preexec = self.limited_command(["postgres", "-D", str(self.pgdata)])
            log = (self.workdir / "postgres.log").open("ab")
            self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                            preexec_fn=preexec)  # type: ignore[arg-type]
        deadline = time.monotonic() + self.timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with psycopg.connect(self.dsn, connect_timeout=2):
                    return time.perf_counter() - started
            except psycopg.Error as error:
                last_error = error
            if self.settings.mode == "docker":
                status = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", self.container],
                    text=True, capture_output=True,
                ).stdout.strip()
                if status.startswith("false"):
                    logs = subprocess.run(["docker", "logs", self.container], text=True,
                                          capture_output=True).stderr[-2000:]
                    raise RuntimeError(f"PostgreSQL container exited ({status}): {logs}")
            if self.settings.mode != "docker" and self.process and self.process.poll() is not None:
                raise RuntimeError(f"PostgreSQL exited with {self.process.returncode}")
            time.sleep(0.2)
        raise TimeoutError(f"PostgreSQL did not become ready: {last_error}")

    def stop(self) -> None:
        """Stop the server while retaining its cluster."""
        if self._query_connection is not None:
            self._query_connection.close()
            self._query_connection = None
        if self.settings.mode == "docker":
            subprocess.run(["docker", "stop", "-t", "30", self.container], capture_output=True)
        elif self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None

    def load(self, rows: Iterable[Sequence[Row]]) -> PhaseStats:
        """Create schema and stream rows with text COPY."""
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
            text_columns = (
                ", content text NOT NULL, search_document tsvector GENERATED ALWAYS AS "
                "(to_tsvector('english', content)) STORED"
                if self.text.enabled else ""
            )
            connection.execute(
                f"CREATE TABLE item(source_id integer PRIMARY KEY, tenant text NOT NULL, "
                f"embedding vector({self.dimensions}) NOT NULL{text_columns})"
            )
            connection.execute("CREATE INDEX item_tenant_idx ON item(tenant)")
        started = time.perf_counter()
        count = 0
        with psycopg.connect(self.dsn) as connection:
            columns = "source_id, tenant, embedding, content" if self.text.enabled else (
                "source_id, tenant, embedding"
            )
            with connection.cursor().copy(f"COPY item({columns}) FROM STDIN") as copy:
                for batch in rows:
                    for row in batch:
                        source_id, tenant, vector, content = row_parts(row)
                        values = (source_id, tenant, _vector(vector), content) if self.text.enabled else (
                            source_id, tenant, _vector(vector)
                        )
                        copy.write_row(values)
                    count += len(batch)
            connection.commit()
        elapsed = time.perf_counter() - started
        return PhaseStats(elapsed, count, self.disk_bytes(), {"format": "COPY text"})

    def build_index(self) -> PhaseStats:
        """Build HNSW after load using pgvector defaults."""
        started = time.perf_counter()
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute("""
                CREATE INDEX item_embedding_hnsw_idx ON item
                USING hnsw (embedding vector_cosine_ops) WITH (m=16, ef_construction=64)
            """)
        vector_seconds = time.perf_counter() - started
        text_seconds = 0.0
        if self.text.enabled:
            text_started = time.perf_counter()
            with psycopg.connect(self.dsn, autocommit=True) as connection:
                connection.execute(
                    "CREATE INDEX item_search_document_gin_idx ON item USING gin (search_document)"
                )
            text_seconds = time.perf_counter() - text_started
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            connection.execute("ANALYZE item")
        elapsed = time.perf_counter() - started
        return PhaseStats(elapsed, disk_bytes=self.disk_bytes(), details={
            "hnsw_parameters": {"m": 16, "ef_construction": 64, "source": "pgvector defaults"},
            "vector_index_seconds": vector_seconds,
            "text_index_seconds": text_seconds if self.text.enabled else None,
            "text_index": "GIN over generated english tsvector" if self.text.enabled else None,
        })

    @staticmethod
    def _mode_value(mode: str) -> str:
        return "off" if mode == "default" else mode

    def _sql(self, tenant: str | None, k: int, explain: bool = False) -> str:
        prefix = "EXPLAIN (FORMAT JSON) " if explain else ""
        where = "WHERE tenant = %s " if tenant is not None else ""
        return f"{prefix}SELECT source_id FROM item {where}ORDER BY embedding <=> %s::vector LIMIT {k}"

    def _query_session(self) -> psycopg.Connection[Any]:
        """Keep one backend alive so query-phase process-tree samples include it."""
        if self._query_connection is None or self._query_connection.closed:
            self._query_connection = psycopg.connect(self.dsn, autocommit=True)
            self._query_connection.execute(f"SET statement_timeout = '{int(self.timeout)}s'")
        return self._query_connection

    def query(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
              mode: str = "default") -> tuple[list[int], float]:
        """Run an idiomatic pgvector cosine query with session search settings."""
        args = (tenant, _vector(vector)) if tenant is not None else (_vector(vector),)
        connection = self._query_session()
        connection.execute(f"SET hnsw.ef_search = {int(ef)}")
        connection.execute(f"SET hnsw.iterative_scan = {self._mode_value(mode)}")
        started = time.perf_counter()
        result = connection.execute(self._sql(tenant, k), args).fetchall()
        elapsed = time.perf_counter() - started
        return [int(row[0]) for row in result], elapsed

    def explain(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
                mode: str = "default") -> str:
        """Capture JSON EXPLAIN for the exact query and session settings."""
        args = (tenant, _vector(vector)) if tenant is not None else (_vector(vector),)
        connection = self._query_session()
        connection.execute(f"SET hnsw.ef_search = {int(ef)}")
        connection.execute(f"SET hnsw.iterative_scan = {self._mode_value(mode)}")
        plan = connection.execute(self._sql(tenant, k, explain=True), args).fetchone()
        if plan is None:
            raise RuntimeError("PostgreSQL EXPLAIN returned no row")
        return json.dumps(plan[0], sort_keys=True)

    def plan_uses_index(self, plan: str) -> bool:
        """Require the named HNSW index and an index scan node."""
        lowered = plan.lower()
        return "item_embedding_hnsw_idx" in lowered and "index scan" in lowered

    def _text_sql(self, tenant: str | None, k: int, explain: bool = False) -> str:
        prefix = "EXPLAIN (FORMAT JSON) " if explain else ""
        tenant_clause = "AND tenant = %s " if tenant is not None else ""
        return (
            f"{prefix}WITH query AS (SELECT plainto_tsquery('english', %s) AS value) "
            "SELECT source_id FROM item, query "
            f"WHERE search_document @@ query.value {tenant_clause}"
            "ORDER BY ts_rank_cd(search_document, query.value) DESC, source_id LIMIT "
            f"{int(k)}"
        )

    def text_query(self, query: str, tenant: str | None, k: int) -> tuple[list[int], float]:
        """Run stock PostgreSQL lexical ranking over an english tsvector."""
        args = (query, tenant) if tenant is not None else (query,)
        started = time.perf_counter()
        result = self._query_session().execute(self._text_sql(tenant, k), args).fetchall()
        elapsed = time.perf_counter() - started
        return [int(row[0]) for row in result], elapsed

    def text_explain(self, query: str, tenant: str | None, k: int) -> str:
        """Capture JSON EXPLAIN for the exact filtered text query."""
        args = (query, tenant) if tenant is not None else (query,)
        row = self._query_session().execute(self._text_sql(tenant, k, explain=True), args).fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL text EXPLAIN returned no row")
        return json.dumps(row[0], sort_keys=True)

    def plan_uses_text_index(self, plan: str) -> bool:
        """Require the named GIN index and its bitmap index scan."""
        lowered = plan.lower()
        return "item_search_document_gin_idx" in lowered and "bitmap index scan" in lowered

    def _hybrid_sql(self, tenant: str | None, k: int, candidates: int, rrf_k: int,
                    explain: bool = False) -> str:
        prefix = "EXPLAIN (FORMAT JSON) " if explain else ""
        vector_tenant = "WHERE tenant = %s " if tenant is not None else ""
        text_tenant = "AND tenant = %s " if tenant is not None else ""
        return f"""{prefix}
            WITH vector_candidates AS MATERIALIZED (
                SELECT source_id,
                       row_number() OVER (ORDER BY embedding <=> %s::vector) AS rank
                FROM item {vector_tenant}
                ORDER BY embedding <=> %s::vector LIMIT {int(candidates)}
            ), text_candidates AS MATERIALIZED (
                SELECT source_id,
                       row_number() OVER (
                           ORDER BY ts_rank_cd(search_document,
                               plainto_tsquery('english', %s)) DESC
                       ) AS rank
                FROM item
                WHERE search_document @@ plainto_tsquery('english', %s) {text_tenant}
                ORDER BY ts_rank_cd(search_document,
                    plainto_tsquery('english', %s)) DESC
                LIMIT {int(candidates)}
            ), ranked AS (
                SELECT source_id, rank FROM vector_candidates
                UNION ALL
                SELECT source_id, rank FROM text_candidates
            )
            SELECT source_id
            FROM ranked
            GROUP BY source_id
            ORDER BY sum(1.0 / ({int(rrf_k)} + rank)) DESC, source_id
            LIMIT {int(k)}
        """

    def _hybrid_args(self, vector: NDArray[np.float32], query: str,
                     tenant: str | None) -> tuple[object, ...]:
        args: list[object] = [_vector(vector)]
        if tenant is not None:
            args.append(tenant)
        args.append(_vector(vector))
        args.extend((query, query))
        if tenant is not None:
            args.append(tenant)
        args.append(query)
        return tuple(args)

    def hybrid_query(self, vector: NDArray[np.float32], query: str, tenant: str | None,
                     k: int, ef: int, candidates: int, rrf_k: int) -> tuple[list[int], float]:
        """Fuse tenant-filtered top-N vector and lexical CTEs with RRF in one SQL statement."""
        connection = self._query_session()
        connection.execute(f"SET hnsw.ef_search = {int(ef)}")
        connection.execute("SET hnsw.iterative_scan = off")
        started = time.perf_counter()
        result = connection.execute(
            self._hybrid_sql(tenant, k, candidates, rrf_k),
            self._hybrid_args(vector, query, tenant),
        ).fetchall()
        elapsed = time.perf_counter() - started
        return [int(row[0]) for row in result], elapsed

    def hybrid_explain(self, vector: NDArray[np.float32], query: str, tenant: str | None,
                       k: int, ef: int, candidates: int, rrf_k: int) -> str:
        """Capture one JSON plan containing both materialized retrieval CTEs."""
        connection = self._query_session()
        connection.execute(f"SET hnsw.ef_search = {int(ef)}")
        connection.execute("SET hnsw.iterative_scan = off")
        row = connection.execute(
            self._hybrid_sql(tenant, k, candidates, rrf_k, explain=True),
            self._hybrid_args(vector, query, tenant),
        ).fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL hybrid EXPLAIN returned no row")
        return json.dumps(row[0], sort_keys=True)

    def version(self) -> dict[str, str]:
        """Return PostgreSQL server and pgvector extension versions."""
        with psycopg.connect(self.dsn) as connection:
            server_row = connection.execute("SHOW server_version").fetchone()
            extension_row = connection.execute(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).fetchone()
        if server_row is None or extension_row is None:
            raise RuntimeError("PostgreSQL version query returned no row")
        server = server_row[0]
        extension = extension_row[0]
        return {"postgresql": str(server), "pgvector": str(extension)}

    def process_roots(self) -> list[int]:
        """Resolve the postmaster host PID."""
        if self.settings.mode == "docker":
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", self.container],
                                    text=True, capture_output=True)
            return [int(result.stdout.strip())] if result.returncode == 0 and result.stdout.strip() != "0" else []
        return [self.process.pid] if self.process and self.process.poll() is None else []

    def disk_bytes(self) -> int:
        """Return PostgreSQL cluster directory bytes."""
        if self.settings.mode == "docker" and self.process_roots():
            result = subprocess.run([
                "docker", "exec", self.container, "du", "-sb", "/var/lib/postgresql/data"
            ], text=True, capture_output=True)
            if result.returncode == 0:
                return int(result.stdout.split()[0])
        return directory_size(self.pgdata)

    def churn_once(self, operation: str, source_id: int, tenant: str,
                   vector: NDArray[np.float32]) -> None:
        """Apply one insert/upsert or delete transaction."""
        with psycopg.connect(self.dsn, autocommit=True) as connection:
            if operation == "delete":
                connection.execute("DELETE FROM item WHERE source_id = %s", (source_id,))
            elif self.text.enabled:
                connection.execute("""
                    INSERT INTO item(source_id, tenant, embedding, content)
                    VALUES (%s, %s, %s::vector, '')
                    ON CONFLICT (source_id) DO UPDATE
                    SET tenant=excluded.tenant, embedding=excluded.embedding
                """, (source_id, tenant, _vector(vector)))
            else:
                connection.execute("""
                    INSERT INTO item(source_id, tenant, embedding) VALUES (%s, %s, %s::vector)
                    ON CONFLICT (source_id) DO UPDATE SET tenant=excluded.tenant, embedding=excluded.embedding
                """, (source_id, tenant, _vector(vector)))

    def cleanup(self) -> None:
        """Remove the disposable container definition."""
        if self.settings.mode == "docker":
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
