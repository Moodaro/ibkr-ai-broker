## Pull Request Checklist

### Description
<!-- Describe what this PR does and why -->

### Type of change
- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that causes existing functionality to change)
- [ ] Refactoring (no functional changes)
- [ ] Documentation update

### Related issues
<!-- Link to related issues: Fixes #123, Relates to #456 -->

### Changes made
<!-- List main changes -->
- 
- 
- 

### Testing
- [ ] Unit tests added/updated
- [ ] Integration tests added/updated (if applicable)
- [ ] Property-based tests added (if modifying risk rules)
- [ ] E2E tests pass
- [ ] All tests pass locally (`pytest`)

### Code quality
- [ ] Linting passes (`ruff check .`)
- [ ] Formatting is correct (`ruff format .`)
- [ ] Type checking passes (`pyright` or `mypy`)
- [ ] Pre-commit hooks pass
- [ ] Code coverage maintained or improved

### Safety (for trade-related changes)
- [ ] All write operations require `ApprovalToken`
- [ ] Schema validation is strict
- [ ] Audit events emitted for state changes
- [ ] Risk rules evaluated
- [ ] No hardcoded credentials or secrets
- [ ] Error handling is comprehensive

### Documentation
- [ ] AGENTS.md updated (if adding commands)
- [ ] README.md updated (if changing setup)
- [ ] ADR added (if significant architectural decision)
- [ ] Docstrings added/updated
- [ ] Comments explain "why" not "what"

### Deployment considerations
- [ ] Database migrations needed? (if yes, provide migration script)
- [ ] Environment variables added/changed? (if yes, document in AGENTS.md)
- [ ] Breaking API changes? (if yes, document migration path)
- [ ] Risk policy changes? (if yes, document impact)

### Screenshots/Demo
<!-- For UI changes, add screenshots or demo video -->

---

### Reviewer notes
<!-- Any specific areas you want reviewers to focus on? -->

### Post-merge tasks
<!-- Any follow-up work needed after merge? -->
- [ ] 
