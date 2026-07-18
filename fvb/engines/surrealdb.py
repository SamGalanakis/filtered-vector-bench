"""SurrealDB HNSW adapter using HTTP JSON-RPC."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import socket
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

import httpx
import numpy as np
from numpy.typing import NDArray

from fvb.config import EngineConfig
from fvb.engines.base import Engine, PhaseStats, Row, directory_size


_ARCHIVE_SHA256 = {
    "v3.2.1": "7036eafd9ba07c3720d25a3201f780b81ec82eb2b4dcb56c9ea81b87655644e7",
}
MAX_LOAD_PAYLOAD_BYTES = 4 * 1024 * 1024
LOAD_WORKERS = 4


def _insert_bodies(rows: Sequence[Row], max_rows: int) -> Iterable[tuple[bytes, int]]:
    """Yield compact SurrealQL INSERT bodies bounded by rows and encoded payload bytes."""
    prefix = b"INSERT INTO item ["
    suffix = b"] RETURN NONE;"
    encoded_rows: list[bytes] = []
    encoded_bytes = 0
    for row_id, tenant, vector in rows:
        encoded = json.dumps({
            "source_id": row_id,
            "tenant": tenant,
            "embedding": np.asarray(vector, dtype=np.float32).tolist(),
        }, separators=(",", ":")).encode()
        separator_bytes = len(encoded_rows)
        candidate_bytes = len(prefix) + encoded_bytes + separator_bytes + len(encoded) + len(suffix)
        if encoded_rows and (len(encoded_rows) >= max_rows or
                             candidate_bytes >= MAX_LOAD_PAYLOAD_BYTES):
            yield prefix + b",".join(encoded_rows) + suffix, len(encoded_rows)
            encoded_rows = []
            encoded_bytes = 0
        if len(prefix) + len(encoded) + len(suffix) >= MAX_LOAD_PAYLOAD_BYTES:
            raise ValueError("one SurrealDB load row exceeds the request payload bound")
        encoded_rows.append(encoded)
        encoded_bytes += len(encoded)
    if encoded_rows:
        yield prefix + b",".join(encoded_rows) + suffix, len(encoded_rows)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class SurrealDBEngine(Engine):
    """One isolated SurrealDB RocksDB cell."""

    name = "surrealdb"

    def __init__(self, workdir: Path, dimensions: int, timeout: int, memory_cap_bytes: int,
                 settings: EngineConfig, cache_dir: Path) -> None:
        super().__init__(workdir, dimensions, timeout, memory_cap_bytes)
        self.settings = settings
        self.cache_dir = cache_dir
        self.port = _free_port()
        self.container = f"fvb-surreal-{self.port}"
        self.process: subprocess.Popen[bytes] | None = None
        self._binary: Path | None = None
        self._client = httpx.Client(timeout=timeout, auth=("root", "root"), headers={
            "surreal-ns": "fvb", "surreal-db": "bench", "content-type": "application/json",
        })

    def _rpc(self, sql: str, variables: dict[str, object] | None = None) -> list[dict[str, object]]:
        response = self._client.post(f"http://127.0.0.1:{self.port}/rpc", json={
            "id": 1, "method": "query", "params": [sql, variables or {}],
        })
        response.raise_for_status()
        payload = cast(dict[str, Any], response.json())
        if "error" in payload:
            raise RuntimeError(f"SurrealDB RPC error: {payload['error']}")
        statements = cast(list[dict[str, object]], payload["result"])
        for statement in statements:
            if statement.get("status") != "OK":
                raise RuntimeError(f"SurrealDB statement failed: {statement}")
        return statements

    def _sql(self, body: bytes) -> None:
        """Execute one payload-bounded plain-text SurrealQL request."""
        response = self._client.post(
            f"http://127.0.0.1:{self.port}/sql", content=body,
            headers={"content-type": "text/plain", "accept": "application/json"},
        )
        response.raise_for_status()
        statements = cast(list[dict[str, object]], response.json())
        for statement in statements:
            if statement.get("status") != "OK":
                raise RuntimeError(f"SurrealDB statement failed: {statement}")

    def _ensure_namespace(self) -> None:
        response = httpx.post(f"http://127.0.0.1:{self.port}/rpc", timeout=self.timeout,
                              auth=("root", "root"), headers={"content-type": "application/json"},
                              json={"id": 1, "method": "query", "params": [
                                  "DEFINE NAMESPACE IF NOT EXISTS fvb; USE NS fvb; DEFINE DATABASE IF NOT EXISTS bench;",
                                  {},
                              ]})
        response.raise_for_status()
        payload = response.json()
        if "error" in payload or any(row.get("status") != "OK" for row in payload.get("result", [])):
            raise RuntimeError(f"failed to initialize SurrealDB namespace: {payload}")

    def _download_binary(self) -> Path:
        if self.settings.binary:
            binary = Path(self.settings.binary).expanduser().resolve()
            if not binary.is_file():
                raise FileNotFoundError(binary)
            return binary
        version = self.settings.version or "v3.2.1"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        binary = self.cache_dir / f"surreal-{version}"
        if binary.exists():
            return binary
        archive_name = f"surreal-{version}.linux-amd64.tgz"
        base = f"https://download.surrealdb.com/{version}"
        archive = self.cache_dir / archive_name
        checksum_file = self.cache_dir / f"{archive_name}.sha256"
        urllib.request.urlretrieve(f"{base}/{archive_name}", archive)
        expected = _ARCHIVE_SHA256.get(version, "")
        actual = hashlib.sha256(archive.read_bytes()).hexdigest()
        if not expected or expected.lower() != actual:
            archive.unlink(missing_ok=True)
            raise RuntimeError(f"unable to verify pinned SHA-256 for {archive_name}")
        checksum_file.write_text(f"{actual}  {archive_name}\n", encoding="utf-8")
        with tarfile.open(archive, "r:gz") as tar:
            member = next(item for item in tar.getmembers() if Path(item.name).name == "surreal")
            source = tar.extractfile(member)
            if source is None:
                raise RuntimeError("SurrealDB archive did not contain the binary")
            binary.write_bytes(source.read())
        binary.chmod(0o755)
        return binary

    def prepare(self) -> None:
        """Create an empty container or resolve the verified local binary."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(exist_ok=True)
        if self.settings.mode == "docker":
            (self.workdir / "data").chmod(0o777)
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
            subprocess.run([
                "docker", "create", "--name", self.container,
                "--memory", str(self.memory_cap_bytes), "-p", f"127.0.0.1:{self.port}:8000",
                "-e", "SURREAL_HTTP_MAX_SQL_BODY_SIZE=64MiB",
                "-e", "SURREAL_HTTP_MAX_RPC_BODY_SIZE=64MiB",
                "-v", f"{(self.workdir / 'data').resolve()}:/data",
                self.settings.image or "surrealdb/surrealdb:v3.2.1", "start", "--log", "warn",
                "--user", "root", "--pass", "root", "rocksdb:/data/fvb.db",
            ], check=True, capture_output=True)
        else:
            self._binary = self._download_binary()

    def start(self) -> float:
        """Start SurrealDB and wait for its health endpoint."""
        started = time.perf_counter()
        if self.settings.mode == "docker":
            subprocess.run(["docker", "start", self.container], check=True, capture_output=True)
        else:
            assert self._binary is not None
            command, preexec = self.limited_command([
                str(self._binary), "start", "--bind", f"127.0.0.1:{self.port}", "--log", "warn",
                "--user", "root", "--pass", "root", f"rocksdb:{self.workdir / 'data' / 'fvb.db'}",
            ])
            log = (self.workdir / "surreal.log").open("ab")
            env = dict(os.environ,
                       SURREAL_HTTP_MAX_SQL_BODY_SIZE="64MiB",
                       SURREAL_HTTP_MAX_RPC_BODY_SIZE="64MiB")
            self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                            env=env, preexec_fn=preexec)  # type: ignore[arg-type]
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                if self._client.get(f"http://127.0.0.1:{self.port}/health").is_success:
                    return time.perf_counter() - started
            except httpx.HTTPError:
                pass
            if self.settings.mode == "docker":
                status = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", self.container],
                    text=True, capture_output=True,
                ).stdout.strip()
                if status.startswith("false"):
                    logs = subprocess.run(["docker", "logs", self.container], text=True,
                                          capture_output=True).stderr[-2000:]
                    raise RuntimeError(f"SurrealDB container exited ({status}): {logs}")
            if self.settings.mode != "docker" and self.process and self.process.poll() is not None:
                raise RuntimeError(f"SurrealDB exited with {self.process.returncode}")
            time.sleep(0.2)
        raise TimeoutError("SurrealDB did not become ready")

    def stop(self) -> None:
        """Stop the current service while retaining durable storage."""
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
        """Maintain HNSW during bounded, four-worker plain-SQL inserts."""
        self._ensure_namespace()
        schema = f"""
            DEFINE TABLE item SCHEMAFULL;
            DEFINE FIELD source_id ON item TYPE int;
            DEFINE FIELD tenant ON item TYPE string;
            DEFINE FIELD embedding ON item TYPE array<float, {self.dimensions}>;
            DEFINE INDEX item_tenant_idx ON item FIELDS tenant;
            DEFINE INDEX item_embedding_hnsw_idx ON item FIELDS embedding
                HNSW DIMENSION {self.dimensions} TYPE F32 DIST COSINE;
        """
        self._rpc(schema)
        started = time.perf_counter()
        count = 0
        max_body_bytes = 0
        max_body_rows = 0
        pending: dict[concurrent.futures.Future[None], int] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=LOAD_WORKERS) as pool:
            for batch in rows:
                for body, body_rows in _insert_bodies(batch, max_rows=len(batch)):
                    max_body_bytes = max(max_body_bytes, len(body))
                    max_body_rows = max(max_body_rows, body_rows)
                    pending[pool.submit(self._sql, body)] = body_rows
                    if len(pending) >= LOAD_WORKERS * 2:
                        finished, _ = concurrent.futures.wait(
                            pending, return_when=concurrent.futures.FIRST_COMPLETED,
                        )
                        for future in finished:
                            count += pending.pop(future)
                            future.result()
            for future in concurrent.futures.as_completed(pending):
                count += pending[future]
                future.result()
        elapsed = time.perf_counter() - started
        return PhaseStats(elapsed, count, self.disk_bytes(), {
            "index_maintained_during_load": True,
            "endpoint": "/sql",
            "load_workers": LOAD_WORKERS,
            "max_request_rows": max_body_rows,
            "max_request_bytes": max_body_bytes,
            "request_payload_limit_bytes": MAX_LOAD_PAYLOAD_BYTES,
            "hnsw_parameters": {
                "m": 12, "ef_construction": 150, "m0": 24,
                "lm": "automatically derived", "source": "SurrealDB defaults",
            },
        })

    def build_index(self) -> PhaseStats:
        """Return the documented no-op because HNSW was maintained during load."""
        return PhaseStats(0.0, details={"no_op": "index defined before load"})

    def _select(self, tenant: str | None, k: int, ef: int) -> str:
        predicate = f"embedding <|{k},{ef}|> $vec"
        if tenant is not None:
            predicate += " AND tenant = $tenant"
        return f"SELECT source_id FROM item WHERE {predicate};"

    def query(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
              mode: str = "default") -> tuple[list[int], float]:
        """Execute SurrealQL's documented HNSW KNN predicate."""
        started = time.perf_counter()
        statements = self._rpc(self._select(tenant, k, ef), {
            "vec": np.asarray(vector, dtype=np.float32).tolist(), "tenant": tenant,
        })
        elapsed = time.perf_counter() - started
        result = cast(list[dict[str, object]], statements[0].get("result", []))
        return [int(cast(int, row["source_id"])) for row in result], elapsed

    def explain(self, vector: NDArray[np.float32], tenant: str | None, k: int, ef: int,
                mode: str = "default") -> str:
        """Capture JSON plan output for the exact query."""
        statements = self._rpc("EXPLAIN " + self._select(tenant, k, ef), {
            "vec": np.asarray(vector, dtype=np.float32).tolist(), "tenant": tenant,
        })
        return json.dumps(statements[0].get("result"), sort_keys=True)

    def plan_uses_index(self, plan: str) -> bool:
        """Require the named HNSW index to appear in the plan."""
        lowered = plan.lower()
        return "item_embedding_hnsw_idx" in lowered and "index" in lowered

    def version(self) -> dict[str, str]:
        """Read the server version through its unauthenticated version endpoint."""
        response = self._client.get(f"http://127.0.0.1:{self.port}/version")
        response.raise_for_status()
        return {"surrealdb": response.text.strip().strip('"'), "storage": "RocksDB"}

    def process_roots(self) -> list[int]:
        """Resolve the host process for local or Docker mode."""
        if self.settings.mode == "docker":
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", self.container],
                                    text=True, capture_output=True)
            return [int(result.stdout.strip())] if result.returncode == 0 and result.stdout.strip() != "0" else []
        return [self.process.pid] if self.process and self.process.poll() is None else []

    def disk_bytes(self) -> int:
        """Return RocksDB directory bytes."""
        if self.settings.mode == "docker" and self.process_roots():
            result = subprocess.run(["docker", "exec", self.container, "du", "-sb", "/data"],
                                    text=True, capture_output=True)
            if result.returncode == 0:
                return int(result.stdout.split()[0])
        return directory_size(self.workdir / "data")

    def churn_once(self, operation: str, source_id: int, tenant: str,
                   vector: NDArray[np.float32]) -> None:
        """Insert/upsert or delete one record."""
        if operation == "delete":
            self._rpc("DELETE type::record('item', $id);", {"id": source_id})
        else:
            self._rpc("UPSERT type::record('item', $id) CONTENT {source_id: $id, tenant: $tenant, embedding: $vec};",
                      {"id": source_id, "tenant": tenant,
                       "vec": np.asarray(vector, dtype=np.float32).tolist()})

    def cleanup(self) -> None:
        """Remove the disposable container definition."""
        if self.settings.mode == "docker":
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
