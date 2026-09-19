# Security Policy

## Reporting a vulnerability

Please **do not** open a public issue for security problems. Instead, report
privately via GitHub's *Security → Report a vulnerability* tab, or contact the
maintainer. We aim to acknowledge reports within a few days.

## What this project handles

- **Trivecta** is a local desktop application. It reads the images/video you
  give it and writes splat/mesh files locally. It does not phone home except to
  download optional AI model weights (from their official sources) when you ask
  it to.
- **SplatFlow** is a small local web server (`server.py`) that accepts video
  uploads and runs the reconstruction pipeline on the local GPU.

## Security protocols in this repository

- **No secrets are committed.** Credentials, tokens, `.env` files and local
  configuration are excluded by `.gitignore`. If you fork this project, never
  commit keys or tokens.
- **No model weights are bundled.** Optional AI weights (SAM, ALIKED/LightGlue,
  Metric3D) are downloaded by the application under their own licenses.
- **Localhost by default.** `splatflow/server.py` binds to `127.0.0.1:8088`
  only. It is intended to be reached through a tunnel.

## Before exposing SplatFlow to the internet

The upload endpoint is **unauthenticated** and runs an expensive GPU job. Before
putting it on a public URL:

1. **Add authentication** — a shared token checked by a dependency on
   `/api/upload` and `/api/status`, or put it behind Cloudflare Access.
   Example (FastAPI):
   ```python
   import os
   from fastapi import Header, HTTPException
   TOKEN = os.environ["SPLATFLOW_TOKEN"]
   def require_token(x_auth: str = Header(default="")):
       if x_auth != TOKEN:
           raise HTTPException(status_code=401)
   ```
2. **Rate-limit / queue** uploads so one client cannot exhaust the GPU.
3. **Cap upload size** (e.g. at the tunnel or in the server) to bound disk use.
4. **Isolate the process** — run the server under a limited user account and
   point `SS_INCOMING`/output folders at a scratch directory.
5. Prefer a **named Cloudflare Tunnel + Access** over a public quick tunnel.

## Out of scope

- Content of the media you process — only reconstruct captures you own or are
  authorised to use.
- Third-party components (Spirula Studio, CUDA/Vulkan drivers, model weights)
  are covered by their own security processes and licenses.
