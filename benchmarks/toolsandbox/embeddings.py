"""One local embedding service shared by all isolated ToolSandbox workers."""

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

QUERY_INSTRUCTION = (
    "Given a user request, retrieve tools that can help complete the request."
)


class CachedEncoder:
    def __init__(self, backend, directory, weights):
        self.backend, self.directory = backend, directory
        directory.mkdir(parents=True, exist_ok=True)
        if backend == "tool-embed-bf16":
            import torch
            from transformers import AutoModel, AutoTokenizer

            self.tokenizer = AutoTokenizer.from_pretrained(
                weights, local_files_only=True
            )
            self.model = AutoModel.from_pretrained(
                weights, dtype=torch.bfloat16, local_files_only=True
            )
            self.device = "mps" if torch.backends.mps.is_available() else "cpu"
            self.model.to(self.device).eval()

    def encode(self, texts, query=False):
        inputs = [
            f"Instruct: {QUERY_INSTRUCTION}\nQuery: {s}"
            if query and self.backend == "tool-embed-bf16"
            else s
            for s in texts
        ]
        paths = [
            self.directory
            / (hashlib.sha256((self.backend + "\0" + s).encode()).hexdigest() + ".json")
            for s in inputs
        ]
        missing = [i for i, p in enumerate(paths) if not p.exists()]
        for offset in range(0, len(missing), 3):
            batch = missing[offset : offset + 3]
            if self.backend == "bge-m3-ollama":
                body = json.dumps(
                    {"model": "bge-m3:latest", "input": [inputs[i] for i in batch]}
                ).encode()
                with urlopen(
                    Request("http://127.0.0.1:11434/api/embed", data=body), timeout=120
                ) as response:
                    vectors = json.load(response)["embeddings"]
            else:
                import torch

                encoded = self.tokenizer(
                    [inputs[i] for i in batch],
                    padding=True,
                    truncation=True,
                    max_length=1024,
                    return_tensors="pt",
                ).to(self.device)
                with torch.inference_mode():
                    hidden = self.model(**encoded).last_hidden_state
                    last = (
                        encoded.attention_mask
                        * torch.arange(
                            encoded.attention_mask.shape[1], device=self.device
                        )
                    ).argmax(dim=1)
                    rows = hidden[
                        torch.arange(len(batch), device=self.device), last
                    ].float()
                    vectors = (
                        torch.nn.functional.normalize(rows, p=2, dim=1).cpu().tolist()
                    )
            for i, vec in zip(batch, vectors, strict=True):
                tmp = paths[i].with_suffix(".part")
                tmp.write_text(json.dumps(vec, separators=(",", ":")))
                tmp.replace(paths[i])
        return [json.loads(p.read_text()) for p in paths]


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument(
        "--backend", choices=["tool-embed-bf16", "bge-m3-ollama"], required=True
    )
    cli.add_argument("--weights", type=Path)
    cli.add_argument("--cache", type=Path, required=True)
    cli.add_argument("--port", type=int, default=18492)
    args = cli.parse_args()
    encoder = CachedEncoder(args.backend, args.cache, args.weights)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/embed":
                self.send_error(404)
                return
            try:
                data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                vectors = encoder.encode(data["texts"], data["query"])
                payload = json.dumps(
                    {"vectors": vectors, "backend": args.backend}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:  # noqa: BLE001 -- avoid returning private server details
                self.send_error(500, type(exc).__name__)

        def log_message(self, *args):
            pass

    HTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
