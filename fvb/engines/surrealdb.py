"""SurrealDB HNSW adapter with selectable storage and RPC transport."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import tarfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

import httpx
import numpy as np
from numpy.typing import NDArray
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Subprotocol

from fvb.config import EngineConfig, TextConfig
from fvb.engines.base import Engine, PhaseStats, Row, directory_size, row_parts


_ARCHIVE_SHA256 = {
    "v3.2.1": "7036eafd9ba07c3720d25a3201f780b81ec82eb2b4dcb56c9ea81b87655644e7",
}
MAX_LOAD_PAYLOAD_BYTES = 4 * 1024 * 1024
LOAD_WORKERS = 4
PD_IMAGE = "pingcap/pd:v8.5.3"
TIKV_IMAGE = "pingcap/tikv:v8.5.3"
SURREAL_IMAGE = "surrealdb/surrealdb:v3.2.1"
TIKV_GRPC_MESSAGE_BYTES = 64 * 1024 * 1024
TIUP_PLAYGROUND_VERSION = "v1.16.5"
TIDB_COMPONENT_VERSION = "v8.5.3"


def _insert_bodies(rows: Sequence[Row], max_rows: int) -> Iterable[tuple[bytes, int]]:
    """Yield compact SurrealQL INSERT bodies bounded by rows and encoded payload bytes."""
    prefix = b"INSERT INTO item ["
    suffix = b"] RETURN NONE;"
    encoded_rows: list[bytes] = []
    encoded_bytes = 0
    for row in rows:
        row_id, tenant, vector, content = row_parts(row)
        document: dict[str, object] = {
            "source_id": row_id,
            "tenant": tenant,
            "embedding": np.asarray(vector, dtype=np.float32).tolist(),
        }
        if content is not None:
            document["content"] = content
        encoded = json.dumps(document, separators=(",", ":")).encode()
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
    """One isolated SurrealDB cell with embedded RocksDB or external TiKV."""

    name = "surrealdb"

    def __init__(self, workdir: Path, dimensions: int, timeout: int, memory_cap_bytes: int,
                 settings: EngineConfig, cache_dir: Path, text: TextConfig) -> None:
        super().__init__(workdir, dimensions, timeout, memory_cap_bytes)
        self.settings = settings
        self.text = text
        self.text_score_zero_detected = False
        self.cache_dir = cache_dir
        self.port = _free_port()
        self.pd_port = _free_port()
        self.tikv_port = _free_port()
        self.container = f"fvb-surreal-{self.port}"
        self.pd_container = f"fvb-pd-{self.port}"
        self.tikv_container = f"fvb-tikv-{self.port}"
        self.network = f"fvb-tikv-{self.port}"
        self._tiup_tag = f"fvb-{self.port}"
        cached_tiup = cache_dir / "tiup-home" / "bin" / "tiup"
        tiup = shutil.which("tiup") or (str(cached_tiup) if cached_tiup.is_file() else None)
        self._tiup_binary = Path(tiup).resolve() if (
            tiup and settings.storage == "tikv" and settings.mode == "binary"
        ) else None
        self.tikv_setup = "tiup" if self._tiup_binary else "docker"
        self.surreal_in_docker = settings.mode == "docker" or (
            settings.storage == "tikv" and self.tikv_setup == "docker"
        )
        self.process: subprocess.Popen[bytes] | None = None
        self.tiup_process: subprocess.Popen[bytes] | None = None
        self._binary: Path | None = None
        self._ws_connections: dict[int, tuple[ClientConnection, bool]] = {}
        self._ws_lock = threading.Lock()
        self._client = httpx.Client(timeout=timeout, auth=("root", "root"), headers={
            "surreal-ns": "fvb", "surreal-db": "bench", "content-type": "application/json",
        })

    @staticmethod
    def _checked_rpc_payload(payload: dict[str, Any]) -> object:
        if "error" in payload:
            raise RuntimeError(f"SurrealDB RPC error: {payload['error']}")
        return payload.get("result")

    def _ws_call(self, connection: ClientConnection, method: str,
                 params: list[object]) -> object:
        connection.send(json.dumps({"id": 1, "method": method, "params": params}))
        raw = connection.recv(timeout=self.timeout)
        payload = cast(dict[str, Any], json.loads(raw))
        return self._checked_rpc_payload(payload)

    def _ws_connection(self, *, scoped: bool = True) -> ClientConnection:
        thread_id = threading.get_ident()
        with self._ws_lock:
            cached = self._ws_connections.get(thread_id)
            if cached is None:
                connection = connect(
                    f"ws://127.0.0.1:{self.port}/rpc", subprotocols=[Subprotocol("json")],
                    open_timeout=self.timeout, close_timeout=5, max_size=None,
                )
                self._ws_call(connection, "signin", [{
                    "user": "root", "pass": "root",
                }])
                cached = (connection, False)
                self._ws_connections[thread_id] = cached
            connection, is_scoped = cached
            if scoped and not is_scoped:
                self._ws_call(connection, "use", ["fvb", "bench"])
                self._ws_connections[thread_id] = (connection, True)
            return connection

    def _close_ws_connections(self) -> None:
        with self._ws_lock:
            connections = list(self._ws_connections.values())
            self._ws_connections.clear()
        for connection, _ in connections:
            try:
                connection.close()
            except OSError:
                pass

    def _rpc(self, sql: str, variables: dict[str, object] | None = None) -> list[dict[str, object]]:
        if self.settings.transport == "ws":
            payload = self._ws_call(
                self._ws_connection(), "query", [sql, variables or {}]
            )
            statements = cast(list[dict[str, object]], payload)
            for statement in statements:
                if statement.get("status") != "OK":
                    raise RuntimeError(f"SurrealDB statement failed: {statement}")
            return statements
        response = self._client.post(f"http://127.0.0.1:{self.port}/rpc", json={
            "id": 1, "method": "query", "params": [sql, variables or {}],
        })
        response.raise_for_status()
        payload = cast(dict[str, Any], response.json())
        statements = cast(list[dict[str, object]], self._checked_rpc_payload(payload))
        for statement in statements:
            if statement.get("status") != "OK":
                raise RuntimeError(f"SurrealDB statement failed: {statement}")
        return statements

    def _sql(self, body: bytes) -> None:
        """Execute one payload-bounded plain-text SurrealQL request."""
        if self.settings.transport == "ws":
            self._rpc(body.decode("utf-8"))
            return
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
        if self.settings.transport == "ws":
            connection = self._ws_connection(scoped=False)
            statements = cast(list[dict[str, object]], self._ws_call(
                connection, "query", [
                    "DEFINE NAMESPACE IF NOT EXISTS fvb; USE NS fvb; "
                    "DEFINE DATABASE IF NOT EXISTS bench;", {},
                ],
            ))
            if any(row.get("status") != "OK" for row in statements):
                raise RuntimeError(f"failed to initialize SurrealDB namespace: {statements}")
            self._ws_call(connection, "use", ["fvb", "bench"])
            with self._ws_lock:
                self._ws_connections[threading.get_ident()] = (connection, True)
            return
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

    def _remove_docker_resources(self) -> None:
        for container in (self.container, self.tikv_container, self.pd_container):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)
        subprocess.run(["docker", "network", "rm", self.network], capture_output=True)

    def _create_tikv_cluster(self) -> None:
        pd_data = self.workdir / "pd-data"
        tikv_data = self.workdir / "tikv-data"
        for path in (pd_data, tikv_data):
            path.mkdir(exist_ok=True)
            path.chmod(0o777)
        tikv_config = self.workdir / "tikv.toml"
        tikv_config.write_text(
            f"[server]\nmax-grpc-send-msg-len = {TIKV_GRPC_MESSAGE_BYTES}\n",
            encoding="utf-8",
        )
        subprocess.run(["docker", "network", "create", self.network], check=True,
                       capture_output=True)
        subprocess.run([
            "docker", "create", "--name", self.pd_container, "--network", self.network,
            "--network-alias", "pd", "-p", f"127.0.0.1:{self.pd_port}:2379",
            "-v", f"{pd_data.resolve()}:/data", PD_IMAGE,
            "--name=pd", "--data-dir=/data", "--client-urls=http://0.0.0.0:2379",
            "--advertise-client-urls=http://pd:2379", "--peer-urls=http://0.0.0.0:2380",
            "--advertise-peer-urls=http://pd:2380", "--initial-cluster=pd=http://pd:2380",
        ], check=True, capture_output=True)
        subprocess.run([
            "docker", "create", "--name", self.tikv_container, "--network", self.network,
            "--network-alias", "tikv", "-v", f"{tikv_data.resolve()}:/data",
            "-v", f"{tikv_config.resolve()}:/etc/tikv/tikv.toml:ro", TIKV_IMAGE,
            "--addr=0.0.0.0:20160", "--advertise-addr=tikv:20160", "--data-dir=/data",
            "--pd=pd:2379", "--config=/etc/tikv/tikv.toml",
        ], check=True, capture_output=True)

    def _create_tiup_cluster(self) -> None:
        """Launch a pinned single-PD/single-TiKV playground with cell-local data."""
        assert self._tiup_binary is not None
        tiup_home = self.cache_dir / "tiup-home"
        tag = self._tiup_tag
        data_target = self.workdir / "tiup-data"
        data_target.mkdir(exist_ok=True)
        data_link = tiup_home / "data" / tag
        data_link.parent.mkdir(parents=True, exist_ok=True)
        if data_link.is_symlink():
            data_link.unlink()
        elif data_link.exists():
            raise RuntimeError(f"refusing to replace existing TiUP data path: {data_link}")
        data_link.symlink_to(data_target.resolve(), target_is_directory=True)
        tikv_config = self.workdir / "tikv.toml"
        tikv_config.write_text(
            f"[server]\nmax-grpc-send-msg-len = {TIKV_GRPC_MESSAGE_BYTES}\n",
            encoding="utf-8",
        )
        env = dict(os.environ, TIUP_HOME=str(tiup_home.resolve()))
        subprocess.run([
            str(self._tiup_binary), "install", f"playground:{TIUP_PLAYGROUND_VERSION}",
            f"pd:{TIDB_COMPONENT_VERSION}", f"tikv:{TIDB_COMPONENT_VERSION}",
        ], check=True, capture_output=True, env=env)
        log = (self.workdir / "tiup-playground.log").open("ab")
        command = [
            str(self._tiup_binary), f"playground:{TIUP_PLAYGROUND_VERSION}",
            TIDB_COMPONENT_VERSION, "--mode", "tikv-slim", "--without-monitor",
            "--host", "127.0.0.1", "--pd", "1", "--kv", "1",
            "--pd.port", str(self.pd_port), "--kv.port", str(self.tikv_port),
            "--kv.config", str(tikv_config.resolve()), "--tag", tag,
        ]
        self.tiup_process = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, env=env,
            start_new_session=True,
        )
        log.close()

    def _create_surreal_container(self) -> None:
        data = self.workdir / "data"
        command = [
            "docker", "create", "--name", self.container, "--memory",
            str(self.memory_cap_bytes), "-p", f"127.0.0.1:{self.port}:8000",
            "-e", "SURREAL_HTTP_MAX_SQL_BODY_SIZE=64MiB",
            "-e", "SURREAL_HTTP_MAX_RPC_BODY_SIZE=64MiB",
        ]
        if self.settings.storage == "tikv":
            command += [
                "--network", self.network,
                "-e", f"SURREAL_TIKV_GRPC_MAX_DECODING_MESSAGE_SIZE={TIKV_GRPC_MESSAGE_BYTES}",
                "-e", f"SURREAL_TIKV_GRPC_MAX_ENCODING_MESSAGE_SIZE={TIKV_GRPC_MESSAGE_BYTES}",
            ]
            datastore = "tikv://pd:2379"
        else:
            command += ["-v", f"{data.resolve()}:/data"]
            datastore = "rocksdb:/data/fvb.db"
        command += [
            self.settings.image or SURREAL_IMAGE, "start", "--log", "warn",
            "--user", "root", "--pass", "root", datastore,
        ]
        subprocess.run(command, check=True, capture_output=True)

    def prepare(self) -> None:
        """Create isolated storage resources and resolve the SurrealDB executable."""
        self.workdir.mkdir(parents=True, exist_ok=True)
        (self.workdir / "data").mkdir(exist_ok=True)
        if self.settings.storage == "tikv" and self.tikv_setup == "tiup":
            self._binary = self._download_binary()
            self._create_tiup_cluster()
        elif self.surreal_in_docker:
            (self.workdir / "data").chmod(0o777)
            self._remove_docker_resources()
            if self.settings.storage == "tikv":
                self._create_tikv_cluster()
            self._create_surreal_container()
        else:
            self._binary = self._download_binary()

    def _docker_running(self, container: str) -> bool:
        result = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            text=True, capture_output=True,
        )
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _wait_for_docker_tikv(self) -> None:
        if not self._docker_running(self.pd_container):
            subprocess.run(["docker", "start", self.pd_container], check=True,
                           capture_output=True)
        deadline = time.monotonic() + self.timeout
        pd_url = f"http://127.0.0.1:{self.pd_port}"
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{pd_url}/pd/api/v1/health", timeout=2).is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            raise TimeoutError("PD did not become ready")
        if not self._docker_running(self.tikv_container):
            subprocess.run(["docker", "start", self.tikv_container], check=True,
                           capture_output=True)
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{pd_url}/pd/api/v1/stores", timeout=2)
                stores = response.json().get("stores", []) if response.is_success else []
                if any(store.get("store", {}).get("state_name") == "Up" for store in stores):
                    return
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            if not self._docker_running(self.tikv_container):
                logs = subprocess.run(
                    ["docker", "logs", self.tikv_container], text=True, capture_output=True,
                ).stderr[-4000:]
                raise RuntimeError(f"TiKV container exited: {logs}")
            time.sleep(0.5)
        raise TimeoutError("TiKV did not register as Up with PD")

    def _wait_for_tiup_tikv(self) -> None:
        """Wait until TiUP's pinned PD reports its one TiKV store as Up."""
        assert self.tiup_process is not None
        deadline = time.monotonic() + self.timeout
        pd_url = f"http://127.0.0.1:{self.pd_port}"
        while time.monotonic() < deadline:
            if self.tiup_process.poll() is not None:
                log = (self.workdir / "tiup-playground.log").read_text(
                    encoding="utf-8", errors="replace"
                )[-4000:]
                raise RuntimeError(f"TiUP playground exited: {log}")
            try:
                response = httpx.get(f"{pd_url}/pd/api/v1/stores", timeout=2)
                stores = response.json().get("stores", []) if response.is_success else []
                if any(store.get("store", {}).get("state_name") == "Up" for store in stores):
                    return
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
            time.sleep(0.5)
        raise TimeoutError("TiUP TiKV did not register as Up with PD")

    def start(self) -> float:
        """Start SurrealDB and wait for its health endpoint."""
        started = time.perf_counter()
        if self.settings.storage == "tikv":
            if self.tikv_setup == "tiup":
                self._wait_for_tiup_tikv()
            else:
                self._wait_for_docker_tikv()
        if self.surreal_in_docker:
            subprocess.run(["docker", "start", self.container], check=True, capture_output=True)
        else:
            assert self._binary is not None
            datastore = (
                f"tikv://127.0.0.1:{self.pd_port}" if self.settings.storage == "tikv"
                else f"rocksdb:{self.workdir / 'data' / 'fvb.db'}"
            )
            command, preexec = self.limited_command([
                str(self._binary), "start", "--bind", f"127.0.0.1:{self.port}", "--log", "warn",
                "--user", "root", "--pass", "root", datastore,
            ])
            log = (self.workdir / "surreal.log").open("ab")
            env = dict(os.environ,
                       SURREAL_HTTP_MAX_SQL_BODY_SIZE="64MiB",
                       SURREAL_HTTP_MAX_RPC_BODY_SIZE="64MiB")
            if self.settings.storage == "tikv":
                env.update(
                    SURREAL_TIKV_GRPC_MAX_DECODING_MESSAGE_SIZE=str(TIKV_GRPC_MESSAGE_BYTES),
                    SURREAL_TIKV_GRPC_MAX_ENCODING_MESSAGE_SIZE=str(TIKV_GRPC_MESSAGE_BYTES),
                )
            self.process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                            env=env, preexec_fn=preexec)  # type: ignore[arg-type]
            log.close()
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                if self._client.get(f"http://127.0.0.1:{self.port}/health").is_success:
                    return time.perf_counter() - started
            except httpx.HTTPError:
                pass
            if self.surreal_in_docker:
                status = subprocess.run(
                    ["docker", "inspect", "-f", "{{.State.Running}} {{.State.ExitCode}}", self.container],
                    text=True, capture_output=True,
                ).stdout.strip()
                if status.startswith("false"):
                    logs = subprocess.run(["docker", "logs", self.container], text=True,
                                          capture_output=True).stderr[-2000:]
                    raise RuntimeError(f"SurrealDB container exited ({status}): {logs}")
            if not self.surreal_in_docker and self.process and self.process.poll() is not None:
                raise RuntimeError(f"SurrealDB exited with {self.process.returncode}")
            time.sleep(0.2)
        raise TimeoutError("SurrealDB did not become ready")

    def stop(self) -> None:
        """Stop the current service while retaining durable storage."""
        self._close_ws_connections()
        if self.surreal_in_docker:
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
            {"DEFINE FIELD content ON item TYPE string;" if self.text.enabled else ""}
            DEFINE INDEX item_tenant_idx ON item FIELDS tenant;
            DEFINE INDEX item_embedding_hnsw_idx ON item FIELDS embedding
                HNSW DIMENSION {self.dimensions} TYPE F32 DIST COSINE;
            {"DEFINE ANALYZER fvb_ascii TOKENIZERS class FILTERS lowercase,ascii;" if self.text.enabled else ""}
            {"DEFINE INDEX item_content_fulltext_idx ON item FIELDS content FULLTEXT ANALYZER fvb_ascii BM25;" if self.text.enabled else ""}
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
            "text_index_maintained_during_load": self.text.enabled,
            "endpoint": "/rpc (WebSocket)" if self.settings.transport == "ws" else "/sql",
            "transport": self.settings.transport,
            "storage": self.settings.storage,
            "tikv_grpc_message_limit_bytes": (
                TIKV_GRPC_MESSAGE_BYTES if self.settings.storage == "tikv" else None
            ),
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

    def _text_select(self, tenant: str | None, k: int) -> str:
        tenant_clause = " AND tenant = $tenant" if tenant is not None else ""
        return (
            "SELECT source_id, search::score(0) AS score FROM item "
            f"WHERE content @0@ $text{tenant_clause} "
            f"ORDER BY score DESC LIMIT {int(k)};"
        )

    def text_query(self, query: str, tenant: str | None, k: int) -> tuple[list[int], float]:
        """Execute a BM25-ranked full-text predicate with the tenant filter in SurrealQL."""
        started = time.perf_counter()
        statements = self._rpc(self._text_select(tenant, k), {"text": query, "tenant": tenant})
        elapsed = time.perf_counter() - started
        result = cast(list[dict[str, object]], statements[0].get("result", []))
        if result and all(float(cast(float, row.get("score", 0.0))) == 0.0 for row in result):
            self.text_score_zero_detected = True
        return [int(cast(int, row["source_id"])) for row in result], elapsed

    def text_explain(self, query: str, tenant: str | None, k: int) -> str:
        """Capture JSON plan output for the exact full-text query."""
        statements = self._rpc(
            "EXPLAIN " + self._text_select(tenant, k), {"text": query, "tenant": tenant}
        )
        return json.dumps(statements[0].get("result"), sort_keys=True)

    def plan_uses_text_index(self, plan: str) -> bool:
        """Require the named FULLTEXT index in the plan."""
        lowered = plan.lower()
        return "item_content_fulltext_idx" in lowered and "index" in lowered

    def _hybrid_statement(self, tenant: str | None, k: int, ef: int, candidates: int,
                          rrf_k: int) -> str:
        tenant_clause = " AND tenant = $tenant" if tenant is not None else ""
        return f"""
            LET $text_candidates = SELECT id, source_id, search::score(0) AS text_score
                FROM item WHERE content @0@ $text{tenant_clause}
                ORDER BY text_score DESC LIMIT {int(candidates)};
            LET $vector_candidates = SELECT id, source_id,
                    vector::distance::knn() AS distance
                FROM item WHERE embedding <|{int(candidates)},{int(ef)}|> $vec{tenant_clause}
                ORDER BY distance ASC LIMIT {int(candidates)};
            RETURN search::rrf([$text_candidates, $vector_candidates], {int(k)}, {int(rrf_k)});
        """

    def hybrid_query(self, vector: NDArray[np.float32], query: str, tenant: str | None,
                     k: int, ef: int, candidates: int, rrf_k: int) -> tuple[list[int], float]:
        """Fuse BM25 and HNSW candidates with search::rrf in one RPC query request."""
        variables = {
            "vec": np.asarray(vector, dtype=np.float32).tolist(),
            "text": query,
            "tenant": tenant,
        }
        started = time.perf_counter()
        statements = self._rpc(
            self._hybrid_statement(tenant, k, ef, candidates, rrf_k), variables
        )
        elapsed = time.perf_counter() - started
        result = cast(list[dict[str, object]], statements[-1].get("result", []))
        if result and all(float(cast(float, row.get("text_score", 0.0))) == 0.0
                          for row in result if "text_score" in row):
            text_rows = [row for row in result if "text_score" in row]
            self.text_score_zero_detected = self.text_score_zero_detected or bool(text_rows)
        return [int(cast(int, row["source_id"])) for row in result], elapsed

    def hybrid_explain(self, vector: NDArray[np.float32], query: str, tenant: str | None,
                       k: int, ef: int, candidates: int, rrf_k: int) -> str:
        """Capture both exact retrieval-branch plans in one SurrealDB request."""
        tenant_clause = " AND tenant = $tenant" if tenant is not None else ""
        sql = f"""
            EXPLAIN SELECT source_id, search::score(0) AS text_score FROM item
                WHERE content @0@ $text{tenant_clause}
                ORDER BY text_score DESC LIMIT {int(candidates)};
            EXPLAIN SELECT source_id, vector::distance::knn() AS distance FROM item
                WHERE embedding <|{int(candidates)},{int(ef)}|> $vec{tenant_clause}
                ORDER BY distance ASC LIMIT {int(candidates)};
        """
        statements = self._rpc(sql, {
            "vec": np.asarray(vector, dtype=np.float32).tolist(),
            "text": query,
            "tenant": tenant,
        })
        return json.dumps([statement.get("result") for statement in statements], sort_keys=True)

    def version(self) -> dict[str, str]:
        """Read the server version through its unauthenticated version endpoint."""
        response = self._client.get(f"http://127.0.0.1:{self.port}/version")
        response.raise_for_status()
        versions = {
            "surrealdb": response.text.strip().strip('"'),
            "storage": "TiKV" if self.settings.storage == "tikv" else "RocksDB",
            "transport": self.settings.transport,
        }
        if self.settings.storage == "tikv":
            if self.tikv_setup == "tiup":
                assert self._tiup_binary is not None
                tiup_home = self.cache_dir / "tiup-home"
                env = dict(os.environ, TIUP_HOME=str(tiup_home.resolve()))
                for key in ("pd", "tikv"):
                    result = subprocess.run(
                        [str(self._tiup_binary), f"{key}:{TIDB_COMPONENT_VERSION}", "--version"],
                        text=True, capture_output=True, env=env,
                    )
                    output = (result.stdout or result.stderr).strip().replace("\n", "; ")
                    versions[key] = output or "version unavailable"
                tiup_version = subprocess.run(
                    [str(self._tiup_binary), "--version"], text=True, capture_output=True,
                    env=env,
                )
                versions["tiup"] = tiup_version.stdout.strip().replace("\n", "; ")
                versions["playground"] = TIUP_PLAYGROUND_VERSION
                versions["topology"] = "single PD + single TiKV; TiUP tikv-slim"
            else:
                for key, container, binary, image in (
                    ("pd", self.pd_container, "/pd-server", PD_IMAGE),
                    ("tikv", self.tikv_container, "/tikv-server", TIKV_IMAGE),
                ):
                    result = subprocess.run(
                        ["docker", "exec", container, binary, "--version"],
                        text=True, capture_output=True,
                    )
                    output = (result.stdout or result.stderr).strip().replace("\n", "; ")
                    versions[key] = f"{output or 'version unavailable'} (image {image})"
                versions["topology"] = "single PD + single TiKV; isolated Docker network"
            versions["setup"] = self.tikv_setup
            versions["tikv_grpc_message_limit_bytes"] = str(TIKV_GRPC_MESSAGE_BYTES)
        return versions

    def _tiup_component_roots(self) -> list[int]:
        """Resolve only the PD/TiKV roots below the TiUP supervisor."""
        if self.tiup_process is None or self.tiup_process.poll() is not None:
            return []
        descendants = {self.tiup_process.pid}
        changed = True
        while changed:
            changed = False
            for entry in Path("/proc").iterdir():
                if not entry.name.isdigit() or int(entry.name) in descendants:
                    continue
                try:
                    parent = int((entry / "stat").read_text().split()[3])
                except (OSError, IndexError, ValueError):
                    continue
                if parent in descendants:
                    descendants.add(int(entry.name))
                    changed = True
        roots = []
        for pid in descendants:
            try:
                executable = Path(f"/proc/{pid}/exe").resolve().name
            except OSError:
                continue
            if executable in {"pd-server", "tikv-server"}:
                roots.append(pid)
        return roots

    def process_roots(self) -> list[int]:
        """Resolve the host process for local or Docker mode."""
        if self.surreal_in_docker:
            result = subprocess.run(["docker", "inspect", "-f", "{{.State.Pid}}", self.container],
                                    text=True, capture_output=True)
            return [int(result.stdout.strip())] if result.returncode == 0 and result.stdout.strip() != "0" else []
        return [self.process.pid] if self.process and self.process.poll() is None else []

    def memory_process_groups(self) -> dict[str, list[int]]:
        """Attribute query-process memory separately from the external storage cluster."""
        groups = {"surrealdb": self.process_roots()}
        if self.settings.storage == "tikv":
            storage_roots = self._tiup_component_roots()
            if self.tikv_setup == "docker":
                storage_roots = []
                for container in (self.pd_container, self.tikv_container):
                    result = subprocess.run(
                        ["docker", "inspect", "-f", "{{.State.Pid}}", container],
                        text=True, capture_output=True,
                    )
                    if result.returncode == 0 and result.stdout.strip() not in {"", "0"}:
                        storage_roots.append(int(result.stdout.strip()))
            groups["tikv_pd"] = storage_roots
        return groups

    def disk_bytes(self) -> int:
        """Return RocksDB directory bytes."""
        if self.settings.storage == "tikv":
            if self.tikv_setup == "tiup":
                return directory_size(self.workdir / "tiup-data")
            return (directory_size(self.workdir / "pd-data") +
                    directory_size(self.workdir / "tikv-data"))
        if self.surreal_in_docker and self.process_roots():
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
            self._rpc(
                "UPSERT type::record('item', $id) MERGE {source_id: $id, tenant: $tenant, "
                "embedding: $vec};",
                {"id": source_id, "tenant": tenant,
                 "vec": np.asarray(vector, dtype=np.float32).tolist()},
            )

    def cleanup(self) -> None:
        """Stop the external storage cluster and remove disposable launch resources."""
        if self.tiup_process is not None and self.tiup_process.poll() is None:
            try:
                os.killpg(self.tiup_process.pid, signal.SIGTERM)
                self.tiup_process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.tiup_process.pid, signal.SIGKILL)
                self.tiup_process.wait(timeout=10)
        self.tiup_process = None
        if self._tiup_binary is not None:
            data_link = self.cache_dir / "tiup-home" / "data" / self._tiup_tag
            if data_link.is_symlink():
                data_link.unlink()
        if self.surreal_in_docker:
            self._remove_docker_resources()
