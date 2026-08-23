"""RAG chain via LlamaIndex.

This module ties together retrieval and generation into a single
question-answering pipeline using LlamaIndex LLM engines.
"""

from __future__ import annotations

import logging
from typing import Generator
import re

from llama_index.core import Settings
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from ragdoll.config import settings
from ragdoll.query.retriever import SearchResult, search

logger = logging.getLogger(__name__)

# ── Prompt templates ───────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Ragdoll, an expert assistant for engineering knowledge.
You answer questions based ONLY on the provided context from JIRA tickets, \
GitHub issues/PRs, Bitbucket PRs, and internal documentation.
If the context doesn't contain enough information, say so honestly.
Always cite the source document IDs when referencing specific information.
Be concise but thorough."""

RAG_PROMPT_TEMPLATE = """\
Use the following context to answer the question.
Each piece of context has a source ID in square brackets.

--- CONTEXT ---
{context}
--- END CONTEXT ---

Question: {question}

Answer (cite sources using [source_id]):"""

SUMMARIZE_PROMPT_TEMPLATE = """\
Summarize the following information retrieved from internal JIRA tickets, \
GitHub issues/PRs, and documentation. Be concise but capture all key points.
Cite source IDs in [brackets].

--- CONTEXT ---
{context}
--- END CONTEXT ---

Topic: {topic}

Summary:"""


CONDENSE_PROMPT_TEMPLATE = """\
Given the following conversation history and a follow-up question, determine if the follow-up question refers to a previous entity, project, or topic.
- If the question contains pronouns or implicit references (e.g. "how many of them are open?", "who created it?", "show me the comments"), rephrase it into a complete standalone question.
- If the question introduces a new topic, function, class, tool, or document (e.g. "what does calculate_checksum do?", "explain authentication"), DO NOT append previous project names or organizations. Return the question VERBATIM.
- If the question is already complete and self-contained, return it VERBATIM.

Return ONLY the standalone question, nothing else. No explanation, no quotes.

Chat History:
{chat_history}

Follow-up Question: {question}
Standalone Question:"""

INTENT_PROMPT = """\
Determine if the user's question requires searching a LIVE DATABASE for a list/aggregation of items.
Reply ONLY with "JIRA_DATABASE" (for Jira issues/tickets), "BITBUCKET_DATABASE" (for Bitbucket pull requests), "GITHUB_DATABASE" (for GitHub issues/PRs), or "KNOWLEDGE" (for technical documentation and general questions).

Question: {question}
Intent:"""

JQL_GENERATOR_PROMPT = """\
You are an expert Atlassian JIRA administrator.
Convert the user's natural language request into a valid JQL (Jira Query Language) string.
Return ONLY the raw JQL string, nothing else. No markdown formatting, no explanations.

Important Rules:
- JIRA project keys are uppercase short alphanumeric identifiers (e.g. MYPROJ, CORE, PROJA, MAIN).
- Do NOT include organization or server names (e.g. "myorg", "enterprise", "company", "jira") inside the project key.
- Example: "tickets in the myorg MYPROJ project" -> project = MYPROJ
- Example: "how many tickets in enterprise PROJA" -> project = PROJA
- Example: "open bugs in CORE" -> project = CORE AND statusCategory != Done AND type = Bug

User Request: {question}
JQL:"""

BITBUCKET_PARAM_GENERATOR_PROMPT = """\
You are an expert Bitbucket administrator.
Extract the project key, repository slug, and state (OPEN, MERGED, DECLINED, or ALL) from the user's request.
Return ONLY a comma-separated string: project,repo,state
If a value is not specified, guess a reasonable default. Do NOT use 'bitbucket' as a project or repo name.
(Hint: project keys are typically short uppercase identifiers like 'PROJ' and repo names are lowercase slugs like 'service').

User Request: {question}
Params:"""

GITHUB_PARAM_GENERATOR_PROMPT = """\
You are an expert GitHub administrator.
Known repositories in this environment: {known_repos}
Default organization/owner: {default_owner}

Extract the owner, repository, state (open, closed, or all), and type (issue, pr, or all) from the user's request.
If the user specifies only a repository name, match it against the known repositories list or use the default organization/owner.
Return ONLY a comma-separated string: owner,repo,state,type
If a value is not specified, guess a reasonable default. Do NOT use 'github' as an owner or repo name.

User Request: {question}
Params:"""


def _format_context(results: list[SearchResult]) -> str:
    """Format search results into a context block for the LLM."""
    parts: list[str] = []
    for r in results:
        source = r.metadata.get("doc_id", r.chunk_id)

        # Keep metadata concise to minimize prompt token overhead
        meta_items = []
        for key in ("source", "key", "title", "status", "author", "repo", "project"):
            if key in r.metadata and r.metadata[key]:
                meta_items.append(f"{key}: {r.metadata[key]}")
        meta_str = " | ".join(meta_items) if meta_items else "source: unknown"

        parts.append(f"[{source}] ({meta_str})\n{r.text.strip()}")
    return "\n\n".join(parts)


def query(
    question: str,
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Single-turn RAG query."""
    results = search(question, top_k=top_k, source_filter=source_filter)
    context = _format_context(results) if results else "(No relevant context found.)"
    prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=prompt),
    ]

    if stream:
        resp = Settings.llm.stream_chat(messages)
        return (chunk.delta for chunk in resp)

    resp = Settings.llm.chat(messages)
    return resp.message.content or ""


def summarize(
    topic: str,
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Summarize context retrieved for a topic."""
    results = search(topic, top_k=top_k, source_filter=source_filter)

    if not results:
        msg = "No relevant documents found for this topic."
        if stream:
            def _empty():
                yield msg
            return _empty()
        return msg

    context = _format_context(results)
    prompt = SUMMARIZE_PROMPT_TEMPLATE.format(context=context, topic=topic)

    messages = [
        ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
        ChatMessage(role=MessageRole.USER, content=prompt),
    ]

    if stream:
        resp = Settings.llm.stream_chat(messages)
        return (chunk.delta for chunk in resp)

    resp = Settings.llm.chat(messages)
    return resp.message.content or ""


def query_live_jira(jql: str) -> str:
    """Execute a JQL query directly against all configured JIRA APIs."""
    from llama_index.readers.jira import JiraReader
    from ragdoll.config import settings

    # Collect all server configs to query
    configs_to_query = []

    # Always include the top-level (global) default server if it's explicitly configured
    if settings.jira_url and settings.jira_url != "https://jira.example.com" and settings.jira_token:
        configs_to_query.append({
            "name": "default",
            "url": settings.jira_url,
            "user": settings.jira_user,
            "token": settings.jira_token,
            "auth_method": settings.jira_auth_method,
        })

    if settings.jira_servers:
        for name, cfg in settings.jira_servers.items():
            url = cfg.get("url", settings.jira_url)

            # Skip unconfigured dummy URLs
            if url == "https://jira.example.com":
                continue

            # Avoid adding the exact same server twice if the user duplicated it
            if any(c["url"] == url for c in configs_to_query):
                continue

            configs_to_query.append({
                "name": name,
                "url": url,
                "user": cfg.get("user", settings.jira_user),
                "token": cfg.get("token", settings.jira_token),
                "auth_method": cfg.get("auth_method", settings.jira_auth_method),
                "projects": cfg.get("projects", []),
            })

    # Clean accidental server/org names from project clause (e.g. project = "myorg MYPROJ" -> project = MYPROJ)
    known_server_keys = {k.lower() for k in settings.jira_servers.keys()} | {"jira", "primary", "secondary", "enterprise", "cloud", "server", "myorg"}
    def _clean_project_clause(match: re.Match) -> str:
        raw_val = match.group(1) or match.group(2) or match.group(3) or ""
        tokens = [t for t in re.findall(r"[A-Za-z0-9_]+", raw_val) if t.upper() not in ("AND", "OR", "NOT", "IN", "IS", "NULL", "EMPTY")]
        if len(tokens) > 1:
            filtered = [t for t in tokens if t.lower() not in known_server_keys]
            chosen = filtered[-1] if filtered else tokens[-1]
            return f"project = {chosen.upper()}"
        elif len(tokens) == 1:
            return f"project = {tokens[0].upper()}"
        return match.group(0)

    jql = re.sub(r"project\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_]+))", _clean_project_clause, jql, flags=re.IGNORECASE)

    # Extract requested project keys from JQL (e.g. project = MYPROJ, project in (PROJA, PROJB))
    project_matches = re.findall(r'project\s*(?:=|in)\s*\(?([A-Za-z0-9_,\s]+)\)?', jql, re.IGNORECASE)
    requested_projects = set()
    for match in project_matches:
        for p in re.findall(r'[A-Za-z0-9_]+', match):
            if p.upper() not in ("AND", "OR", "NOT", "IN", "IS", "NULL", "EMPTY"):
                requested_projects.add(p.upper())

    # Smart server routing: match servers that host the requested projects
    matched_configs = []
    unrestricted_configs = []
    for cfg in configs_to_query:
        server_projects = cfg.get("projects", [])
        if isinstance(server_projects, str):
            server_projects = [p.strip().upper() for p in server_projects.split(",") if p.strip()]
        else:
            server_projects = [p.strip().upper() for p in server_projects if isinstance(p, str)]

        if server_projects and requested_projects:
            if any(p in server_projects for p in requested_projects):
                matched_configs.append(cfg)
        elif not server_projects:
            unrestricted_configs.append(cfg)

    if matched_configs:
        targets = matched_configs
    elif requested_projects and unrestricted_configs:
        targets = unrestricted_configs
    else:
        targets = configs_to_query

    all_results = []
    for cfg in targets:
        server_url = cfg["url"]
        if server_url.startswith("https://"):
            server_url = server_url[8:]
        elif server_url.startswith("http://"):
            server_url = server_url[7:]

        try:
            if cfg["auth_method"] == "pat":
                reader = JiraReader(
                    PATauth={
                        "server_url": cfg["url"],
                        "api_token": cfg["token"],
                    }
                )
            else:
                reader = JiraReader(
                    email=cfg["user"],
                    api_token=cfg["token"],
                    server_url=server_url,
                )
            jira_client = reader.jira
            issues = jira_client.search_issues(jql, maxResults=50)

            if issues:
                all_results.append(
                    f"### Results from {cfg['name']} ({server_url}):\nFound {issues.total} total tickets. Showing top {len(issues)}:")
                for issue in issues:
                    key = issue.key
                    summary = issue.fields.summary
                    status = issue.fields.status.name if getattr(issue.fields, "status", None) else "Unknown"
                    issue_type = issue.fields.issuetype.name if getattr(issue.fields, "issuetype", None) else "Unknown"
                    priority = issue.fields.priority.name if getattr(issue.fields, "priority", None) else "None"
                    assignee = issue.fields.assignee.displayName if getattr(issue.fields, "assignee", None) else "Unassigned"
                    updated = getattr(issue.fields, "updated", "Unknown Date")
                    all_results.append(
                        f"- {key} [{issue_type} | Priority: {priority}] ({status}): {summary} | Assignee: {assignee} | Updated: {updated}")
            else:
                all_results.append(f"### Results from {cfg['name']} ({server_url}):\nFound 0 matching tickets.")
        except Exception as e:
            err_str = str(e)
            logger.debug("Jira server %s query failed: %s", cfg["name"], err_str)
            if "does not exist" in err_str.lower() or "not exist" in err_str.lower() or "not found" in err_str.lower():
                all_results.append(f"### Results from {cfg['name']} ({server_url}):\n(Project or field not present on this Jira instance)")
            else:
                first_line = err_str.splitlines()[0] if err_str else "Unknown error"
                all_results.append(f"### Results from {cfg['name']} ({server_url}):\n(Query note: {first_line})")

    if not all_results:
        return "No tickets found matching this JQL across any configured Jira servers."

    return "\n".join(all_results)


def query_live_bitbucket(project: str, repo: str, state: str = "OPEN") -> str:
    """Execute a query directly against configured Bitbucket APIs for PRs."""
    import requests
    from ragdoll.config import settings

    configs_to_query = []

    if settings.bitbucket_url and settings.bitbucket_url != "https://bitbucket.example.com" and settings.bitbucket_token:
        configs_to_query.append({
            "name": "default",
            "url": settings.bitbucket_url,
            "user": settings.bitbucket_user,
            "token": settings.bitbucket_token,
            "auth_method": settings.bitbucket_auth_method,
        })

    if settings.bitbucket_servers:
        for name, cfg in settings.bitbucket_servers.items():
            url = cfg.get("url", settings.bitbucket_url)
            if url == "https://bitbucket.example.com":
                continue
            if any(c["url"] == url for c in configs_to_query):
                continue
            configs_to_query.append({
                "name": name,
                "url": url,
                "user": cfg.get("user", settings.bitbucket_user),
                "token": cfg.get("token", settings.bitbucket_token),
                "auth_method": cfg.get("auth_method", settings.bitbucket_auth_method),
            })

    all_results = []
    for cfg in configs_to_query:
        server_url = cfg["url"]
        if server_url.endswith("/"):
            server_url = server_url[:-1]

        headers = {"Accept": "application/json"}
        if cfg["auth_method"] == "pat":
            headers["Authorization"] = f"Bearer {cfg['token']}"
        elif cfg["auth_method"] == "basic" and cfg["user"]:
            import base64
            auth = base64.b64encode(f"{cfg['user']}:{cfg['token']}".encode()).decode()
            headers["Authorization"] = f"Basic {auth}"

        prs_endpoint = f"{server_url}/rest/api/1.0/projects/{project}/repos/{repo}/pull-requests"
        params = {"state": state, "limit": 10}

        try:
            resp = requests.get(prs_endpoint, headers=headers, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            prs = data.get("values", [])

            clean_url = server_url.replace("https://", "").replace("http://", "")
            if prs:
                all_results.append(f"### Results from {cfg['name']} ({clean_url}) for {project}/{repo}:")
                for pr in prs:
                    pr_id = pr.get("id")
                    title = pr.get("title")
                    pr_state = pr.get("state")
                    author_dict = pr.get("author", {}).get("user", {})
                    author = author_dict.get("displayName") or author_dict.get("name") or "Unknown"
                    all_results.append(f"- PR-{pr_id} ({pr_state}): {title} | Author: {author}")
            else:
                all_results.append(f"### Results from {cfg['name']} ({clean_url}):\nNo PRs found for {project}/{repo} in state {state}.")
        except Exception as e:
            clean_url = server_url.replace("https://", "").replace("http://", "")
            err_str = str(e)
            logger.debug("Bitbucket server %s query failed: %s", cfg["name"], err_str)
            if "404" in err_str or "not found" in err_str.lower():
                all_results.append(
                    f"### Results from {cfg['name']} ({clean_url}):\n(Repository '{project}/{repo}' not found on this Bitbucket instance)")
            else:
                first_line = err_str.splitlines()[0] if err_str else "Unknown error"
                all_results.append(f"### Results from {cfg['name']} ({clean_url}):\n(Query note: {first_line})")

    if not all_results:
        return "No PRs found across any configured Bitbucket servers."
    return "\n".join(all_results)


def query_live_github(owner: str, repo: str, state: str = "open", item_type: str = "all") -> str:
    """Execute a query directly against GitHub API for issues/PRs."""
    import requests
    from ragdoll.config import settings

    # Resolve target server based on repo mapping
    target_server = None
    target_repo_str = f"{owner}/{repo}".lower()
    if settings.github_servers:
        for name, s_cfg in settings.github_servers.items():
            server_repos = s_cfg.get("repos", [])
            if isinstance(server_repos, str):
                server_repos = [r.strip().lower() for r in server_repos.split(",") if r.strip()]
            else:
                server_repos = [r.strip().lower() for r in server_repos if isinstance(r, str)]

            if target_repo_str in server_repos or any(r.endswith(f"/{repo}".lower()) for r in server_repos):
                target_server = name
                break

    cfg = settings.get_github_config(target_server)
    url = cfg["url"]
    token = cfg["token"]

    if url.endswith("/"):
        url = url[:-1]

    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    endpoint = f"{url}/search/issues"

    # Build query string
    query_parts = [f"repo:{owner}/{repo}"]

    if state.lower() in ["open", "closed"]:
        query_parts.append(f"state:{state.lower()}")

    if item_type.lower() == "issue":
        query_parts.append("type:issue")
    elif item_type.lower() == "pr" or item_type.lower() == "pull-request":
        query_parts.append("type:pr")

    query_str = " ".join(query_parts)

    params = {"q": query_str, "per_page": 50}

    try:
        resp = requests.get(endpoint, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        total_count = data.get("total_count", 0)
        items = data.get("items", [])

        type_str = "issues/PRs"
        if item_type.lower() == "issue":
            type_str = "issues"
        elif item_type.lower() == "pr":
            type_str = "pull requests"

        results = [
            f"### Results from GitHub ({url}):\nFound exact count of {total_count} {state} {type_str} for {owner}/{repo}. (Tell the user this exact total_count). Showing top {len(items)} for context:"]
        for item in items:
            number = item["number"]
            title = item["title"]
            item_state = item["state"]
            user = item.get("user", {}).get("login", "Unknown")
            is_pr = "pull_request" in item
            type_label = "PR" if is_pr else "Issue"

            results.append(f"- {type_label}-{number} ({item_state}): {title} | Author: {user}")

        return "\n".join(results)
    except Exception as e:
        err_str = str(e)
        logger.debug("GitHub query failed for %s/%s: %s", owner, repo, err_str)
        first_line = err_str.splitlines()[0] if err_str else "Unknown error"
        return f"### Results from GitHub ({url}):\nFailed to query GitHub for {owner}/{repo}: {first_line}"


def chat_with_context(
    messages: list[dict[str, str]],
    top_k: int | None = None,
    source_filter: str | None = None,
    stream: bool = False,
) -> str | Generator[str, None, None]:
    """Chat with RAG context injected from the latest user message."""
    user_query = ""
    for msg in reversed(messages):
        if msg["role"] == "user":
            user_query = msg["content"]
            # Clean up Open WebUI's injected chat history
            user_query = re.sub(r'<chat_history>.*?</chat_history>', '', user_query, flags=re.DOTALL).strip()
            break

    llama_messages = []

    if not user_query or user_query.startswith("### Task:\n"):
        # Just normal chat without RAG (or fast-path for Open WebUI background tasks)
        for msg in messages:
            role = MessageRole(msg["role"])
            llama_messages.append(ChatMessage(role=role, content=msg["content"]))
    else:
        # Context resolution: Reformulate follow-up questions using prior chat history
        search_query = user_query
        if len(messages) > 1:
            history_lines = []
            for m in messages[:-1]:
                if m.get("role") in ("user", "assistant"):
                    role_label = "User" if m["role"] == "user" else "Assistant"
                    content_snippet = m["content"].strip()
                    if len(content_snippet) > 300:
                        content_snippet = content_snippet[:300] + "..."
                    history_lines.append(f"{role_label}: {content_snippet}")

            chat_history_str = "\n".join(history_lines[-6:])
            if chat_history_str.strip():
                try:
                    condense_msg = Settings.llm.chat([
                        ChatMessage(
                            role=MessageRole.USER,
                            content=CONDENSE_PROMPT_TEMPLATE.format(
                                chat_history=chat_history_str,
                                question=user_query,
                            ),
                        )
                    ])
                    condensed = condense_msg.message.content.strip().strip("\'\"")
                    if condensed and len(condensed) >= 3 and not condensed.lower().startswith("error"):
                        logger.info("Conversational Context Resolved: '%s' -> '%s'", user_query, condensed)
                        search_query = condensed
                except Exception as e:
                    logger.debug("Query condensation failed: %s", e)

        # Route query: Database vs Knowledge
        try:
            intent_msg = Settings.llm.chat([ChatMessage(role=MessageRole.USER, content=INTENT_PROMPT.format(question=search_query))])
            intent = intent_msg.message.content.strip().upper()
            logger.info("Query Intent Classified as: %s", intent)
        except Exception as e:
            logger.warning("Intent classification failed: %s", e)
            intent = "KNOWLEDGE"

        if "JIRA_DATABASE" in intent or ("DATABASE" in intent and "BITBUCKET" not in intent and "GITHUB" not in intent):
            logger.info("Routing query to Live JIRA Database...")
            try:
                jql_msg = Settings.llm.chat([ChatMessage(role=MessageRole.USER, content=JQL_GENERATOR_PROMPT.format(question=search_query))])
                jql = jql_msg.message.content.strip()
                jql = re.sub(r"^```jql\s*|```\s*$", "", jql, flags=re.IGNORECASE).strip()
                logger.info("Generated JQL: %s", jql)

                live_results = query_live_jira(jql)
                system_content = f"{SYSTEM_PROMPT}\n\n--- LIVE DATABASE RESULTS ---\n{live_results}\n--- END RESULTS ---"
            except Exception as e:
                logger.error("JQL Generation failed: %s", e)
                system_content = f"{SYSTEM_PROMPT}\n\n(Failed to query live database.)"

        elif "BITBUCKET_DATABASE" in intent:
            logger.info("Routing query to Live Bitbucket Database...")
            try:
                bb_msg = Settings.llm.chat(
                    [ChatMessage(role=MessageRole.USER, content=BITBUCKET_PARAM_GENERATOR_PROMPT.format(question=search_query))])
                params_str = bb_msg.message.content.strip()

                project, repo, state = "UNKNOWN", "UNKNOWN", "ALL"
                parts = [p.strip() for p in params_str.split(",")]
                if len(parts) >= 1:
                    project = parts[0]
                if len(parts) >= 2:
                    repo = parts[1]
                if len(parts) >= 3:
                    state = parts[2]

                logger.info("Parsed Bitbucket params: project=%s, repo=%s, state=%s", project, repo, state)
                live_results = query_live_bitbucket(project, repo, state)
                system_content = f"{SYSTEM_PROMPT}\n\n--- LIVE DATABASE RESULTS ---\n{live_results}\n--- END RESULTS ---"
            except Exception as e:
                logger.error("Bitbucket Parameter Parsing failed: %s", e)
                system_content = f"{SYSTEM_PROMPT}\n\n(Failed to query live Bitbucket database.)"

        elif "GITHUB_DATABASE" in intent:
            logger.info("Routing query to Live GitHub Database...")
            try:
                known_repos = settings.get_all_github_repos()
                known_repos_str = ", ".join(known_repos) if known_repos else "None configured"
                default_owner = settings.github_default_owner or "None"

                prompt_text = GITHUB_PARAM_GENERATOR_PROMPT.format(
                    question=search_query,
                    known_repos=known_repos_str,
                    default_owner=default_owner,
                )
                gh_msg = Settings.llm.chat([ChatMessage(role=MessageRole.USER, content=prompt_text)])
                params_str = gh_msg.message.content.strip()

                owner, repo, state, item_type = "UNKNOWN", "UNKNOWN", "all", "all"
                parts = [p.strip() for p in params_str.split(",")]
                if len(parts) >= 1:
                    owner = parts[0]
                if len(parts) >= 2:
                    repo = parts[1]
                if len(parts) >= 3:
                    state = parts[2]
                if len(parts) >= 4:
                    item_type = parts[3]

                # Fall back to default_owner if owner was unresolved
                if (not owner or owner.upper() == "UNKNOWN") and settings.github_default_owner:
                    owner = settings.github_default_owner

                logger.info("Parsed GitHub params: owner=%s, repo=%s, state=%s, type=%s", owner, repo, state, item_type)
                live_results = query_live_github(owner, repo, state, item_type)
                system_content = f"{SYSTEM_PROMPT}\n\n--- LIVE DATABASE RESULTS ---\n{live_results}\n--- END RESULTS ---"
            except Exception as e:
                logger.error("GitHub Parameter Parsing failed: %s", e)
                system_content = f"{SYSTEM_PROMPT}\n\n(Failed to query live GitHub database.)"

        else:
            # Retrieve context.
            results = search(search_query, top_k=top_k, source_filter=source_filter)
            context = _format_context(results) if results else "(No relevant context found.)"
            system_content = f"{SYSTEM_PROMPT}\n\n--- RETRIEVED CONTEXT ---\n{context}\n--- END CONTEXT ---"

        # Build augmented message list with context as system prompt.
        llama_messages.append(ChatMessage(role=MessageRole.SYSTEM, content=system_content))

        # Add recent conversation history (last 3 exchanges / 6 messages)
        recent_messages = [m for m in messages if m.get("role") != "system"][-6:]
        for msg in recent_messages:
            role = MessageRole(msg["role"])
            llama_messages.append(ChatMessage(role=role, content=msg["content"]))

    if stream:
        resp = Settings.llm.stream_chat(llama_messages)
        return (chunk.delta or "" for chunk in resp)

    resp = Settings.llm.chat(llama_messages)
    return resp.message.content or ""
