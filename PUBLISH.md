# Publish to AppliedAIBedrockPlayground

This tree is the **`bedrock-playground/`** subtree from Cloudera Applied AI:

- Source repo: `https://github.com/royles/ClouderaAppliedAI`
- Source branch: **`cursor/bedrock-playground-1ffb`**

It is a **standalone Bedrock LLM playground** (no Customer 360 monorepo files at the repo root).

If automated pushes fail with **403**, add **`cursor[bot]`** as a collaborator on `AppliedAIBedrockPlayground`, then retry from a Cloud Agent.

## Refresh from ClouderaAppliedAI

```bash
git -C /path/to/ClouderaAppliedAI fetch origin cursor/bedrock-playground-1ffb
git archive origin/cursor/bedrock-playground-1ffb bedrock-playground \
  | tar -x --strip-components=1 -C /path/to/AppliedAIBedrockPlayground
```

Then commit and push `main` (or open a PR).
