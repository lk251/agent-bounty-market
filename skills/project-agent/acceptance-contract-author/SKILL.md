name: acceptance-contract-author
version: 0.1.0
category: project-agent
provenance: agent-bounty-market issue-2

# Acceptance Contract Author

## When It Applies

Use this skill when writing the acceptance contract for a candidate that may be
funded.

## Inputs And Required Evidence

- issue reference;
- repository;
- base commit;
- protected verifier ID and digest if available;
- allowed paths and forbidden paths if policy supplies them;
- concise acceptance summary.

## Refusal Conditions

Do not write a fundable contract when there is no protected verifier, no base
commit, no repository issue reference, or acceptance depends on subjective
judgment alone.

## Output Contract

The `acceptance_contract` object must include at least title, issue_ref,
repo_full_name, base_commit, verifier_id, and acceptance_summary. Add bounded
path policy when known.

## Budget And Safety

Do not include private prompts, credentials, or unnecessary repository content.
Do not authorize spending; trusted host policy decides.

## Example

Acceptance can be "the platform-owned Motoko issue #1 verifier accepts the
candidate against base SHA X."

## Counterexample

Acceptance cannot be "maintainer feels the refactor is better" unless a human
approval path explicitly handles it.
