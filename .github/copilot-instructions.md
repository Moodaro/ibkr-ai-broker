# Copilot Instructions

## General principles

- Prefer **small PRs** (<=300 LOC) and incremental changes
- Always **add/update tests** for any behavior change
- Do not change public schemas without updating docs and migrations
- Keep all trade-writing paths behind **RiskGate + ApprovalToken**
- Use **structured logging** and emit an **AuditEvent** for every state transition

## Code generation rules

### Before implementing new broker endpoints
1. Add adapter interface method first (in `Protocol`)
2. Add fake/mocked implementation for tests
3. Then implement real adapter
4. Add integration tests with both fake and real adapter

### When adding new order types or trade logic
1. Define schema in `packages/schemas/` first
2. Add validation tests
3. Implement simulator support
4. Add risk rules if needed
5. Update audit events
6. Add E2E test

### When modifying risk rules
1. Update `risk_policy.yml` first
2. Add property-based tests (Hypothesis) for invariants
3. Document rule in code comments
4. Update docs/risk-rules.md

## Safety checklist

Before merging any PR that touches trade execution:

- [ ] All write operations require `ApprovalToken`
- [ ] Schema validation is strict (no `extra="allow"`)
- [ ] Audit events are emitted
- [ ] Tests cover rejection cases
- [ ] Risk rules are evaluated
- [ ] No hardcoded credentials or sensitive data

## Testing requirements

- Unit tests for all new functions
- Integration tests for broker adapters
- Property-based tests for risk rules
- E2E test for complete flows
- Coverage must not decrease

## Documentation

- Update AGENTS.md if adding new commands
- Add ADR in `docs/adr/` for significant decisions
- Update README.md if changing setup process
- Add docstrings with examples for public APIs

## Commit messages

Use conventional commits:

- `feat:` new feature
- `fix:` bug fix
- `refactor:` code restructuring
- `test:` adding tests
- `docs:` documentation
- `chore:` maintenance

## Dependencies

- Minimize external dependencies
- Prefer standard library when possible
- Pin versions in `pyproject.toml`
- Document why each dependency is needed

## Error handling

- Never catch and ignore exceptions silently
- Log all errors with context (correlation ID)
- Return structured error responses
- Emit audit event for errors in critical paths

## Performance

- Avoid premature optimization
- Measure before optimizing
- Keep simulator fast (<100ms for typical case)
- Use connection pooling for database
- Implement caching only when proven necessary

---

**Remember**: Code should be boring, obvious, and safe. Cleverness is the enemy.
