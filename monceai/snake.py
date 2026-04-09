"""
monceai.Snake — Cloud-backed Snake classifier.

Drop-in replacement for algorithmeai.Snake. Same interface, distributed backend.

    from monceai import Snake

    model = Snake(data, target_index="label", n_layers=15)
    model.get_prediction(X)
    model.get_probability(X)
    model.get_audit(X)

    # Pull locally — compatible with algorithmeai.Snake
    model.to_json("model.json")

    from algorithmeai import Snake as LocalSnake
    local = LocalSnake("model.json")  # works

API key from SNAKE_API_KEY env var.
"""

import json
import os
import requests


DEFAULT_ENDPOINT = "https://snakebatch.aws.monce.ai"

MODES = {
    "fast":     {"n_layers": 25,  "bucket": 16},
    "balanced": {"n_layers": 50,  "bucket": 32},
    "heavy":    {"n_layers": 100, "bucket": 64},
}


def _get_api_key():
    key = os.environ.get("SNAKE_API_KEY")
    if not key:
        return None
    return key


class Snake:
    """
    Cloud Snake classifier.

    Modes:
        Snake(data, target_index=...)       — train new model
        Snake(model_id="snake-abc-123")     — connect to existing model
        Snake("snake-abc-123")              — connect (shorthand)
        Snake("model.json")                 — load local file, upload to cloud
    """

    def __init__(self, Knowledge=None, target_index=0, n_layers=None, bucket=250,
                 noise=0.25, oppose_profile="auto", model_id=None,
                 endpoint=None, api_key=None, max_lambdas=None, timeout=120,
                 budget_ms=2100, mode="fast"):

        self.endpoint = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        self.api_key = api_key or _get_api_key()
        self.model_id = model_id
        self.timeout = timeout
        self.budget_ms = budget_ms
        self.training_info = None
        self._session = requests.Session()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._session.headers.update(headers)

        # Resolve n_layers and bucket: explicit > mode > default
        mode_cfg = MODES.get(mode, MODES["fast"])
        if n_layers is None:
            n_layers = mode_cfg["n_layers"]
        if bucket == 250:  # default sentinel — override with mode
            bucket = mode_cfg["bucket"]

        # Connect to existing model by model_id kwarg
        if Knowledge is None and model_id:
            self._verify_model()
            return

        # Shorthand: Snake("snake-abc-123")
        if isinstance(Knowledge, str) and not Knowledge.endswith((".json", ".csv")):
            self.model_id = Knowledge
            self._verify_model()
            return

        # Load local JSON — Snake model or raw training data
        if isinstance(Knowledge, str) and Knowledge.endswith(".json"):
            with open(Knowledge) as f:
                content = json.load(f)
            # Snake models have "layers" key; raw data is a list of dicts
            if isinstance(content, dict) and "layers" in content:
                self._upload_model(Knowledge)
            elif isinstance(content, list):
                self._train(content, target_index, n_layers, bucket, noise,
                            oppose_profile, max_lambdas)
            else:
                raise ValueError(f"JSON file is neither a Snake model nor a list of training data")
            return

        # Train from data
        if Knowledge is not None:
            self._train(Knowledge, target_index, n_layers, bucket, noise,
                        oppose_profile, max_lambdas)
            return

        raise ValueError("Provide training data, a model_id, or a JSON path")

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def _train(self, data, target_index, n_layers, bucket, noise,
               oppose_profile, max_lambdas):
        config = {
            "target_index": target_index,
            "n_layers": n_layers,
            "bucket": bucket,
            "noise": noise,
            "oppose_profile": oppose_profile,
        }
        if max_lambdas is not None:
            config["max_lambdas"] = max_lambdas

        payload = json.dumps(data, default=str).encode()
        size_mb = len(payload) / (1024 * 1024)

        FIXED_OVERHEAD_MS = 500
        server_budget = max(100, self.budget_ms - FIXED_OVERHEAD_MS) if self.budget_ms else None

        if size_mb > 4 or len(data) > 3000:
            # Large data: cache server-side first, then train by reference.
            # Split into chunks that fit under 4MB API Gateway limit.
            if size_mb > 4:
                chunk_size = max(1000, int(len(data) * 3.5 / size_mb))
            else:
                chunk_size = 3000
            all_items = []
            for i in range(0, len(data), chunk_size):
                chunk = data[i:i + chunk_size]
                cache = self._post("/cache-items", {"items": chunk})
                all_items.append(cache["cache_key"])
            body = {"cache_keys": all_items, "config": config}
        else:
            body = {"data": data, "config": config}

        if server_budget:
            body["budget_ms"] = server_budget

        resp = self._post("/train", body)

        self.model_id = resp["model_id"]

        # Async training: poll until ready
        if resp.get("async"):
            import sys
            sys.stdout.write(f"Training {resp.get('n_samples', '?')} samples async")
            sys.stdout.flush()
            while True:
                import time as _t
                _t.sleep(2)
                try:
                    info = self.info()
                    status = info.get("status", "unknown")
                    if status == "ready":
                        sys.stdout.write(" done\n")
                        sys.stdout.flush()
                        break
                    sys.stdout.write(".")
                    sys.stdout.flush()
                except Exception:
                    sys.stdout.write(".")
                    sys.stdout.flush()

        self.training_info = resp

    def _upload_model(self, path):
        """Upload a local Snake JSON to the cloud for inference."""
        with open(path) as f:
            model_json = json.load(f)
        resp = self._post("/model/upload", {"model": model_json})
        self.model_id = resp["model_id"]

    # ------------------------------------------------------------------
    # Training metadata
    # ------------------------------------------------------------------

    @property
    def wall_clock_ms(self):
        """Server-side training time in ms."""
        if self.training_info:
            return self.training_info.get("wall_clock_ms")
        return None

    @property
    def breakdown(self):
        """Training time breakdown: preprocess_ms, chain_build_ms, bucket_fan_out_ms, merge_s3_ms."""
        if self.training_info:
            return self.training_info.get("breakdown")
        return None

    @property
    def log(self):
        """Server-side training log."""
        if self.training_info:
            return self.training_info.get("log")
        return None

    # ------------------------------------------------------------------
    # Budget estimation
    # ------------------------------------------------------------------

    @staticmethod
    def estimate(n_samples, n_layers=5, bucket=250, noise=0.25, endpoint=None):
        """
        Estimate cost before training.

        Returns dict with estimated_total_lambdas, estimated_cost_usd,
        estimated_wall_clock_ms.
        """
        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        resp = requests.post(f"{ep}/estimate", json={
            "n_samples": n_samples,
            "config": {"n_layers": n_layers, "bucket": bucket, "noise": noise},
        })
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Prediction — same signatures as algorithmeai.Snake
    # ------------------------------------------------------------------

    def get_prediction(self, X):
        resp = self._post(f"/predict/{self.model_id}", {"X": X})
        return resp["prediction"]

    def get_probability(self, X):
        resp = self._post(f"/predict/{self.model_id}", {"X": X, "mode": "probability"})
        return resp["probability"]

    def get_audit(self, X):
        resp = self._post(f"/predict/{self.model_id}", {"X": X, "mode": "audit"})
        return resp["audit"]

    def get_augmented(self, X):
        resp = self._post(f"/predict/{self.model_id}", {"X": X, "mode": "augmented"})
        return resp["augmented"]

    def get_lookalikes(self, X):
        resp = self._post(f"/predict/{self.model_id}", {"X": X, "mode": "lookalikes"})
        return resp["lookalikes"]

    def get_lookalikes_labeled(self, X):
        resp = self._post(f"/predict/{self.model_id}", {"X": X, "mode": "lookalikes_labeled"})
        return resp["lookalikes_labeled"]

    # ------------------------------------------------------------------
    # Batch prediction
    # ------------------------------------------------------------------

    def get_batch_prediction(self, items, mode="prediction", budget_ms=None, items_key=None):
        """
        Predict on a list of dicts. Auto-scales: measures 1 item, chunks accordingly.

        First call: caches items (outside budget). Use items_key on repeat calls.

        Args:
            items: list of X dicts
            mode: "prediction", "probability"
            budget_ms: max wall-clock ms (default: no limit)
            items_key: S3 cache key from previous call (skip upload)

        Returns:
            list of results (same order as items), None for unscored
        """
        FIXED_OVERHEAD_MS = 500
        server_budget = max(100, budget_ms - FIXED_OVERHEAD_MS) if budget_ms else None
        body = {"mode": mode}

        if items_key:
            body["items_key"] = items_key
        elif items:
            payload_size = len(json.dumps(items, default=str).encode())
            if payload_size > 3 * 1024 * 1024:
                bytes_per_item = payload_size / len(items)
                chunk_n = max(100, int(2.5 * 1024 * 1024 / bytes_per_item))
                chunk_keys = []
                for i in range(0, len(items), chunk_n):
                    cache = self._post("/cache-items", {"items": items[i:i+chunk_n]})
                    chunk_keys.append(cache["cache_key"])
                body["cache_chunks"] = chunk_keys
            else:
                body["items"] = items

        if server_budget:
            body["budget_ms"] = server_budget

        resp = self._post(f"/batch/{self.model_id}", body)
        return resp

    def get_batch_rank(self, items, target_class, top=100, budget_ms=5000,
                       workers=None, items_key=None):
        """
        Rank test items by P(target_class). Returns top-K sorted descending.

        Distributed across N scorer Lambdas. Content-hash cached in S3 —
        repeated calls with same test data skip upload.

        First call without items_key: caches data + warms up workers.
        Subsequent calls with items_key: pure budgeted scoring.

        Args:
            items: list of dicts (test data, up to 100K+)
            target_class: class to rank by
            top: return top N results (default 100)
            budget_ms: total wall-clock budget in ms (default 5000)
            workers: number of parallel scorer Lambdas (auto if None)
            items_key: S3 cache key from previous call (skip cache + warmup)

        Returns:
            RankResult with .top, .n_scored, .cache_key, .wall_clock_ms
        """
        # Subtract fixed overhead: ~300ms network + ~200ms API handler
        # Server gets what's left for actual scoring.
        FIXED_OVERHEAD_MS = 500
        server_budget = max(100, budget_ms - FIXED_OVERHEAD_MS) if budget_ms else None
        body = {
            "target_class": target_class,
            "top": top,
            "budget_ms": server_budget,
        }
        if items_key:
            body["items_key"] = items_key
        elif items:
            payload_size = len(json.dumps(items, default=str).encode())
            if payload_size > 3 * 1024 * 1024:
                # Too large for single request. Cache in chunks, then
                # pass chunk keys for server to merge.
                bytes_per_item = payload_size / len(items)
                chunk_n = max(100, int(2.5 * 1024 * 1024 / bytes_per_item))
                chunk_keys = []
                for i in range(0, len(items), chunk_n):
                    cache = self._post("/cache-items", {"items": items[i:i+chunk_n]})
                    chunk_keys.append(cache["cache_key"])
                body["cache_chunks"] = chunk_keys
            else:
                body["items"] = items
        if workers:
            body["workers"] = workers

        resp = self._post(f"/rank/{self.model_id}", body)
        return RankResult(resp)

    def warmup(self, workers=30):
        """
        Warm up scorer Lambda containers. Call before get_batch_rank for
        guaranteed 1s budget at scale.

        Args:
            workers: number of containers to warm (default 30)

        Returns:
            dict with warmed count and wall_clock_ms
        """
        return self._post("/warmup", {"workers": workers})

    @classmethod
    def warmup_all(cls, scorers=5, endpoint=None, api_key=None):
        """
        Warm all Lambda functions: API, orchestrator, inference, and scorers.
        Call once at startup to eliminate cold starts on first train/predict.

        Args:
            scorers: number of scorer containers to warm (default 5)
            endpoint: API endpoint (default from env)
            api_key: API key (default from env)

        Returns:
            dict with per-function warm status and wall_clock_ms
        """
        ep = (endpoint or DEFAULT_ENDPOINT).rstrip("/")
        key = api_key or _get_api_key()
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        resp = requests.post(
            f"{ep}/warmup-all",
            json={"scorers": scorers},
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Model management
    # ------------------------------------------------------------------

    def to_json(self, path="snakeclassifier.json", stripped=False):
        """
        Download model as Snake-compatible JSON.

        Args:
            path: output file path
            stripped: if True, downloads inference-only model (no population, 95% smaller)

        Compatible with: algorithmeai.Snake("model.json")
        Stripped models support prediction/probability but not audit.
        """
        variant = "stripped" if stripped else "full"
        resp = self._post(f"/model/{self.model_id}/download", {"variant": variant})
        model_json = resp["model"]
        model_json.pop("_distributed", None)

        with open(path, "w") as f:
            json.dump(model_json, f)

        return path

    def info(self):
        """Model metadata: version, population size, layers, status."""
        return self._get(f"/model/{self.model_id}")

    def usage(self, limit=100):
        """Query API usage and costs for your API key."""
        return self._post("/usage", {"limit": limit})

    def get_report(self, test_data=None, target_class=None, top=50,
                   budget_ms=10000, output_path=None):
        """
        Generate a comprehensive audit report ZIP.

        Args:
            test_data: list[dict] to score and rank (optional — global audit if omitted)
            target_class: class to rank by (auto-picks first class if omitted)
            top: number of top items to include detailed audits for
            budget_ms: scoring budget in ms
            output_path: ZIP file path (default: snake_audit_<model_id>.zip)

        Returns:
            str: path to generated ZIP file
        """
        from .report import generate_report
        return generate_report(
            model=self,
            test_data=test_data,
            target_class=target_class,
            top=top,
            budget_ms=budget_ms,
            output_path=output_path,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _verify_model(self):
        info = self.info()
        if info.get("status") not in ("ready", "available"):
            raise RuntimeError(
                f"Model {self.model_id} status: {info.get('status', 'unknown')}"
            )

    def _post(self, path, body):
        resp = self._session.post(
            f"{self.endpoint}{path}",
            json=body,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _get(self, path):
        resp = self._session.get(
            f"{self.endpoint}{path}",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def __repr__(self):
        parts = [f"model_id='{self.model_id}'"]
        if self.wall_clock_ms:
            parts.append(f"{self.wall_clock_ms}ms")
        if self.log:
            parts.append(f"log='{self.log}'")
        return f"Snake({', '.join(parts)})"


class RankResult:
    """Result of get_batch_rank — top items sorted by target class probability."""

    def __init__(self, data):
        self._data = data
        self.top = data["top"]
        self.n_scored = data["n_scored"]
        self.n_total = data["n_total"]
        self.n_workers = data["n_workers"]
        self.cache_key = data.get("cache_key")
        self.wall_clock_ms = data["wall_clock_ms"]
        self.breakdown = data.get("breakdown", {})

    def __len__(self):
        return len(self.top)

    def __iter__(self):
        return iter(self.top)

    def __getitem__(self, idx):
        return self.top[idx]

    def __repr__(self):
        return (f"RankResult(top={len(self.top)}, scored={self.n_scored}/{self.n_total}, "
                f"{self.wall_clock_ms}ms, workers={self.n_workers})")
