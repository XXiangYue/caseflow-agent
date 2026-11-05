"""Initialize real MCP and read a real seeded service state, without inference."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from caseflow_agent.caseflow import Gateway
from caseflow_agent.caseflow_eval import seed, task_corpus
from caseflow_agent.caseflow_runtime import services
from caseflow_agent.common import ROOT, write_json

async def check(cfg, out):
    task = next(t for t in task_corpus() if t['split'] == 'dev' and t['family'] == 'normal' and t['index'] == 0)
    fixture = await asyncio.to_thread(seed, cfg, task, out)
    ledger = out / 'gateway.sqlite'
    Gateway(ledger, scope=fixture['session_scope'], subject='synthetic-operator', knowledge_url=cfg['knowledge'], tickets_url=cfg['tickets'], internal_token=cfg['token'], user_policy=task['policy'], skills_path=ROOT/'skills')
    config = {'ledger': str(ledger.resolve()), 'scope': fixture['session_scope'], 'subject': 'synthetic-operator', 'arm': 'W1', 'user_policy': task['policy']}
    env = {k: v for k, v in os.environ.items() if not any(x in k for x in ('API_KEY', 'ANTHROPIC_AUTH_TOKEN'))}
    env.update(CASEFLOW_SESSION=json.dumps(config), CASEFLOW_KNOWLEDGE_URL=cfg['knowledge'], CASEFLOW_TICKETS_URL=cfg['tickets'], CASEFLOW_INTERNAL_TOKEN=cfg['token'])
    params = StdioServerParameters(command=sys.executable, args=['-m', 'caseflow_agent.caseflow_mcp'], env=env)
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools
            result = await session.call_tool('tickets.get', {'id': fixture['ticket_id']})
            data = result.structured_content
            if data is None:
                data = json.loads(next(c.text for c in result.content if c.type == 'text'))
            assert data['ok'], data
            assert data['data']['id'] == fixture['ticket_id']
            assert len(tools) == 12
            return {'mcp_initialized': True, 'listed_tools': len(tools), 'actual_ticket_read': True, 'model_calls': 0}

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        p.error('Use a new output directory')
    a.out.mkdir(parents=True)
    with services() as cfg:
        summary = asyncio.run(check(cfg, a.out))
    write_json(a.out/'summary.json', summary)
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
