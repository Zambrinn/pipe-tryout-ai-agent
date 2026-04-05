"""
AI Code Review Script
=====================
Called by the GitHub Actions workflow on every pull request.

Required environment variables
-------------------------------
GITHUB_TOKEN  – GitHub token injected automatically by Actions (secrets.GITHUB_TOKEN)
OPENAI_API_KEY – OpenAI API key stored as a repository secret
PR_NUMBER      – Pull-request number (set by the workflow)
REPO           – "owner/repo" string (set by the workflow)
BASE_SHA       – Base commit SHA of the PR
HEAD_SHA       – Head commit SHA of the PR
"""

import os
import sys
import requests
from openai import OpenAI, OpenAIError

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_REQUIRED_ENV_VARS = [
    "GITHUB_TOKEN",
    "OPENAI_API_KEY",
    "PR_NUMBER",
    "REPO",
    "BASE_SHA",
    "HEAD_SHA",
]

_missing = [v for v in _REQUIRED_ENV_VARS if not os.environ.get(v)]
if _missing:
    sys.exit(
        f"ERROR: The following required environment variables are not set: "
        f"{', '.join(_missing)}\n"
        f"Make sure all secrets and workflow inputs are configured correctly."
    )

GITHUB_TOKEN = os.environ["GITHUB_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
PR_NUMBER = os.environ["PR_NUMBER"]
REPO = os.environ["REPO"]
BASE_SHA = os.environ["BASE_SHA"]
HEAD_SHA = os.environ["HEAD_SHA"]

GITHUB_API = "https://api.github.com"
GITHUB_HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

# Maximum number of characters of diff sent to the model.
# GPT-4o supports ~128 k tokens; 12 000 chars ≈ 3 000 tokens, leaving ample
# room for the system prompt, file list, and the model's reply.
MAX_DIFF_CHARS = 12_000

openai_client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def get_pr_commits() -> list[dict]:
    """Return the list of commits on this PR from the GitHub API."""
    url = f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}/commits"
    try:
        resp = requests.get(url, headers=GITHUB_HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"ERROR: Failed to fetch PR commits from GitHub API: {exc}")
    return resp.json()


def get_pr_files() -> list[dict]:
    """Return the list of files changed by this PR from the GitHub API."""
    url = f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}/files"
    try:
        resp = requests.get(url, headers=GITHUB_HEADERS, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"ERROR: Failed to fetch PR files from GitHub API: {exc}")
    return resp.json()


def post_pr_comment(body: str) -> None:
    """Post *body* as a comment on the pull request."""
    url = f"{GITHUB_API}/repos/{REPO}/issues/{PR_NUMBER}/comments"
    payload = {"body": body}
    try:
        resp = requests.post(url, headers=GITHUB_HEADERS, json=payload, timeout=30)
        resp.raise_for_status()
    except requests.RequestException as exc:
        sys.exit(f"ERROR: Failed to post comment to GitHub API: {exc}")
    print(f"Comment posted: {resp.json().get('html_url', '')}")


# ---------------------------------------------------------------------------
# AI helpers
# ---------------------------------------------------------------------------

def build_review_prompt(
    commits: list[dict], files: list[dict], diff_text: str, *, truncated: bool = False
) -> str:
    """Compose the prompt that is sent to the AI model."""
    commit_lines = "\n".join(
        f"- {c['sha'][:10]}  {c['commit']['message'].splitlines()[0]}"
        for c in commits
    )
    file_lines = "\n".join(
        f"- {f['filename']}  (+{f['additions']} / -{f['deletions']})"
        for f in files
    )

    truncation_note = (
        f"\n\n> ⚠️ **Note:** The diff was truncated to {MAX_DIFF_CHARS} characters. "
        "Some changes at the end may not be shown."
        if truncated
        else ""
    )

    return f"""You are an expert code reviewer. A pull request has been opened with the following changes.

## Commits
{commit_lines}

## Changed files
{file_lines}

## Diff{truncation_note}
```diff
{diff_text}
```

Please review the code changes above and provide:
1. **Summary** – a brief description of what the PR does.
2. **Potential issues** – bugs, security concerns, logic errors, or style problems.
3. **Suggestions** – concrete improvements the author should consider.
4. **Overall verdict** – Approve / Request changes / Needs discussion.

Be concise, constructive, and specific. Reference filenames and line content where relevant."""


def call_ai_agent(prompt: str) -> str:
    """Send *prompt* to the OpenAI chat completion endpoint and return the reply."""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a senior software engineer performing a pull-request "
                        "code review. Provide clear, actionable feedback."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
    except OpenAIError as exc:
        sys.exit(
            f"ERROR: OpenAI API call failed: {exc}\n"
            f"Check that OPENAI_API_KEY is valid and the model is available."
        )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"Reviewing PR #{PR_NUMBER} in {REPO}")
    print(f"Base SHA : {BASE_SHA[:10]}")
    print(f"Head SHA : {HEAD_SHA[:10]}")

    # Fetch data from GitHub
    commits = get_pr_commits()
    files = get_pr_files()

    print(f"Commits  : {len(commits)}")
    print(f"Files    : {len(files)}")

    # Build diff text from the patch hunks returned by the files endpoint
    diff_parts: list[str] = []
    for f in files:
        patch = f.get("patch", "")
        if patch:
            diff_parts.append(f"--- {f['filename']}\n{patch}")
    full_diff = "\n\n".join(diff_parts)

    truncated = False
    if len(full_diff) > MAX_DIFF_CHARS:
        # Snap to the last newline within the limit to avoid cutting mid-line.
        cut = full_diff.rfind("\n", 0, MAX_DIFF_CHARS)
        diff_text = full_diff[: cut if cut != -1 else MAX_DIFF_CHARS]
        truncated = True
    else:
        diff_text = full_diff

    if not diff_text:
        print("No diff content found; skipping AI review.")
        return

    # Call the AI agent
    prompt = build_review_prompt(commits, files, diff_text, truncated=truncated)
    print("Sending diff to AI agent…")
    review = call_ai_agent(prompt)
    print("AI review received.")

    # Format the comment
    sha_range = f"`{BASE_SHA[:10]}` → `{HEAD_SHA[:10]}`"
    comment = (
        f"## 🤖 AI Code Review\n\n"
        f"**Commits reviewed:** {sha_range} ({len(commits)} commit(s))\n"
        f"**Files changed:** {len(files)}\n\n"
        f"---\n\n"
        f"{review}\n\n"
        f"---\n"
        f"*Generated automatically by the AI Code Review pipeline.*"
    )

    post_pr_comment(comment)


if __name__ == "__main__":
    main()
