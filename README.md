# pipe-tryout-ai-agent

An automated CI/CD pipeline that calls an AI agent every time a pull request is opened (or updated) to review the changed files and commits.

---

## How it works

1. A pull request is **opened**, **synchronised**, or **reopened**.
2. The GitHub Actions workflow (`.github/workflows/ai-code-review.yml`) is triggered.
3. A Python script (`scripts/ai_review.py`) runs inside the workflow and:
   - Fetches the list of **commits** on the PR (including their SHA hashes and messages).
   - Fetches the list of **changed files** and their diffs from the GitHub API.
   - Sends the commit list, file list, and diff to **OpenAI GPT-4o** for a code review.
4. The AI-generated review is posted back as a **comment on the pull request**.

---

## Setup

### 1. Add the required secret

| Secret | Description |
|---|---|
| `OPENAI_API_KEY` | Your [OpenAI API key](https://platform.openai.com/api-keys). |

Go to **Settings → Secrets and variables → Actions → New repository secret** and add `OPENAI_API_KEY`.

> `GITHUB_TOKEN` is provided automatically by GitHub Actions — no manual configuration needed.

### 2. Open a pull request

That's it! Every PR will now receive an automated AI code review comment.

---

## Repository structure

```
.github/
  workflows/
    ai-code-review.yml   # GitHub Actions workflow definition
scripts/
  ai_review.py           # Python script: fetches PR data, calls AI, posts comment
README.md
```

---

## Local testing

You can run the review script locally by exporting the required variables:

```bash
export GITHUB_TOKEN="ghp_..."
export OPENAI_API_KEY="sk-..."
export PR_NUMBER="1"
export REPO="owner/repo"
export BASE_SHA="abc1234567"
export HEAD_SHA="def9876543"

python scripts/ai_review.py
```
