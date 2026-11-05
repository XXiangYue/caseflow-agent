# Source and attribution

The project was separated from the author's integrated implementation commit
`f6818662fdf4d845732545c34b63776a3960b694`. `PROVENANCE.json` binds copied files to original hashes. Python package
names and the CLI were adapted for standalone use; historical measurements stay
bound to their original commit and protocols.


CaseFlow directly reuses Notebook's models and Markdown chunking from [XXiangYue/notebook](https://github.com/XXiangYue/notebook), commit 1a2f821285de417a2f5e0589c202ee0321e0e704. Only required files are vendored in upstream/notebook with its MIT LICENSE. The gateway, receipt schema, services integration, MCP interface and workflow evaluation are the new implementation.



Third-party files retain their original license notices. This packaging operation
does not assign a new blanket license to the author's original portfolio code.

The ToolSandbox extension downloads the separately licensed [Apple ToolSandbox source](https://github.com/apple/ToolSandbox/blob/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1/LICENSE). Tool-Embed-4B uses [the author's published checkpoint](https://huggingface.co/Lux1997/Tool-Embed-4B). The supplemental BGE-M3 embeddings use [the BAAI model](https://huggingface.co/BAAI/bge-m3). This repository publishes independently written adapters, aggregate results, compact numerical/state receipts and task IDs; obtain the simulator and model weights from their original sources.
