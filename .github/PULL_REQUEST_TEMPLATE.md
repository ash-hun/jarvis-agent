## Summary

<!-- What does this PR do? One or two sentences. Link the related issue if any: Closes #123 -->

## Changes

<!-- Bullet list of concrete changes. Focus on *what* changed, not why (that's in the commit messages). -->

- 

## Layer Impact

<!-- Check all layers touched by this PR -->
- [ ] `model_layer`
- [ ] `agent_layer`
- [ ] `core/policy`
- [ ] `core/tools`
- [ ] `core/skills`
- [ ] `core/plugins`
- [ ] `ui`
- [ ] `config`
- [ ] `tests`
- [ ] `docs` / `CLAUDE.md`

## Test Plan

- [ ] `uv run pytest` passes (97/97)
- [ ] `uv run ruff check .` clean
- [ ] `uv run mypy src/` clean
- [ ] New tests added for new behavior
- [ ] No real API calls in tests (FauxProvider only)

## Security Checklist

<!-- Skip items that are not relevant to this PR -->
- [ ] No secrets or API keys hardcoded
- [ ] Security pipeline order not changed (`Validate → Auth → Policy → Sandbox`)
- [ ] New tools requiring approval added to `require_approval_for`
- [ ] Dependency direction not violated (`model_layer` does not import `core`)
