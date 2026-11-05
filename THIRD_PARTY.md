# Source and attribution

The project was separated from the author's integrated implementation commit
`f6818662fdf4d845732545c34b63776a3960b694`. `PROVENANCE.json` binds copied files to original hashes. Python package
names and the CLI were adapted for standalone use; historical measurements stay
bound to their original commit and protocols.


CaseFlow directly reuses Notebook's models and Markdown chunking from [XXiangYue/notebook](https://github.com/XXiangYue/notebook), commit 1a2f821285de417a2f5e0589c202ee0321e0e704. Only required files are vendored in upstream/notebook with its MIT LICENSE. The gateway, receipt schema, services integration, MCP interface and workflow evaluation are the new implementation.



Third-party files retain their original license notices. This packaging operation
does not assign a new blanket license to the author's original portfolio code.
