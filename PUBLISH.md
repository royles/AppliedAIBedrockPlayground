# Publish to AppliedAIBedrockPlayground

This tree is a **standalone Bedrock LLM playground** (no Customer 360 monorepo files).

If automated pushes fail with **403**, add **`cursor[bot]`** as a collaborator on `AppliedAIBedrockPlayground`, then retry from a Cloud Agent. You can also push **`main`** from your machine using your GitHub credentials.

## Option A — Push this repo directly (SSH)

```bash
git remote -v   # should show AppliedAIBedrockPlayground
git push -u origin main
```

If `origin` is wrong:

```bash
git remote set-url origin git@github.com:royles/AppliedAIBedrockPlayground.git
git push -u origin main
```

## Option B — From ClouderaAppliedAI staging branch

A copy of this commit is on:

`https://github.com/royles/ClouderaAppliedAI` → branch **`applied-ai-bedrock-playground-main`**

```bash
git clone --branch applied-ai-bedrock-playground-main --single-branch \
  git@github.com:royles/ClouderaAppliedAI.git bedrock-playground-export
cd bedrock-playground-export
git remote set-url origin git@github.com:royles/AppliedAIBedrockPlayground.git
git push -u origin HEAD:main
```

## Grant access (optional)

To allow Cursor Cloud to push to the new repo in the future, add **`cursor[bot]`** as a collaborator on `AppliedAIBedrockPlayground`.
