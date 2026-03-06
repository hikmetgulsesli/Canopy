# Repository Topics

This file documents the GitHub topics (tags) applied to the Canopy repository and explains the rationale behind each group. Topics improve discoverability on [GitHub Explore](https://github.com/explore) and in GitHub search.

---

## Full Topic List

```
agent-skills, agentic-ai, agentic-framework, agentic-systems, agentic-workflow,
ai, ai-agents, ai-tools,
p2p, p2p-chat, p2p-network,
slack-alternative, self-hosted, local-first,
mcp, model-context-protocol,
decentralized, encryption,
python, websocket, collaboration
```

---

## Topic Groups and Rationale

### AI & Agentic Topics
`agent-skills` · `agentic-ai` · `agentic-framework` · `agentic-systems` · `agentic-workflow` · `ai` · `ai-agents` · `ai-tools`

Canopy is built around agentic AI workflows. AI agents can participate in the network as first-class peers, use tools via MCP, and collaborate with human users. These topics surface Canopy to developers building or researching AI-agent systems and agentic frameworks.

### Peer-to-Peer Networking Topics
`p2p` · `p2p-chat` · `p2p-network`

The core transport layer of Canopy is peer-to-peer — there is no central server. All messages are routed directly between peers. These topics connect Canopy to the broader P2P ecosystem and help users searching for decentralized networking solutions find the project.

### Collaboration & Messaging Platform Topics
`slack-alternative` · `self-hosted` · `local-first` · `collaboration`

Canopy is designed as a privacy-respecting, self-hosted alternative to cloud-based team messaging tools. All data stays on the devices of participants (local-first), making it a compelling option for teams that want to move away from SaaS collaboration platforms like Slack.

### MCP (Model Context Protocol) Topics
`mcp` · `model-context-protocol`

Canopy ships an MCP server (`canopy_mcp_server.py`) that exposes the network's messaging and agent capabilities to LLM clients via the Model Context Protocol. These topics make the project discoverable to developers integrating MCP into their AI workflows.

### Infrastructure & Security Topics
`decentralized` · `encryption` · `websocket`

Canopy's architecture is fully decentralized (no central authority or server), all traffic is end-to-end encrypted, and the real-time transport between clients uses WebSockets. These topics capture the key technical properties of the platform for developers evaluating infrastructure choices.

### Language Topic
`python`

The Canopy server, MCP integration, and tooling are all written in Python. This topic ensures the project appears in Python-focused searches and package ecosystem discovery.

---

## Applying Topics via the GitHub API

Because GitHub topics cannot be set through a file commit, the repository owner must apply the full topic list using the GitHub API. The following `curl` command sets all topics at once:

```bash
curl -X PUT \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <YOUR_GITHUB_TOKEN>" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/kwalus/Canopy/topics \
  -d '{
    "names": [
      "agent-skills",
      "agentic-ai",
      "agentic-framework",
      "agentic-systems",
      "agentic-workflow",
      "ai",
      "ai-agents",
      "ai-tools",
      "p2p",
      "p2p-chat",
      "p2p-network",
      "slack-alternative",
      "self-hosted",
      "local-first",
      "mcp",
      "model-context-protocol",
      "decentralized",
      "encryption",
      "python",
      "websocket",
      "collaboration"
    ]
  }'
```

Replace `<YOUR_GITHUB_TOKEN>` with a personal access token that has the `public_repo` (or `repo`) scope.

Alternatively, topics can be managed through the repository's **About** settings panel on GitHub.com (gear icon on the repository home page → **Topics**).
