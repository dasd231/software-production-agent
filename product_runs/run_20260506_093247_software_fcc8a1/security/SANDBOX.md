# Frontend Sandbox

The product UI previews `frontend/index.html` inside an iframe with:

- `sandbox="allow-scripts"`
- no `allow-same-origin`
- no form, popup, download, or top-navigation permission
- CSP blocking network access, external scripts, objects, forms, and parent embedding outside the UI

The generated JavaScript is never executed by the agent loop. Static verification only scans
the generated files for high-risk patterns.
