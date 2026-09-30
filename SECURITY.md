# Security policy

TixLab is a learning project, but security reports are welcome.

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting instead:
**Security → Report a vulnerability** on this repository.

Include what you found, how to reproduce it, and the affected image tag or commit.
You should get a reply within a week.

## What's in place

- Secret scanning with push protection, and gitleaks in CI and as a pre-commit hook
- CodeQL (Python, JavaScript, GitHub Actions) and dependency review on every pull request
- Trivy scan of every image; fixable HIGH/CRITICAL findings block publishing
- Hash-pinned Python dependencies and SHA-pinned GitHub Actions, kept current by Dependabot
- Images signed with cosign (keyless) with an attached SPDX SBOM. Verify with:

```bash
cosign verify ghcr.io/denny2020/tixlab-api:<tag> \
  --certificate-identity-regexp '^https://github.com/Denny2020/tixlab-app/.github/workflows/ci.yaml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```
